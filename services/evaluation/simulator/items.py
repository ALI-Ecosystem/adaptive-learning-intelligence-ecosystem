"""The multiple-choice item bank.

Every item has four options: one correct and three distractors, each distractor mapped to
one misconception of the item's concept (the Eedi structure used by Li et al. 2025). A
concept has four misconceptions, so each item carries three of them and an item does not
always "discriminate" a given misconception - as in a real bank.

Items have NO difficulty parameter. The simulator's answer model is a discrete state
(knows / does not know) plus guess, slip and misconception pull; an item's difficulty plays
no part. This is one of the ways the generator differs from the evaluator, whose model
uses an item difficulty b (evaluation architecture section 3.4).

The bank is fixed (it does not depend on the run seed): it is public content the system
knows, like the option -> misconception map Learner State reads from the item bank.

SCRUM-96: a separate TRANSFER bank per concept - problems of a new kind on the same concept
(item ids REC-T01 ...), built the same way. Its items are marked kind TRANSFER_PROBLEM; the
ordinary bank is unchanged and its public form does not get the new field.
"""
from dataclasses import dataclass

from .concepts import CONCEPTS
from .draws import Draws

ITEMS_PER_CONCEPT = 20
TRANSFER_PER_CONCEPT = 12
STANDARD, TRANSFER = "STANDARD", "TRANSFER_PROBLEM"
OPTIONS = ("A", "B", "C", "D")
_BANK_DRAWS = Draws(seed=0, learner_index=-1)       # fixed: the bank is not run-dependent


@dataclass(frozen=True)
class Item:
    item_id: str
    concept_source_id: str
    correct_option: str
    distractors: tuple              # ((option, misconception_id), ...) - three entries
    kind: str = STANDARD            # SCRUM-96: TRANSFER_PROBLEM for the transfer bank

    def option_for(self, misconception_id: str) -> str | None:
        for opt, mid in self.distractors:
            if mid == misconception_id:
                return opt
        return None

    def to_public(self) -> dict:
        out = {"item_id": self.item_id, "concept_source_id": self.concept_source_id,
               "options": [{"option": o,
                            "correct": o == self.correct_option,
                            "misconception_id": dict(self.distractors).get(o)}
                           for o in OPTIONS]}
        if self.kind != STANDARD:
            out["activity_type"] = self.kind
        return out


def build_bank(items_per_concept: int = ITEMS_PER_CONCEPT, kind: str = STANDARD) -> dict:
    """{concept_source_id: [Item, ...]}. Item k is the same item in a bank of any size
    (its options are keyed by its id), so a larger bank only adds items."""
    bank = {}
    tag = "T" if kind == TRANSFER else ""
    for c in CONCEPTS:
        items = []
        mids = [m.misconception_id for m in c.misconceptions]
        for i in range(1, items_per_concept + 1):
            item_id = f"{c.short}-{tag}{i:02d}"
            correct = _BANK_DRAWS.choice(OPTIONS, "correct", item_id)
            carried = _BANK_DRAWS.shuffled(mids, "carried", item_id)[:3]
            wrong = [o for o in OPTIONS if o != correct]
            items.append(Item(item_id, c.source_id, correct, tuple(zip(wrong, carried)), kind))
        bank[c.source_id] = items
    return bank


BANK = build_bank()
TRANSFER_BANK = build_bank(TRANSFER_PER_CONCEPT, TRANSFER)


def public_bank(bank: dict) -> list:
    return [it.to_public() for items in bank.values() for it in items]
