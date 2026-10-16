"""Layer 5: turn the evidence of layers 1-4 into ACCEPT_PROVISIONAL / REJECT / NEEDS_REVIEW.

Kody's policy (2026-10-16): the teacher should see at most ~20% of proposals.
First version (choice C) sent a disagreement to the teacher only when Wikidata backed the
proposal; on the real SCRUM-89 agent stream that left the teacher 0% of proposals while
13 correct/reasonable placements were rejected. Since the budget was unused, every
disagreement with the blind validator now goes to the teacher with both candidates
(choice B): 9.4% of the agent stream, no correct placement lost.

Rules, first match wins:
  1  layer 1 FAIL                                         REJECT
  2  layer 1 REVIEW (new top-level field)                 NEEDS_REVIEW
  3  layer 2: all embedding signals agree it is wrong     REJECT
  4  layer 3: Wikidata knows the name as an existing      REJECT (duplicate_of)
     concept
  5  layer 4: the validator says it is the same concept   REJECT (duplicate_of)
     as an existing one
  6  layer 4 picked the proposed parent                   ACCEPT_PROVISIONAL
  7  layer 4 picked another parent, but Wikidata puts     NEEDS_REVIEW (sources conflict)
     the concept DIRECTLY under the proposed parent
  8  layer 4 picked another parent otherwise              NEEDS_REVIEW (teacher picks between
                                                          the agent's and the validator's parent)
  9  layer 4 gave no readable answer / did not run        NEEDS_REVIEW

The agent's own confidence is not a gate: on the synthetic test set it does not exist,
so it could not be calibrated. It is kept as evidence and orders the teacher's queue and
the audit sample (lowest confidence first).
"""
from .contract import Decision, Result

RULES = {
    1: "a deterministic rule is broken",
    2: "a new top-level field always needs a person",
    3: "all embedding signals agree the parent is wrong",
    4: "Wikidata knows this name as a concept that already exists",
    5: "the blind validator says this concept already exists",
    6: "the blind validator independently picked the same parent",
    7: "the validator and Wikidata disagree: a person decides",
    8: "the blind validator picked a different parent: the teacher chooses",
    9: "the blind validator gave no usable answer",
}


def decide(checks, signals: dict) -> tuple[Decision, int, dict]:
    """checks: all Check objects of layers 1-4. signals: {"semantic": .., "external": ..,
    "blind": ..} raw signals (may be missing for layers that did not run).
    Returns (decision, rule number, extra fields such as duplicate_of / suggested_parent)."""
    by = {(c.layer, c.check): c for c in checks}
    res = lambda layer, name: by[(layer, name)].result if (layer, name) in by else None

    if any(c.layer == "structural" and c.result is Result.FAIL for c in checks):
        return Decision.REJECT, 1, {}
    if any(c.layer == "structural" and c.result is Result.REVIEW for c in checks):
        return Decision.NEEDS_REVIEW, 2, {}
    if res("semantic", "semantic_reject") is Result.FAIL:
        return Decision.REJECT, 3, {}
    ext = signals.get("external") or {}
    if res("external", "wikidata_duplicate") is Result.FAIL:
        return Decision.REJECT, 4, {"duplicate_of": ext.get("duplicate_of")}

    b = signals.get("blind")
    if not b or b.get("picked_role") in (None, "invalid"):
        return Decision.NEEDS_REVIEW, 9, {}
    if b.get("same_as"):
        return Decision.REJECT, 5, {"duplicate_of": b["same_as"]}
    if b["picked_role"] == "proposed":
        return Decision.ACCEPT_PROVISIONAL, 6, {}
    if ext.get("support") == 1:
        return Decision.NEEDS_REVIEW, 7, {"validator_parent": b.get("picked_id")}
    return Decision.NEEDS_REVIEW, 8, {"validator_parent": b.get("picked_id"),
                                      "suggested_parent": b.get("picked_id"),
                                      "validator_role": b["picked_role"]}
