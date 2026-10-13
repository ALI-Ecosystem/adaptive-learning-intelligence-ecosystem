"""Blind LLM judge for the hide-and-replace results.

Exact match against the source parent is too strict: the source hierarchy is noisy
(~30% wrong links in SCRUM-88) and shallow at the top, so a better, more specific parent
counts as a miss. The judge rates every proposed parent - the source's own included -
without knowing which method proposed it. A person then checks the judge on a subset
they know (human-set.json) and the agreement rate is reported next to the judge's numbers.

Usage:
  python -m placement.judge --run runs/eval-A --llm-only-run runs/eval-B
  (resumable: rerun the same command to continue)
"""
import argparse
import hashlib
import json
import os
import random
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .graph import Graph, connect

JUDGE_MODEL = os.environ.get("ALI_JUDGE_MODEL", "claude-opus-5-5")
HUMAN_FIELDS = ("Computer science", "Mathematics")
HUMAN_N = 20

PARENT_PROMPT = """You are checking a knowledge graph of academic concepts. A concept must be \
attached under a parent: a broader concept of which it is a kind, part or sub-topic.

Concept: {name}
Definition: {description}

Candidate parents (each shown with its own path up to a top-level field):
{candidates}

Rate EACH candidate independently:
- "correct": the concept is clearly a kind/part/sub-topic of this parent and it is a good place for it.
- "reasonable": right direction but too broad, slightly too narrow, or a loose fit; acceptable.
- "wrong": different meaning, wrong field, or only loosely associated.

Reply with JSON only: {{"A": {{"verdict": "...", "why": "<one short sentence>"}}, ...}}"""

DUP_PROMPT = """Are these two entries in an academic knowledge graph the same concept (synonym, \
spelling variant or abbreviation), or different concepts?

Entry 1: {a_name} - {a_desc}
Entry 2: {b_name} - {b_desc} (path: {b_path})

Answer "same", "close" (closely related but not the same thing, e.g. one is a sub-type of \
the other) or "different". Reply with JSON only: {{"verdict": "...", "why": "<one short sentence>"}}"""


def _json(text: str):
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else None


def _ask(client, prompt: str):
    resp = client.messages.create(model=JUDGE_MODEL, max_tokens=2048,
                                  messages=[{"role": "user", "content": prompt}])
    text = "".join(b.text for b in resp.content if b.type == "text")
    return _json(text), resp.usage.input_tokens + resp.usage.output_tokens


def build_items(graph: Graph, rows, llm_rows):
    """One judge item per test concept: unique candidate parents in a fixed shuffled order."""
    def path(cid):
        return " > ".join(p["name"] for p in reversed(graph.path_to_root(cid)))

    items = []
    for r in rows:
        g = graph.with_hidden({r["id"]})
        a = r.get("agent", {})
        if a.get("decision") == "already_exists":
            ex = g.concept(a["said_exists"])
            items.append({"id": r["id"], "kind": "duplicate", "concept": r["name"],
                          "description": r["description"] or "", "existing_id": ex["id"],
                          "existing": ex["name"], "existing_description": ex["description"] or "",
                          "existing_path": path(ex["id"]), "field": r["field"]})
        cands = defaultdict(list)
        cands[r["parent_id"]].append("source")
        for m, pred in (("agent", a.get("pred")), ("baseline", r.get("baseline", {}).get("pred")),
                        ("llm_only", llm_rows.get(r["id"], {}).get("pred"))):
            if pred:
                cands[pred].append(m)
        order = sorted(cands)
        random.Random(hashlib.sha1(r["id"].encode()).hexdigest()).shuffle(order)
        items.append({"id": r["id"], "kind": "parent", "concept": r["name"],
                      "description": r["description"] or "", "field": r["field"],
                      "level": r["level"],
                      "candidates": [{"cid": c, "name": g.concept(c)["name"],
                                      "description": g.concept(c)["description"] or "",
                                      "path": path(c), "methods": cands[c]} for c in order]})
    return items


def judge_item(client, it):
    if it["kind"] == "duplicate":
        out, tok = _ask(client, DUP_PROMPT.format(
            a_name=it["concept"], a_desc=it["description"] or "-", b_name=it["existing"],
            b_desc=it["existing_description"] or "-", b_path=it["existing_path"]))
        return {"key": f"dup:{it['id']}", "verdict": (out or {}).get("verdict"),
                "why": (out or {}).get("why"), "tokens": tok}
    letters = "ABCDEFG"
    lines = [f"{letters[i]}. {c['name']} - {c['description'] or 'no definition'}\n"
             f"   path: {c['path']}" for i, c in enumerate(it["candidates"])]
    out, tok = _ask(client, PARENT_PROMPT.format(name=it["concept"],
                                                 description=it["description"] or "-",
                                                 candidates="\n".join(lines)))
    out = out or {}
    return {"key": f"parent:{it['id']}", "tokens": tok,
            "verdicts": {c["cid"]: (out.get(letters[i]) or {}).get("verdict")
                         for i, c in enumerate(it["candidates"])},
            "why": {c["cid"]: (out.get(letters[i]) or {}).get("why")
                    for i, c in enumerate(it["candidates"])}}


def summarize(items, judged):
    s = {"judge_model": JUDGE_MODEL, "methods": {}, "duplicates": {}}
    per = defaultdict(Counter)
    for it in items:
        if it["kind"] != "parent":
            continue
        j = judged.get(f"parent:{it['id']}")
        if not j:
            continue
        for c in it["candidates"]:
            for m in c["methods"]:
                per[m][j["verdicts"].get(c["cid"]) or "unparsed"] += 1
        for m in ("agent", "baseline", "llm_only"):
            if not any(m in c["methods"] for c in it["candidates"]):
                per[m]["no_answer"] += 1
    for m, c in per.items():
        n = sum(c.values())
        s["methods"][m] = {"n": n, **dict(c),
                           "correct_rate": round(c["correct"] / n, 3),
                           "correct_or_reasonable_rate": round((c["correct"] + c["reasonable"]) / n, 3)}
    d = Counter(judged[f"dup:{it['id']}"]["verdict"] for it in items
                if it["kind"] == "duplicate" and f"dup:{it['id']}" in judged)
    s["duplicates"] = dict(d)
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, required=True, help="eval run with agent + baseline")
    ap.add_argument("--llm-only-run", type=Path)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    rows = [json.loads(l) for l in (a.run / "results.jsonl").read_text().splitlines()]
    llm_rows = {}
    if a.llm_only_run:
        for l in (a.llm_only_run / "results.jsonl").read_text().splitlines():
            r = json.loads(l)
            llm_rows[r["id"]] = r["llm_only"]

    graph = Graph(connect())
    items = build_items(graph, rows, llm_rows)
    (a.run / "judge-items.json").write_text(json.dumps(items, ensure_ascii=False, indent=1))

    human = [it for it in items if it["kind"] == "parent" and it["field"] in HUMAN_FIELDS]
    human.sort(key=lambda it: (HUMAN_FIELDS.index(it["field"]), it["id"]))
    (a.run / "human-set.json").write_text(json.dumps(
        [{k: v for k, v in it.items() if k != "candidates"} |
         {"candidates": [{k: v for k, v in c.items() if k != "methods"} for c in it["candidates"]]}
         for it in human[:HUMAN_N]], ensure_ascii=False, indent=1))

    out_path = a.run / "judge.jsonl"
    judged = {}
    if out_path.exists():
        for l in out_path.read_text().splitlines():
            j = json.loads(l)
            judged[j["key"]] = j
    from .agent import make_client
    client = make_client()
    todo = [it for it in items if f"{it['kind'] if it['kind'] == 'parent' else 'dup'}:{it['id']}"
            not in judged]
    print(f"judging {len(todo)} items with {JUDGE_MODEL} ({len(judged)} already done)")
    with ThreadPoolExecutor(max_workers=a.workers) as ex, open(out_path, "a") as f:
        futs = {ex.submit(judge_item, client, it): it for it in todo}
        for n, fut in enumerate(as_completed(futs), 1):
            it = futs[fut]
            try:
                j = fut.result()
            except Exception as e:
                print(f"  ! {it['concept']}: {e}")
                continue
            judged[j["key"]] = j
            f.write(json.dumps(j, ensure_ascii=False) + "\n"); f.flush()
            print(f"  [{n}/{len(todo)}] {it['kind']}: {it['concept']}")
    summary = summarize(items, judged)
    (a.run / "judge-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print(json.dumps(summary, indent=1))
    graph.driver.close()


if __name__ == "__main__":
    main()
