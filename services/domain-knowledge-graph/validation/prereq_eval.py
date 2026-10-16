"""Test the prerequisite-link validation on LectureBank (Li et al., AAAI 2019): 208 NLP /
ML / AI topics, each with a Wikipedia link, and human labels for topic pairs - 921 pairs
"A is a prerequisite of B" and many pairs labelled "not a prerequisite".

Topics are mapped to our graph through Wikipedia -> Wikidata id -> Concept.wikidata.
For every mapped topic N we pretend N is new and test three kinds of proposed links:
    true       A -> N   labelled prerequisite                      expected: accept
    negative   A -> N   labelled NOT a prerequisite (hard negative) expected: not accept
    reversed   X -> N   where the label says N -> X (wrong direction) expected: not accept

Signals: RefD on the Wikipedia articles (no model) and the blind order question (one
Opus call per topic N, all its candidates shuffled together - the negatives double as
decoys). Each link is then decided by validation/prereq.decide_edge with the concept
itself taken as accepted, so the numbers measure the link layer alone.

Usage: python -m validation.prereq_eval            (network; ~1 Opus call per topic, resumable)
Writes runs/scrum90-prereq/{topics.json, links.jsonl, summary.json}
"""
import csv
import io
import json
import random
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

from placement import config
from placement.graph import Graph, connect

from . import prereq, refd, wikidata
from .contract import Decision, Proposal

OUT = config.RUNS_DIR / "scrum90-prereq"
RAW = "https://raw.githubusercontent.com/Yale-LILY/LectureBank/master/LB-Paper/"
MAX_PER_TOPIC = 8
SEED = 90


def _fetch(name):
    path = OUT / name
    if not path.exists():
        req = urllib.request.Request(RAW + name, headers={"User-Agent": wikidata.USER_AGENT})
        path.write_bytes(urllib.request.urlopen(req, timeout=60).read())
    return path.read_text()


def map_topics(graph, wp) -> dict:
    """{lb_id: {name, title, qid, concept_id}} for topics that map to one of our concepts."""
    path = OUT / "topics.json"
    if path.exists():
        return json.loads(path.read_text())
    out = {}
    for row in csv.reader(io.StringIO(_fetch("208topics.csv"))):
        if len(row) < 3:
            continue
        tid, name, url = row[0], ",".join(row[1:-1]).strip(), row[-1].strip()   # names may hold commas
        if not url.startswith("http") or "#" in url:       # missing, or only a section
            continue
        title = urllib.parse.unquote(url.rsplit("/wiki/", 1)[-1]).replace("_", " ")
        d = wp._get(action="query", titles=title, prop="pageprops", ppprop="wikibase_item",
                    redirects=1)
        page = next(iter(d.get("query", {}).get("pages", {}).values()), {})
        qid = page.get("pageprops", {}).get("wikibase_item")
        if not qid:
            continue
        rows = graph._read("""MATCH (c:Concept {wikidata: $q}) RETURN c.id AS id
                              ORDER BY c.works_count DESC LIMIT 1""", q=qid)
        if rows:
            out[tid] = {"name": name, "title": page.get("title", title), "qid": qid,
                        "concept": rows[0]["id"]}
    path.write_text(json.dumps(out, indent=1))
    return out


def build_links(topics) -> dict:
    """{new_topic: [(candidate_topic, kind)]} with kind true / negative / reversed."""
    rows = list(csv.reader(io.StringIO(_fetch("prerequisite_annotation.csv"))))
    pos = {(a, b) for a, b, y in rows if y == "1" and a in topics and b in topics}
    neg = [(a, b) for a, b, y in rows if y == "0" and a in topics and b in topics
           and topics[a]["concept"] != topics[b]["concept"]]
    rng = random.Random(SEED)
    per = defaultdict(list)
    for a, b in pos:
        per[b].append((a, "true"))
        per[a].append((b, "reversed"))       # proposing b as a prerequisite of a: wrong way
    negs = defaultdict(list)
    for a, b in neg:
        negs[b].append(a)
    for n in list(per):
        k = sum(1 for _, kind in per[n] if kind == "true")
        per[n] += [(a, "negative") for a in rng.sample(negs[n], min(len(negs[n]), max(k, 1)))]
        rng.shuffle(per[n])
        seen, uniq = {topics[n]["concept"]}, []    # one link per graph concept
        for a, kind in per[n]:
            if topics[a]["concept"] not in seen:
                seen.add(topics[a]["concept"]); uniq.append((a, kind))
        per[n] = uniq[:MAX_PER_TOPIC]
    return per


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    graph = Graph(connect())
    wp = refd.WikipediaClient(config.RUNS_DIR / "wikipedia-cache.json")
    topics = map_topics(graph, wp)
    per = build_links(topics)
    print(f"{len(topics)} of 208 LectureBank topics map to the graph; "
          f"{len(per)} topics with test links, {sum(len(v) for v in per.values())} links")

    path = OUT / "links.jsonl"
    done = {json.loads(l)["topic"] for l in open(path)} if path.exists() else set()
    from placement.agent import make_client
    client = make_client()
    with open(path, "a") as f:
        for i, (n, cands) in enumerate(per.items(), 1):
            if n in done:
                continue
            t = topics[n]
            c = graph.concept(t["concept"])
            ids = [topics[a]["concept"] for a, _ in cands]
            p = Proposal(id=t["concept"], name=c["name"], description=c.get("description") or "",
                         parent_ids=[], requires=ids)
            order = prereq.ask_order(client, p, graph, ids, [])
            for (a, kind), cid in zip(cands, ids):
                r = refd.refd(wp, topics[a]["title"], t["title"])
                dec, rule = prereq.decide_edge("requires", cid, None, Decision.ACCEPT_PROVISIONAL,
                                               order, r["refd"])
                f.write(json.dumps({"topic": n, "new": t["name"], "candidate": topics[a]["name"],
                                    "kind": kind, "refd": r["refd"],
                                    "refd_truncated": r.get("truncated"),
                                    "validator": None if order is None else
                                    ("before" if cid in order["before"] else
                                     "after" if cid in order["after"] else "neither"),
                                    "decision": dec.value, "rule": rule},
                                   ensure_ascii=False) + "\n")
            f.flush()
            wp.save()
            print(f"\r{i}/{len(per)}", end="", flush=True)
    wp.save()
    print()

    rows = [json.loads(l) for l in open(path)]
    for r in rows:                      # re-decide with the current rules: reruns are free
        v = r["validator"]
        order = None if v is None else {"before": ["X"] if v == "before" else [],
                                        "after": ["X"] if v == "after" else []}
        dec, r["rule"] = prereq.decide_edge("requires", "X", None, Decision.ACCEPT_PROVISIONAL,
                                            order, r["refd"])
        r["decision"] = dec.value
    by = defaultdict(Counter)
    for r in rows:
        by[r["kind"]][r["decision"]] += 1
    refd_by = defaultdict(Counter)
    for r in rows:
        refd_by[r["kind"]][refd.verdict(r["refd"])] += 1
    val_by = defaultdict(Counter)
    for r in rows:
        val_by[r["kind"]][r["validator"]] += 1
    n = len(rows)
    bad = [r for r in rows if r["kind"] != "true"]
    summary = {
        "topics_mapped": len(topics), "links": n,
        "decision_by_kind": {k: dict(v) for k, v in by.items()},
        "refd_by_kind": {k: dict(v) for k, v in refd_by.items()},
        "validator_by_kind": {k: dict(v) for k, v in val_by.items()},
        "teacher_rate": round(sum(r["decision"] == "NEEDS_REVIEW" for r in rows) / n, 3),
        "true_accepted_rate": round(by["true"]["ACCEPT_PROVISIONAL"] / max(sum(by["true"].values()), 1), 3),
        "false_accept_rate": round(sum(r["decision"] == "ACCEPT_PROVISIONAL" for r in bad) / max(len(bad), 1), 3),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    graph.driver.close()


if __name__ == "__main__":
    main()
