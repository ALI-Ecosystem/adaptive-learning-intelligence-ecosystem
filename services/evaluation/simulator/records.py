"""Writes a run as separate files. The answers never sit in the same file as the truth.

  answers.jsonl   one Learner Graph update body per line (ADD_EVIDENCE / ADD_EXPOSURE,
                  schema ali.learner-graph.update/v1), in time order. Unsigned: whoever
                  feeds them to the real pipeline signs them with its own key.
  items.json      the public item bank (options and their misconception map)
  truth.jsonl     one line per learner: population, parameters, true states, the twin,
                  checkpoint labels, every transition and a per-answer trace
  manifest.json   seed, sizes, and a SHA-256 of every file and of the simulator source
"""
import hashlib
import json
from pathlib import Path

from .items import BANK, ITEMS_PER_CONCEPT, public_bank
from .generator import POST_ITEMS


def _dump(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def source_digest() -> str:
    here = Path(__file__).parent
    h = hashlib.sha256()
    for p in sorted(here.glob("*.py")):
        h.update(p.name.encode() + b"\0" + p.read_bytes())
    return h.hexdigest()


def write_run(result: dict, out_dir) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "answers.jsonl": "".join(_dump(b) + "\n" for b in result["answers"]),
        "truth.jsonl": "".join(_dump(t) + "\n" for t in result["truth"]),
        "items.json": _dump(public_bank(result.get("bank", BANK))) + "\n",
    }
    digests = {}
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf-8")
        digests[name] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    manifest = {
        "generated_by": "SCRUM-93 learner simulator",
        "simulation_result": True,
        "seed": result["seed"], "n_per_population": result["n_per_population"],
        "post_items": result.get("post_items", POST_ITEMS),
        "items_per_concept": result.get("items_per_concept", ITEMS_PER_CONCEPT),
        "populations": result["populations"],
        "learners": len(result["truth"]), "records": len(result["answers"]),
        "evidence_records": sum(b["operation"] == "ADD_EVIDENCE" for b in result["answers"]),
        "sha256": digests, "simulator_source_sha256": source_digest(),
    }
    if "config" in result:                  # SCRUM-95 run: record the settings used
        manifest["config"] = result["config"]
        manifest["generated_by"] = "SCRUM-93 learner simulator (SCRUM-95 extensions)"
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                                       encoding="utf-8")
    return manifest
