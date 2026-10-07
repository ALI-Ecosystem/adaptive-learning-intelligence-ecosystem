# Diagnosis information gateway

SCRUM-8 adds the first information access boundary. The package currently has
diagnosis contracts, not an executable diagnosis algorithm. Consumers can now
request diagnostic information through this gateway:

```text
Diagnosis -> InformationGateway -> configured diagnostic information sources
```

Application setup supplies a mapping of source names to implementations of
`DiagnosticInformationSource`. The gateway copies that collection. For now, only
the temporary example source is configured and no external source is connected:

```python
from ali_diagnosis.application.information_access.gateway import InformationGateway
from ali_diagnosis.infrastructure.example_information_provider import (
    ExampleInformationProvider,
)

gateway = InformationGateway({"example": ExampleInformationProvider()})
```

Diagnosis receives that gateway and uses only the source-independent contracts:

```python
from ali_diagnosis.domain import DiagnosisRunRequest
import json

information = gateway.get_information(
    DiagnosisRunRequest(
        diagnosis_run_id="run-123",
        learner_id="learner-123",
        evidence_id="evidence-123",
    )
)
print(json.dumps(information, indent=2))
```

The gateway forwards the existing `DiagnosisRunRequest` unchanged to each source, including
`diagnosis_run_id`, `learner_id`, `evidence_id`, and `schema_version` (default `0.1`).
The request has no `subject_ref`; subject resolution belongs to the later
evidence/taxonomy flow using the triggering `evidence_id`.

The gateway calls all configured sources sequentially in mapping order and
assembles a dictionary keyed by their configured names. Each source's dictionary
is preserved independently, so overlapping fields do not overwrite each other.
The gateway only retrieves and assembles information; it performs no diagnosis.

The temporary example contains a fixed message and mock metadata in plain
dictionaries. It defines no learner or future source schema and contains no
retrieved facts. No domain model exists for this temporary metadata; diagnostic
provenance remains represented by
`DiagnosticArtifact`, its `producer`, and source references.

With the example source configured above, the gateway currently returns:

```json
{
  "example": {
    "message": "Temporary example diagnostic information.",
    "provenance": {
      "source_name": "temporary_example_information",
      "is_temporary_example": true,
      "real_source_connected": false,
      "notice": "Temporary example information only. No real information source is connected. The content is synthetic and is not diagnostic evidence."
    }
  }
}
```

This response exercises the access boundary; it must not be treated as real
diagnostic evidence. No Learner State, Domain Graph, history, profile, database,
persistence, or OpenAI Agent SDK is integrated.

## Replacing the example later

Implement `DiagnosticInformationSource.get_information(request)` in an
infrastructure adapter when a real source is available. That adapter owns source
access; its data schema will be decided when needed. Add it under a distinct name
in the mapping passed to `InformationGateway(sources)` during application setup. Diagnosis keeps the
same request and gateway call and does not import that adapter or its clients.

The source protocol is exported from
`ali_diagnosis.application.information_access`. Concrete source
implementations remain under `ali_diagnosis.infrastructure`.

Source errors propagate to the caller; assembly stops on the first error, with
no partial result or automatic fallback to example data. An empty source mapping
returns an empty dictionary. Source names are assigned by application setup and
identify entries in the assembled result; they define no source-specific schema.

These collection, naming, and error-handling choices are the minimal assumptions
for this implementation; selective retrieval and partial-failure handling are
not implemented.

Run the focused checks with `python -m pytest` in an environment containing the
project dependencies and the `dev` extra.
