# Diagnosis Engine

Self-contained Python project for ALI Diagnosis. The package name remains
`ali_diagnosis`; domain, application, infrastructure, prompts, and tests retain
their existing structure.

Architecture constraints and runtime documentation remain in the repository's
[Diagnosis architecture folder](../../docs/architecture/diagnosis/README.md).
See [runtime installation and configuration](../../docs/architecture/diagnosis/agentic-orchestrator.md#installation-and-execution),
[information gateway](../../docs/information_gateway.md), and
[capability registry](../../docs/capability_registry.md).

## Install and test

Requires Python 3.11+. From the repository root, on Windows:

```powershell
cd services/diagnosis
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e '.[dev,openai,anthropic,deepseek,google_genai,groq]'
$env:ALI_DIAGNOSIS_RUN_LIVE = '0'
.venv/Scripts/python.exe -m pytest -q -m 'not live'
```

On macOS/Linux, use `.venv/bin/python` instead of `.venv/Scripts/python.exe`.
Provider extras are optional for ordinary use; the command above includes all
adapters exercised by the full non-live compatibility tests.

For discovery only, run the same pytest command with `--collect-only`.
The local `pyproject.toml` discovers `tests/`, adds `src/` to pytest's import path,
and includes `prompts/v1/*.md` in the package. These are Diagnosis-only tests;
running bare pytest at the monorepo root is not a combined validation workflow.

## Execute

The module entry point remains:

```powershell
.venv/Scripts/python.exe -m ali_diagnosis.infrastructure.synthetic_cli --help
```

Executing a scenario requires explicit provider credentials, model configuration,
and run limits, and calls a real model. Follow the runtime documentation linked
above. Live tests remain explicitly opt-in.

The relocation changes filesystem paths only. Existing editable installations
must be reinstalled from this directory; do not move or commit virtual environments,
bytecode, build output, or generated package metadata.
