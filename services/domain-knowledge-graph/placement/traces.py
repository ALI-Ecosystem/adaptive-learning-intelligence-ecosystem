"""Traces hold the learner's conversation, so they stay on the local disk (runs/, git-ignored)."""
import json
from datetime import datetime, timezone

from .config import RUNS_DIR


def save_trace(result, extra: dict | None = None, folder=None) -> str:
    folder = folder or RUNS_DIR / "traces"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{result.trace_id}.json"
    path.write_text(json.dumps({
        "trace_id": result.trace_id, "saved_at": datetime.now(timezone.utc).isoformat(),
        "decision": result.decision, "error": result.error, "steps": result.steps,
        "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
        "seconds": round(result.seconds, 1), **(extra or {}), "trace": result.trace,
    }, ensure_ascii=False, indent=1, default=str))
    return str(path)
