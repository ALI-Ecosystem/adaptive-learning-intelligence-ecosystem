"""No-LLM baseline: nearest-neighbour parent voting.

Find the concepts most similar to the new one; each neighbour votes for itself
(it might be the parent) and for its parents (the new concept might be its sibling).
Votes are weighted by similarity. Deterministic, fast and free - the reference the
agent has to beat.
"""
from collections import defaultdict

from .embedder import concept_text
from .graph import Graph

K = 20
W_SELF = 1.0      # neighbour itself as the parent
W_PRIMARY = 1.0   # neighbour's primary parent
W_OTHER = 0.5     # neighbour's other parents


def place_baseline(graph: Graph, name: str, description: str | None):
    hits = graph.vector_search(concept_text(name, description), K)
    score, why = defaultdict(float), defaultdict(list)
    for h in hits:
        s = max(h["score"], 0.0)
        score[h["id"]] += W_SELF * s
        why[h["id"]].append(f"similar itself ({s:.2f})")
        for p in graph.parents_of(h["id"]):
            score[p["id"]] += (W_PRIMARY if p["primary"] else W_OTHER) * s
            why[p["id"]].append(f"parent of {h['name']} ({s:.2f})")
    if not score:
        return None
    ranked = sorted(score, key=score.get, reverse=True)
    best = ranked[0]
    return {"parent_id": best, "score": round(score[best], 3),
            "alternatives": ranked[1:4], "reasoning": "; ".join(why[best][:5])}
