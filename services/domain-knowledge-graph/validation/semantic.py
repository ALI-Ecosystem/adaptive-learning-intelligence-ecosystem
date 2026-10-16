"""Layer 2 of the gate: embedding similarity, with the same static model as SCRUM-88
(English only, so the English name and the description are compared, never the
Hebrew original).

One similarity number cannot tell a parent from a sibling, so the layer compares:
  1. parent_rank      the proposed parent against the best parents the neighbourhood
                      votes for (the SCRUM-89 baseline vote)
  2. family_fit       the new concept against its future siblings, versus the
                      siblings it would have under the best alternative parent
  3. parent_sim_pct   its similarity to the parent, as a percentile of the real
                      CHILD_OF links at the same level (thresholds from data)
  4. near_duplicate   the most similar concept in the whole graph

Kody's decision (2026-10-16): this layer may reject on its own, but only when the
signals agree - the parent is not among the candidates AND it is far below the real
links AND the family fits worse than the alternative. Single signals are warnings.
The thresholds are calibrated on the SCRUM-89 judged placements (calibrate.py).
"""
from bisect import bisect_left
from collections import defaultdict
from typing import Protocol

import numpy as np

from .contract import Check, Proposal, Result

LAYER = "semantic"
K_NEIGHBOURS = 20
TOP_CANDIDATES = 10        # parent_rank beyond this counts as "not a candidate"
FAMILY_TOP = 3             # mean of the 3 most similar siblings
PCT_WARN = 10.0            # parent similarity below the 10th percentile of real links: warn
PCT_REJECT = 5.0           # ... below the 5th, as part of the reject rule
DUPLICATE_SIM = 0.90       # nearest concept this close: possible duplicate (calibrated later)
W_SELF, W_PRIMARY, W_OTHER = 1.0, 1.0, 0.5   # same weights as placement/baseline.py


class SemanticView(Protocol):
    def embed_text(self, text: str) -> np.ndarray: ...
    def neighbours(self, vec: np.ndarray, k: int) -> list[dict]:
        """[{id, name, sim}] most similar concepts, sim = cosine."""
    def embeddings(self, ids: list[str]) -> dict[str, np.ndarray]: ...
    def parents(self, cid: str) -> list[dict]:
        """[{id, primary}]"""
    def children(self, cid: str) -> list[str]: ...
    def level_of(self, cid: str) -> int: ...
    def link_sims(self, child_level: int) -> list[float]:
        """Sorted CHILD_OF.similarity of the real links whose child is at this level."""


def _check(name, result, message, **evidence):
    return Check(LAYER, name, result, message, evidence)


def _family(vec, kids, embs):
    sims = sorted((float(vec @ embs[k]) for k in kids if k in embs), reverse=True)
    return float(np.mean(sims[:FAMILY_TOP])) if sims else None


def candidate_parents(vec, hits, view):
    """The SCRUM-89 baseline vote: each neighbour votes for itself and its parents."""
    score = defaultdict(float)
    for h in hits:
        s = max(h["sim"], 0.0)
        score[h["id"]] += W_SELF * s
        for p in view.parents(h["id"]):
            score[p["id"]] += (W_PRIMARY if p["primary"] else W_OTHER) * s
    return sorted(score, key=score.get, reverse=True), score


def signals(p: Proposal, view: SemanticView) -> dict:
    """The raw numbers; run() turns them into checks. Kept apart for calibration."""
    from placement.embedder import concept_text
    vec = view.embed_text(concept_text(p.name, p.description))
    parent = p.parent_ids[0]
    hits = view.neighbours(vec, K_NEIGHBOURS)
    ranked, score = candidate_parents(vec, hits, view)
    rank = ranked.index(parent) + 1 if parent in ranked else None
    best_alt = next((c for c in ranked if c != parent), None)

    kids_parent = [k for k in view.children(parent) if k != p.id]
    kids_alt = view.children(best_alt) if best_alt else []
    embs = view.embeddings([parent] + kids_parent + kids_alt)
    parent_sim = float(vec @ embs[parent]) if parent in embs else None
    fam_parent, fam_alt = _family(vec, kids_parent, embs), _family(vec, kids_alt, embs)

    pct = None
    if parent_sim is not None:
        real = view.link_sims(view.level_of(parent) + 1)
        if real:
            pct = 100.0 * bisect_left(real, parent_sim) / len(real)

    top = hits[0] if hits else None
    return {
        "parent_rank": rank, "candidates": len(ranked),
        "best_alternative": best_alt,
        "alternatives": [c for c in ranked if c != parent][:5],
        "parent_vote": round(score.get(parent, 0.0), 3),
        "best_alternative_vote": round(score.get(best_alt, 0.0), 3) if best_alt else None,
        "parent_sim": None if parent_sim is None else round(parent_sim, 4),
        "parent_sim_pct": None if pct is None else round(pct, 1),
        "family_parent": None if fam_parent is None else round(fam_parent, 4),
        "family_alternative": None if fam_alt is None else round(fam_alt, 4),
        "nearest": top and {"id": top["id"], "name": top["name"], "sim": round(top["sim"], 4)},
        "nearest_list": [{"id": h["id"], "name": h["name"], "sim": round(h["sim"], 4)}
                         for h in hits[:3]],
    }


def run(p: Proposal, view: SemanticView) -> tuple[list[Check], bool, dict]:
    """Returns (checks, reject, signals). Only runs on a proposal with one parent."""
    s = signals(p, view)
    checks = []

    not_candidate = s["parent_rank"] is None or s["parent_rank"] > TOP_CANDIDATES
    checks.append(_check(
        "parent_rank", Result.WARN if not_candidate else Result.PASS,
        ("the neighbourhood does not point at this parent" if not_candidate else
         f"the parent is candidate #{s['parent_rank']} of the neighbourhood vote"),
        rank=s["parent_rank"], best_alternative=s["best_alternative"],
        parent_vote=s["parent_vote"], best_alternative_vote=s["best_alternative_vote"]))

    pct = s["parent_sim_pct"]
    low = pct is not None and pct < PCT_WARN
    checks.append(_check(
        "parent_similarity", Result.WARN if low else (Result.SKIP if pct is None else Result.PASS),
        (f"less similar to its parent than {100 - pct:.0f}% of the real links at this level"
         if low else "no data" if pct is None else
         f"similarity to the parent is at the {pct:.0f}th percentile of real links"),
        parent_sim=s["parent_sim"], percentile=pct))

    fp, fa = s["family_parent"], s["family_alternative"]
    worse = fp is not None and fa is not None and fa > fp
    if fp is None:
        fam = _check("family_fit", Result.SKIP, "the parent has no other children to compare with")
    else:
        fam = _check("family_fit", Result.WARN if worse else Result.PASS,
                     ("fits the siblings under the alternative parent better" if worse else
                      "fits its future siblings at least as well as any alternative family"),
                     family_parent=fp, family_alternative=fa,
                     alternative=s["best_alternative"])
    checks.append(fam)

    near = s["nearest"]
    if near and near["sim"] >= DUPLICATE_SIM:
        checks.append(_check("near_duplicate", Result.WARN,
                             f"very close to an existing concept: {near['name']}", nearest=near))
    else:
        checks.append(_check("near_duplicate", Result.PASS, "no near-duplicate", nearest=near))

    reject = not_candidate and pct is not None and pct < PCT_REJECT and worse
    if reject:
        checks.append(_check("semantic_reject", Result.FAIL,
                             "all embedding signals agree the parent is wrong"))
    return checks, reject, s
