"""The concepts the simulation runs on: real Domain Knowledge Graph concepts.

The public concept_id is computed exactly as the Domain Knowledge Graph computes it
(services/domain-knowledge-graph/placement/ids.py), so the answer stream can later be fed
to the Learner Graph (SCRUM-92) without a lookup. The function is repeated here, not
imported, so this service does not depend on the DKG service's code; a test checks that
both give the same ids.

The misconceptions are SYNTHETIC: written for the simulation, one short statement each.
The DKG holds no misconceptions, and none of the project papers lists them for these
concepts.
"""
import uuid
from dataclasses import dataclass

DKG_NAMESPACE = uuid.UUID("6f1c2a0e-3b7d-5e4a-9c8f-a11d0c0ffee0")   # must equal placement/ids.py


def concept_uuid(source_id: str) -> str:
    return str(uuid.uuid5(DKG_NAMESPACE, f"openalex:{source_id}"))


@dataclass(frozen=True)
class Misconception:
    misconception_id: str
    statement: str


@dataclass(frozen=True)
class Concept:
    source_id: str          # OpenAlex id inside the DKG
    name: str
    short: str              # used in item ids only
    misconceptions: tuple

    @property
    def concept_id(self) -> str:
        return concept_uuid(self.source_id)


CONCEPTS = (
    Concept("C168773036", "Recursion (computer science)", "REC", (
        Misconception("M-REC-1", "a recursive function does not need a base case"),
        Misconception("M-REC-2", "the recursive call runs only once"),
        Misconception("M-REC-3", "a result returns to the first caller without a return statement"),
        Misconception("M-REC-4", "the most recent call finishes last"),
    )),
    Concept("C146101286", "Linked list", "LL", (
        Misconception("M-LL-1", "reaching the i-th element takes constant time"),
        Misconception("M-LL-2", "deleting a node needs no pointer update"),
        Misconception("M-LL-3", "the head is the last node inserted at the tail"),
        Misconception("M-LL-4", "the nodes are stored next to each other in memory"),
    )),
    Concept("C197855036", "Binary tree", "BT", (
        Misconception("M-BT-1", "every binary tree is a binary search tree"),
        Misconception("M-BT-2", "a node may have three children"),
        Misconception("M-BT-3", "the height equals the number of nodes"),
        Misconception("M-BT-4", "a leaf has exactly one child"),
    )),
)

BY_SOURCE_ID = {c.source_id: c for c in CONCEPTS}
