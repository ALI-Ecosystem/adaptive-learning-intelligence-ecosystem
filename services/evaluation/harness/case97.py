"""SCRUM-97 case analysis log.

    python -m harness.case97 --out runs/scrum97

1. builds every case of the SCRUM-94, 95 and 96 runs (the runs the reports used), with one
   label per dimension, an overall label and, for every WRONG dimension, a layer and the
   rule it points to (caselog/spec.py, pre-registered);
2. selects cases by the fixed rule (spec.SELECTION_RULE) and lists the empty cells;
3. rebuilds the selected cases with their full chain (every answer, counted or excluded
   with its reason, next to the truth), renders them, and runs the counterfactual replays;
4. checks every rendered case against the raw run files (no hand-written text);
5. writes the summary tables and the blind-review package.

Writes: cases.txt, cases.jsonl, all_labels.jsonl, summary.json, summary.md, check.json,
review/{review_cases.txt, answer_sheet.csv, coding_guide.md} and review_key/key.json (keep
the key away from the reviewer), manifest.json.
"""
import argparse
import hashlib
import json
import multiprocessing
from pathlib import Path

from caselog import build94, build95, build96
from caselog import log as G
from caselog import spec as S
from caselog.common import spec_sha

BUILD = {"R94": build94.build, "R95": build95.build, "R96": build96.build}


def _build(job):
    run, root, details = job
    return [G.finish_case(c) for c in BUILD[run](root, details)]


def light(c):
    return {"case_id": c["case_id"], "population": c["population"],
            "overall": c["overall"]["label"],
            "dims": [[d["name"], d["output"], d["label"], d["layer"]] for d in c["dimensions"]]}


def code_digest(root: Path) -> str:
    h = hashlib.sha256()
    for d in ("caselog", "outcome", "verdict", "gap", "harness", "simulator"):
        for p in sorted((root / d).glob("*.py")):
            h.update(f"{d}/{p.name}".encode() + b"\0" + p.read_bytes())
    return h.hexdigest()


def sha(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write_md(summ, empty, groups, checks, cf, out):
    L = ["# SCRUM-97 case analysis log - summary (generated, do not edit)", "",
         "Simulated learners only. Labels: CORRECT / WRONG / UNCERTAIN per dimension; "
         "NOT_OBSERVED = the dimension read no answer (coverage), NOT_SCORABLE = the truth "
         "changed inside a pooled window.", "",
         f"Selection rule: {S.SELECTION_RULE}", ""]
    for run, R in summ.items():
        L += [f"## {run} - {S.RUNS[run]['mission']} ({R['cases']} cases)", "",
              "### Overall label per population", "",
              "| population | CORRECT | WRONG | UNCERTAIN |", "|---|---|---|---|"]
        for p, x in R["overall"].items():
            L.append(f"| {p} | {x.get('CORRECT', 0)} | {x.get('WRONG', 0)} | {x.get('UNCERTAIN', 0)} |")
        L += ["", "### Labels per population and dimension family", "",
              "| population | family | CORRECT | WRONG | UNCERTAIN | NOT_OBSERVED | NOT_SCORABLE | "
              "WRONG by layer |", "|---|---|---|---|---|---|---|---|"]
        for cell, x in R["labels"].items():
            p, f = cell.split("|")
            lay = R["layers"].get(cell, {})
            L.append(f"| {p} | {f} | {x.get('CORRECT', 0)} | {x.get('WRONG', 0)} | "
                     f"{x.get('UNCERTAIN', 0)} | {x.get('NOT_OBSERVED', 0)} | "
                     f"{x.get('NOT_SCORABLE', 0)} | "
                     + ", ".join(f"{k} {v}" for k, v in lay.items()) + " |")
        L += ["", "### System outputs per population and family", "",
              "| population | family | outputs |", "|---|---|---|"]
        for cell, x in R["outputs"].items():
            p, f = cell.split("|")
            L.append(f"| {p} | {f} | " + ", ".join(f"{k} {v}" for k, v in x.items()) + " |")
        L += ["", "### Wrong kinds (all cases) and their layer", "",
              "| family | output / truth | layer | n |", "|---|---|---|---|"]
        for f, ks in R["wrong_kinds"].items():
            for k, n in sorted(ks.items(), key=lambda kv: -kv[1]):
                kind, layer = k.split(" | ")
                L.append(f"| {f} | {kind} | {layer} | {n} |")
        L += ["", "### Uncertain dimensions by reason", "", "| family: reason | n |", "|---|---|"]
        for k, n in R["uncertain_reasons"].items():
            L.append(f"| {k} | {n} |")
        L.append("")
    L += ["## Layers in total (every wrong dimension of every case)", "",
          "| run | family | layer | n |", "|---|---|---|---|"]
    for k, n in G.layer_totals(summ).items():
        r, f, l = k.split("|")
        L.append(f"| {r} | {f} | {l} | {n} |")
    seen = {k.split("|")[2] for k in G.layer_totals(summ)}
    for layer in S.LAYERS:
        if layer not in seen:
            L.append(f"| all | all | {layer} | 0 (empty - see the report) |")
    L += ["", f"## Empty cells ({len(empty)})", "", "| run | population | family | output | why |",
          "|---|---|---|---|---|"]
    for e in empty:
        L.append(f"| {e['run']} | {e['population']} | {e['family']} | {e['output']} | {e['why']} |")
    L += ["", "## Counterfactual replays on the selected wrong dimensions", "",
          "A replay changes one thing and runs the same measure again. It never sets a label; it "
          "tests the attribution: an INPUT_DATA attribution is supported when filling the "
          "missing field makes the output CORRECT; an INTERACTION 'state changed in the window' "
          "attribution when removing the delayed answers that fell before t_R does. "
          "For the window replay, '-> UNCERTAIN' means removing the answers left too little "
          "evidence; for the input replay, the filled-in ratings left the measure undecided.", "",
          "| attributed layer | replay | -> CORRECT | -> UNCERTAIN | still WRONG | n |",
          "|---|---|---|---|---|---|"]
    for k, v in cf.items():
        a, rep = k.split("|")
        L.append(f"| {a} | {rep} | {v['to_correct']} | {v['to_uncertain']} | {v['still_wrong']} | {v['n']} |")
    L += ["", f"## Consistency check: {checks['cases']} rendered cases, {checks['problems']} problems", ""]
    (out / "summary.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def counterfactual_table(detailed):
    t = {}
    for c in detailed:
        for d in c["dimensions"]:
            cf = d.get("counterfactual")
            if d["label"] != S.WRONG or not cf:
                continue
            (rep, v), = cf.items()
            key = f"{d['layer']}|{rep}" if isinstance(v, dict) else f"{d['layer']}|{rep}: not available"
            x = t.setdefault(key, {"to_correct": 0, "to_uncertain": 0, "still_wrong": 0, "n": 0})
            x["n"] += 1
            if isinstance(v, dict):
                x[{S.CORRECT: "to_correct", S.WRONG: "still_wrong"}.get(v["label"], "to_uncertain")] += 1
    return dict(sorted(t.items()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", default="runs/scrum97")
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    root, out = Path(a.root), Path(a.out)
    (out / "review").mkdir(parents=True, exist_ok=True)
    (out / "review_key").mkdir(parents=True, exist_ok=True)
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(a.workers) as pool:
        built = pool.map(_build, [(r, str(root), None) for r in S.RUNS], chunksize=1)
    cases = dict(zip(S.RUNS, built))
    for run, cs in cases.items():
        print(f"{run}: {len(cs)} cases")
    sel, empty, groups = G.select(cases)
    by_run = {r: {i for i in sel if i.startswith(r)} for r in S.RUNS}
    with ctx.Pool(a.workers) as pool:
        det = pool.map(_build, [(r, str(root), by_run[r]) for r in S.RUNS], chunksize=1)
    light_by_id = {c["case_id"]: c for cs in cases.values() for c in cs}
    detailed = []
    for cs in det:
        for c in cs:
            ref = light_by_id[c["case_id"]]
            strip = lambda ds: [{k: v for k, v in d.items() if k != "counterfactual"} for d in ds]
            assert strip(c["dimensions"]) == strip(ref["dimensions"]), c["case_id"]
            c["selected_by"] = sel[c["case_id"]]
            detailed.append(c)
    detailed.sort(key=lambda c: (list(S.RUNS).index(c["run"]), c["population"], c["case_id"]))
    print(f"selected {len(detailed)} cases; {len(empty)} empty cells")

    texts, problems = [], {}
    raws = {r: G.raw_index(root, r, {c["learner_id"] for c in detailed if c["run"] == r})
            for r in S.RUNS}
    for c in detailed:
        t = G.render(c)
        texts.append(t)
        bad = G.check_case(c, raws[c["run"]], t)
        if bad:
            problems[c["case_id"]] = bad
    checks = {"cases": len(detailed), "problems": len(problems), "detail": problems}
    (out / "cases.txt").write_text("\n".join(texts), encoding="utf-8")
    with open(out / "cases.jsonl", "w", encoding="utf-8") as f:
        for c in detailed:
            f.write(json.dumps(c, sort_keys=True) + "\n")
    with open(out / "all_labels.jsonl", "w", encoding="utf-8") as f:
        for run in S.RUNS:
            for c in cases[run]:
                f.write(json.dumps(light(c), sort_keys=True) + "\n")
    summ = G.summary(cases)
    cf = counterfactual_table(detailed)
    (out / "summary.json").write_text(json.dumps(
        {"summary": summ, "layer_totals": G.layer_totals(summ), "empty_cells": empty,
         "wrong_group_sizes": groups, "selected": {c["case_id"]: c["selected_by"] for c in detailed},
         "counterfactual": cf}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (out / "check.json").write_text(json.dumps(checks, indent=1, sort_keys=True) + "\n",
                                    encoding="utf-8")
    write_md(summ, empty, groups, checks, cf, out)
    by_id = {c["case_id"]: c for c in detailed}
    items = G.review_items(detailed)
    pkg = G.review_package(items, by_id)
    (out / "review" / "review_cases.txt").write_text(pkg["review_cases.txt"], encoding="utf-8")
    (out / "review" / "answer_sheet.csv").write_text(pkg["answer_sheet.csv"], encoding="utf-8")
    (out / "review_key" / "key.json").write_text(pkg["key.json"], encoding="utf-8")
    guide = Path(__file__).resolve().parents[1] / "caselog" / "coding_guide.md"
    (out / "review" / "coding_guide.md").write_text(guide.read_text(encoding="utf-8"), encoding="utf-8")
    labels_sha = hashlib.sha256(json.dumps(
        [light(c) for run in S.RUNS for c in cases[run]], sort_keys=True).encode()).hexdigest()
    manifest = {"policy": S.POLICY, "format": S.FORMAT, "spec_sha256": spec_sha(),
                "code_sha256": code_digest(Path(__file__).resolve().parents[1]),
                "labels_sha256": labels_sha,
                "inputs": {r: dict({f: sha(root / S.RUNS[r]["run"] / f)
                                    for f in ("answers.jsonl", "truth.jsonl", "items.json")},
                                   **{"calibration.json": sha(root / S.RUNS[r]["calib"] / "calibration.json")},
                                   **{k: sha(root / S.RUNS[r][k]) for k in ("norm", "clean_norm")
                                      if k in S.RUNS[r]})
                           for r in S.RUNS},
                "selected_cases": len(detailed), "empty_cells": len(empty),
                "review_items": len(items), "consistency_problems": len(problems)}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n",
                                       encoding="utf-8")
    print(f"consistency problems: {len(problems)}; labels sha256 {labels_sha[:16]}... -> {out}")
    if problems:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
