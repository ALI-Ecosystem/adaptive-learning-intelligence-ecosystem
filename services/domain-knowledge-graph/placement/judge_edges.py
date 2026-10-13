"""Second, independent judge for the SCRUM-88 100-link sample.

The sample was labelled OK / WRONG / DOUBT by Claude during SCRUM-88. This asks Opus,
without showing it those labels, to label the same links, then lists where the two
disagree (plus every DOUBT) for a person to settle.

Usage: python -m placement.judge_edges
Output: runs/edge-review/judge.csv, review.csv, summary.json
"""
import csv
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import RUNS_DIR, SERVICE_DIR
from .judge import JUDGE_MODEL

SAMPLE = SERVICE_DIR / "research" / "scrum88-edge-sample-100.csv"
OUT = RUNS_DIR / "edge-review"

PROMPT = """In an academic concept hierarchy, a CHILD_OF link says the child is a narrower \
concept of the parent: a kind of it, a part of it, or a sub-topic studied within it.

Child: {child} - {child_desc}
Parent: {parent} - {parent_desc}

Label the link:
- "OK": the child is clearly a kind, part or sub-topic of the parent.
- "WRONG": a different meaning or field, or the relation runs the other way.
- "DOUBT": related, but it is unclear whether it is a parent-child relation.

Reply with JSON only: {{"label": "...", "why": "<one short sentence>"}}"""


def ask(client, row):
    resp = client.messages.create(model=JUDGE_MODEL, max_tokens=1024, messages=[{
        "role": "user", "content": PROMPT.format(
            child=row["child"], child_desc=row["child_desc"] or "no definition",
            parent=row["parent"], parent_desc=row["parent_desc"] or "no definition")}])
    text = "".join(b.text for b in resp.content if b.type == "text")
    m = re.search(r"\{.*\}", text, re.S)
    out = json.loads(m.group(0)) if m else {}
    return {"label": str(out.get("label", "")).upper(), "why": out.get("why", "")}


def main():
    from .agent import make_client
    rows = list(csv.DictReader(SAMPLE.open()))
    client = make_client()
    print(f"judging {len(rows)} links with {JUDGE_MODEL}")
    with ThreadPoolExecutor(max_workers=4) as ex:
        verdicts = list(ex.map(lambda r: ask(client, r), rows))

    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "judge.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["n", "child", "parent", "label_scrum88", "label_opus", "why_opus"])
        for r, v in zip(rows, verdicts):
            w.writerow([r["n"], r["child"], r["parent"], r["label"], v["label"], v["why"]])

    review = [(r, v) for r, v in zip(rows, verdicts)
              if r["label"] != v["label"] or "DOUBT" in (r["label"], v["label"])]
    with (OUT / "review.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["n", "child", "child_desc", "parent", "parent_desc", "kody_label"])
        for r, v in review:
            w.writerow([r["n"], r["child"], r["child_desc"], r["parent"], r["parent_desc"], ""])

    agree = sum(r["label"] == v["label"] for r, v in zip(rows, verdicts))
    summary = {"judge_model": JUDGE_MODEL, "n": len(rows),
               "scrum88_labels": dict(Counter(r["label"] for r in rows)),
               "opus_labels": dict(Counter(v["label"] for v in verdicts)),
               "agree": agree,
               "both_wrong": sum(r["label"] == v["label"] == "WRONG" for r, v in zip(rows, verdicts)),
               "both_ok": sum(r["label"] == v["label"] == "OK" for r, v in zip(rows, verdicts)),
               "to_review": len(review)}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    print(f"results: {OUT}")


if __name__ == "__main__":
    main()
