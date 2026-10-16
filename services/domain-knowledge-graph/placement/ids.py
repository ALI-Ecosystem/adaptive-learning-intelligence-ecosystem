"""The public concept id: a UUID, the type Learner State keys its rows by
(learner-state architecture, App. C.2: concept_id UUID; §11.4: a concept_id is
immutable and never deleted).

Every node keeps two ids:
  id          the source key used inside this service: the OpenAlex id (C41008148) for
              a source concept, P-<hex> for a proposal. Never shown to other services.
  concept_id  the UUID other ALI services store and pass around.

Source concepts get a name-based UUID (v5) of their OpenAlex id, so rebuilding the graph
from the raw files always gives every concept the same concept_id. A proposed concept gets
a random UUID (v4) when it is proposed and keeps it if the gate promotes it, so the id
never changes over its life. NAMESPACE must never change: changing it would re-identify
every concept and orphan every learner's evidence.
"""
import uuid

NAMESPACE = uuid.UUID("6f1c2a0e-3b7d-5e4a-9c8f-a11d0c0ffee0")   # ALI Domain Knowledge Graph


def concept_uuid(source_id: str) -> str:
    """Stable UUID of a source concept, e.g. concept_uuid('C41008148')."""
    return str(uuid.uuid5(NAMESPACE, f"openalex:{source_id}"))


def new_concept_uuid() -> str:
    """UUID of a newly proposed concept."""
    return str(uuid.uuid4())
