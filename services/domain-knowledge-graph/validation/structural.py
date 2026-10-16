"""Layer 1 of the gate: deterministic rules. No model, no randomness: the same proposal
on the same graph always gets the same checks.

A FAIL here rejects the proposal at once; later layers never see it. A REVIEW sends it
to the teacher whatever the other layers say. Everything else continues to layer 2.

The rules read the graph through the small GraphView interface below, so they can be
tested with an in-memory fake (tests/test_validation_structural.py) as well as run on
Neo4j (validation/neo4j_view.py).
"""
from typing import Protocol

from .contract import Check, Decision, Proposal, Result, base_name, normalize_name

LAYER = "structural"
MAX_LEVEL = 5             # OpenAlex levels run 0 (field) .. 5
MAX_PREREQ_EDGES = 5      # more than this from one conversation is not supported evidence


class GraphView(Protocol):
    def get_concept(self, cid: str) -> dict | None:
        """{id, name, level, trust: 'trusted'|'provisional', disambiguation_suspect} or None"""
    def ancestors(self, cid: str) -> set[str]:
        """Every concept above cid through CHILD_OF, any path."""
    def prereq_reachable(self, src: str, dst: str) -> bool:
        """True when src -[:PREREQUISITE_OF*]-> dst already exists."""
    def concepts_named_like(self, name: str) -> list[dict]:
        """Concepts whose name may match: [{id, concept_id, name}]. May over-return."""
    def proposals_named_like(self, name: str, exclude_id: str) -> list[dict]:
        """Other proposals: [{id, concept_id, name, status, parent_id}]. May over-return."""


def _check(name, result, message, **evidence):
    return Check(LAYER, name, result, message, evidence)


def check_parent(p: Proposal, g: GraphView) -> tuple[list[Check], dict | None]:
    if not p.parent_ids:
        return [_check("parent_count", Result.REVIEW,
                       "no parent: this would be a new top-level field, which always needs a person")], None
    if len(p.parent_ids) > 1:
        return [_check("parent_count", Result.FAIL,
                       "an addition has exactly one parent", parent_ids=p.parent_ids)], None
    checks = [_check("parent_count", Result.PASS, "one parent")]

    pid = p.parent_ids[0]
    parent = g.get_concept(pid)
    if parent is None:
        checks.append(_check("parent_exists", Result.FAIL,
                             "the parent is not a concept in the graph", parent_id=pid))
        return checks, None
    if parent.get("trust") == "provisional":
        checks.append(_check("parent_exists", Result.WARN,
                             "the parent is itself provisional (not yet audited)", parent_id=pid))
    else:
        checks.append(_check("parent_exists", Result.PASS, "the parent is a trusted concept",
                             parent_id=pid))

    level = (parent.get("level") or 0) + 1
    if level > MAX_LEVEL:
        checks.append(_check("depth", Result.WARN,
                             f"the new concept would be at level {level}, below the deepest "
                             f"level ({MAX_LEVEL}) of the source: may be too specific",
                             level=level))
    else:
        checks.append(_check("depth", Result.PASS, f"level {level}", level=level))

    if parent.get("disambiguation_suspect"):
        checks.append(_check("parent_ambiguous", Result.WARN,
                             "the parent looks like a disambiguation page", parent_id=pid))
    return checks, parent


def check_prerequisites(p: Proposal, g: GraphView) -> list[Check]:
    if not p.requires and not p.enables:
        return [_check("prereq_none", Result.PASS, "no prerequisite links proposed")]
    checks = []
    n = len(p.requires) + len(p.enables)
    if n > MAX_PREREQ_EDGES:
        checks.append(_check("prereq_count", Result.FAIL,
                             f"{n} prerequisite links from one proposal (max {MAX_PREREQ_EDGES})",
                             count=n))

    missing = [c for c in p.requires + p.enables if g.get_concept(c) is None]
    if missing:
        checks.append(_check("prereq_targets_exist", Result.FAIL,
                             "prerequisite links point at concepts that are not in the graph",
                             missing=missing))

    if p.id in p.requires or p.id in p.enables:
        checks.append(_check("prereq_self", Result.FAIL, "a concept cannot require itself"))

    both = sorted(set(p.requires) & set(p.enables))
    if both:
        checks.append(_check("prereq_cycle", Result.FAIL,
                             "the new concept both requires and enables the same concept "
                             "(a cycle of length 2)", concepts=both))
    for e in p.enables:
        for r in p.requires:
            if e != r and g.prereq_reachable(e, r):
                checks.append(_check("prereq_cycle", Result.FAIL,
                                     "this would close a prerequisite cycle: no learner could "
                                     "ever start it", cycle=[r, p.id, e, "...", r]))

    if p.parent_ids:
        above = {p.parent_ids[0]} | g.ancestors(p.parent_ids[0])
        bad = sorted(set(p.enables) & above)
        if bad:
            checks.append(_check("prereq_vs_hierarchy", Result.FAIL,
                                 "the new concept would be a prerequisite of its own parent or "
                                 "ancestor (the specific case before the general one)",
                                 concepts=bad))

    if not any(c.result is Result.FAIL for c in checks):
        checks.append(_check("prereq_rules", Result.PASS, f"{n} prerequisite links are consistent"))
    return checks


def check_duplicates(p: Proposal, g: GraphView) -> tuple[list[Check], str | None]:
    checks, duplicate_of = [], None
    names = {n for n in (p.name, p.name_original) if n}
    exact = {normalize_name(n) for n in names}
    bases = {base_name(n) for n in names}

    same, similar = [], []
    for n in names:
        for c in g.concepts_named_like(n):
            if c["id"] == p.id:                  # the proposal itself, once promoted
                continue
            if normalize_name(c["name"]) in exact:
                same.append(c)
            elif base_name(c["name"]) in bases:
                similar.append(c)
    if same:
        duplicate_of = same[0].get("concept_id") or same[0]["id"]
        checks.append(_check("duplicate_concept", Result.FAIL,
                             f"a concept with this name already exists: {same[0]['name']}",
                             duplicate_of=duplicate_of))
    elif similar:
        uniq = {c["id"]: c["name"] for c in similar}
        checks.append(_check("duplicate_concept", Result.WARN,
                             "same name with a different qualifier: may be the same concept or "
                             "a different meaning in another field, later layers decide",
                             candidates=uniq))
    else:
        checks.append(_check("duplicate_concept", Result.PASS, "no concept with this name"))

    parent = p.parent_ids[0] if p.parent_ids else None
    for n in names:
        for q in g.proposals_named_like(n, p.id):
            if normalize_name(q["name"]) not in exact:
                continue
            if q["status"] in ("proposed", "needs_review", "accepted"):
                checks.append(_check("duplicate_proposal", Result.FAIL,
                                     "the same concept is already proposed", proposal=q["id"],
                                     status=q["status"]))
                duplicate_of = duplicate_of or q.get("concept_id") or q["id"]
            elif q["status"] == "rejected" and q.get("parent_id") == parent:
                checks.append(_check("duplicate_proposal", Result.FAIL,
                                     "this exact placement was already rejected",
                                     rejected=q["id"]))
            elif q["status"] == "rejected":
                checks.append(_check("duplicate_proposal", Result.WARN,
                                     "the concept was rejected before under another parent",
                                     rejected=q["id"], rejected_parent=q.get("parent_id")))
            return checks, duplicate_of
    return checks, duplicate_of


def run(p: Proposal, g: GraphView) -> tuple[list[Check], Decision | None, str | None]:
    """All layer-1 checks. Returns (checks, decision or None to continue, duplicate_of),
    duplicate_of being the public concept_id of the concept that already exists."""
    parent_checks, _ = check_parent(p, g)
    dup_checks, duplicate_of = check_duplicates(p, g)
    checks = parent_checks + check_prerequisites(p, g) + dup_checks
    if any(c.result is Result.FAIL for c in checks):
        return checks, Decision.REJECT, duplicate_of
    if any(c.result is Result.REVIEW for c in checks):
        return checks, Decision.NEEDS_REVIEW, duplicate_of
    return checks, None, duplicate_of
