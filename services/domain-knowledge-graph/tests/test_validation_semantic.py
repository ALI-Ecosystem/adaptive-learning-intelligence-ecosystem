"""Layer 2 (embedding signals) on a tiny hand-made vector space. No Neo4j, no model.
Run: .venv/bin/python -m pytest tests/test_validation_semantic.py -q

Directions (2-D unit vectors, angle in degrees):
    ALG 10 with children REC 20, SORT 0          <- the new concept sits at 18
    BIO 120 with children CELL 115, GENE 125     <- far away
"""
import math

import numpy as np

from validation import semantic
from validation.contract import Proposal, Result

ANGLE = {"ALG": 10, "REC": 20, "SORT": 0, "BIO": 120, "CELL": 115, "GENE": 125}
PARENT = {"REC": "ALG", "SORT": "ALG", "CELL": "BIO", "GENE": "BIO"}
NEW = 18


def v(deg):
    r = math.radians(deg)
    return np.array([math.cos(r), math.sin(r)], dtype=np.float32)


class FakeSemView:
    def embed_text(self, text):
        return v(NEW)

    def neighbours(self, vec, k):
        hits = [{"id": c, "name": c, "sim": float(vec @ v(a))} for c, a in ANGLE.items()]
        # like a vector index over a large graph: only genuinely close concepts come back
        return sorted((h for h in hits if h["sim"] > 0.5), key=lambda h: -h["sim"])[:k]

    def embeddings(self, ids):
        return {i: v(ANGLE[i]) for i in ids if i in ANGLE}

    def parents(self, cid):
        return [{"id": PARENT[cid], "primary": True}] if cid in PARENT else []

    def children(self, cid):
        return [c for c, p in PARENT.items() if p == cid]

    def level_of(self, cid):
        return 1

    def link_sims(self, child_level):
        return sorted(float(v(ANGLE[c]) @ v(ANGLE[p])) for c, p in PARENT.items())


def P(parent):
    return Proposal(id="P-new", name="Tail recursion", parent_ids=[parent])


def test_right_parent_passes():
    checks, reject, s = semantic.run(P("ALG"), FakeSemView())
    assert not reject and s["parent_rank"] == 1
    assert {c.check: c.result for c in checks}["family_fit"] is Result.PASS


def test_far_parent_rejected_when_all_signals_agree():
    checks, reject, s = semantic.run(P("BIO"), FakeSemView())
    r = {c.check: c.result for c in checks}
    assert reject and r["semantic_reject"] is Result.FAIL
    assert s["family_alternative"] > s["family_parent"]


def test_sibling_as_parent_only_warns():
    # REC is close in meaning (it is a sibling), so the vote still lists it: no reject
    checks, reject, _ = semantic.run(P("REC"), FakeSemView())
    assert not reject


def test_near_duplicate_warns():
    old = dict(ANGLE)
    ANGLE["TAILREC"] = NEW
    try:
        checks, _, _ = semantic.run(P("ALG"), FakeSemView())
        assert {c.check: c.result for c in checks}["near_duplicate"] is Result.WARN
    finally:
        ANGLE.clear(); ANGLE.update(old)
