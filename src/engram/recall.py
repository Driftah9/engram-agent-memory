"""NL-robust hybrid recall over an engram index. NEXUS:PORTABLE.

A raw natural-language prompt ("how is my memory handled in the live system") should
NOT be fed to FTS as an implicit-AND query — almost nothing matches every token, so
recall comes back empty. `smart_recall` scores every indexed SECTION on two signals:

- keyword overlap: stopword-stripped content words present in the section
- semantic similarity: cosine between the query embedding and the section's stored
  vector (local Ollama nomic-embed-text; fail-open to keyword-only if unavailable)

and returns only sections that clear a relevance floor — it never pads results to k
with weak single-keyword matches or bare node descriptions (the old behavior that
made ~60% of injected recall marginal-or-irrelevant, measured 2026-07-26).

Pure stdlib; no assumptions about install location.
"""
import re
from typing import List, Dict

_STOP = {
    "the", "and", "for", "are", "but", "not", "you", "your", "with", "this", "that",
    "from", "what", "how", "why", "when", "where", "which", "who", "have", "has", "had",
    "was", "were", "will", "would", "can", "could", "should", "into", "out", "about",
    "did", "does", "doing", "done", "get", "got", "use", "used", "using", "via", "now",
    "live", "system", "based", "thing", "things", "like", "just", "also", "any", "all",
    "let", "lets", "its", "their", "they", "them", "our", "ours", "may", "per",
}

# Relevance floors (calibrated 2026-07-26 against a labeled 12-query operator
# scripts/benchmark_recall.py). Absolute cosine thresholds don't discriminate —
# nomic-embed similarities compress into ~0.4-0.7 for everything — so the vector
# signal is used as a z-score against the query's own candidate distribution.
# A hit must clear the floor AND stay within TOP_GAP of the best hit's score
# (kills the padded tail of weak matches below a genuinely strong top hit).
VEC_Z_STRONG = 2.0
VEC_Z_SUPPORT = 0.8
KW_STRONG_FRAC = 0.4
TOP_GAP = 0.85


def keywords(query: str, cap: int = 10) -> List[str]:
    """Lowercase content words from a query, stopwords removed, deduped, capped."""
    out: List[str] = []
    for t in re.findall(r"[a-zA-Z0-9_]{3,}", (query or "").lower()):
        if t in _STOP or t in out:
            continue
        out.append(t)
    return out[:cap]


def _relevant(kw_hits: int, kw_frac: float, vec_z, have_vec: bool) -> bool:
    """Relevance floor.

    vec_z is None for rows with no stored embedding (node-level candidates from
    sectionless files) — those pass on keyword coverage alone. With no query
    embedding at all (Ollama down), fall back to the keyword-only floor.
    """
    if kw_hits >= 2 and kw_frac >= 0.6:
        return True
    if not have_vec or vec_z is None:
        return kw_hits >= 2 or kw_frac >= 0.5
    if vec_z >= VEC_Z_STRONG:
        return True
    return kw_hits >= 2 and kw_frac >= KW_STRONG_FRAC and vec_z >= VEC_Z_SUPPORT


def smart_recall(store, query: str, k: int = 4) -> List[Dict]:
    """Return up to k precise, line-pointed hits for a natural-language query.

    Each hit: {text, source, score}. `source` is "engram:<file>:<start>-<end>".
    `store` is a MemoryStore. Falls back gracefully to [] on any error. Returning
    FEWER than k (including zero) is correct behavior when nothing clears the
    relevance floor — callers must not treat an empty list as an error.
    """
    kws = keywords(query)
    if not kws:
        return []

    qvec = None
    try:
        qvec = store._get_embedding(query)
    except Exception:
        qvec = None

    try:
        con = store.connect()
    except Exception:
        return []
    try:
        rows = con.execute(
            "SELECT mi.id, mi.file_name, ms.heading, ms.line_start, ms.line_end, "
            "       ms.content, mv.embedding "
            "FROM memory_sections ms "
            "JOIN memory_index mi ON ms.node_id = mi.id "
            "LEFT JOIN memory_vectors mv ON ms.rowid = mv.section_id "
            "WHERE mi.id NOT IN ('MEMORY', 'SCHEMA')"
        ).fetchall()
        # NODE-LEVEL candidates for every node (concept channel). Sectionless
        # files (no '## ' headings — ~45% of the store) have no memory_sections
        # rows at all and match on their full body; sectioned files contribute
        # their DESCRIPTION — the hand-written conceptual summary a paraphrased
        # query can match when no section's literal text does. Embeddings live in
        # memory_vectors under section_id = -(memory_index rowid) — the
        # negative-id convention written by ingest and backfill_node_vectors.py.
        node_rows = con.execute(
            "SELECT mi.id, mi.file_name, NULL AS heading, mi.line_start, "
            "       mi.line_end, "
            "       CASE WHEN EXISTS (SELECT 1 FROM memory_sections ms "
            "                         WHERE ms.node_id = mi.id) "
            "            THEN mi.description "
            "            ELSE COALESCE(mi.body, mi.description) END AS content, "
            "       mv.embedding "
            "FROM memory_index mi "
            "LEFT JOIN memory_vectors mv ON mv.section_id = -mi.rowid "
            "WHERE mi.id NOT IN ('MEMORY', 'SCHEMA')"
        ).fetchall()
        rows = list(rows) + list(node_rows)
    except Exception:
        con.close()
        return []

    nk = len(kws)
    all_sims: List[float] = []
    scored: List[tuple] = []
    try:
        for r in rows:
            content = (r["content"] or "").lower()
            kw_hits = sum(1 for kw in kws if kw in content)
            vec_sim = 0.0
            if qvec is not None and r["embedding"]:
                try:
                    vec_sim = max(0.0, store._cosine_similarity(
                        qvec, store._bytes_to_vector(r["embedding"])))
                    all_sims.append(vec_sim)
                except Exception:
                    vec_sim = 0.0
            if kw_hits == 0 and vec_sim == 0.0:
                continue
            scored.append((kw_hits, vec_sim, r))
    finally:
        con.close()

    # Vector signal is only meaningful relative to this query's own similarity
    # distribution (absolute cosines compress); compute mean/sd for z-scoring.
    have_vec = qvec is not None and len(all_sims) >= 8
    if have_vec:
        mean = sum(all_sims) / len(all_sims)
        var = sum((v - mean) ** 2 for v in all_sims) / len(all_sims)
        sd = var ** 0.5 or 1.0

    best_per_node: Dict[str, tuple] = {}
    for kw_hits, vec_sim, r in scored:
        embedded = r["embedding"] is not None
        vec_z = ((vec_sim - mean) / sd) if (have_vec and embedded) else None
        score = kw_hits / nk
        if vec_z is not None:
            score += max(0.0, vec_z) / 4.0
        prev = best_per_node.get(r["id"])
        if prev is None or score > prev[0]:
            best_per_node[r["id"]] = (score, kw_hits, vec_z, r)

    ranked = sorted(best_per_node.values(), key=lambda x: x[0], reverse=True)
    hits: List[Dict] = []
    top_score = 0.0
    for score, kw_hits, vec_z, r in ranked:
        if not _relevant(kw_hits, kw_hits / nk, vec_z, have_vec):
            continue
        if hits and score < top_score * TOP_GAP:
            break
        if not hits:
            top_score = score
        txt = " ".join((r["content"] or "").split())[:400]
        label = f"[{r['id']} > {r['heading']}]" if r["heading"] else f"[{r['id']}]"
        hits.append({
            "text": f"{label} {txt}",
            "source": f"engram:{r['file_name']}:{r['line_start']}-{r['line_end']}",
            "score": round(score, 3),
        })
        if len(hits) >= k:
            break
    return hits
