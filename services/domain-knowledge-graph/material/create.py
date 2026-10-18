"""CREATE MATERIAL GRAPH - the operation, and its CLI.

This component does not decide WHETHER ALI should build a material graph; it receives a
request and performs it:

    create_material_graph(material, graph, ...) -> {material_graph_id, ...}

    1 ingest    material -> units                              (material/ingest.py)
    2 extract   units -> concepts with roles and evidence      (material/extract.py)
    3 link      concepts -> canonical global concepts          (material/link.py)
    4 missing   no match -> SCRUM-89 agent -> SCRUM-90 gate    (material/missing.py)
    5 scope     anchors -> scoped region of the global graph   (material/scope.py)
    6 store     overlay nodes, nothing copied                  (material/store.py)

Usage:
  python -m material.create create --source materials/schneider-enlp-2018 \
         --titles material/samples/schneider-enlp-2018.tsv
  python -m material.create create --source materials/hebrew-ds-wikibooks.json
  python -m material.create create ... --no-llm      (lexical extraction, top-hit linking,
                                                      heuristic parent check: free, offline)
  python -m material.create show MATERIAL_GRAPH_ID
  python -m material.create export MATERIAL_GRAPH_ID > graph.json
  python -m material.create list
"""
import argparse
import csv
import json
import re
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from placement import config
from placement.graph import Graph, connect

from . import extract as ex
from . import ingest, link, scope, store
from .llm import JsonCache, Usage

CACHE = config.RUNS_DIR / "scrum91-llm-cache.json"


def _config_key(a) -> str:
    return f"extract={a.extract};link={a.link};judge={a.judge};missing={not a.no_missing};model={a.model}"


def create_material_graph(material, graph, *, extract_method="llm", link_method="llm",
                          judge_name="claude", missing=True, client=None,
                          model=config.CLAUDE_MODEL, dry_run=False, new_version=False,
                          config_key="", run_dir: Path | None = None, progress=print) -> dict:
    t0 = time.time()
    if not dry_run and not new_version:
        prev = store.find_existing(graph, material.content_hash(), config_key)
        if prev:
            progress(f"already built: {prev['id']} (version {prev['version']}); "
                     f"use --new-version to rebuild")
            return {"material_graph_id": prev["id"], "reused": True}
    cache = JsonCache(CACHE)
    usage = Usage()

    progress(f"[1/5] extract ({extract_method}) from {len(material.units)} units")
    lex = ex.Lexicon.from_graph(graph) if extract_method == "lexical" else None
    mentions, topics, u1 = ex.extract(material, extract_method, client, lex, model, cache, progress)
    cache.save()
    concepts = link.merge_mentions(mentions)
    progress(f"      {len(mentions)} mentions -> {len(concepts)} distinct concepts")

    progress(f"[2/5] link ({link_method})")
    if link_method == "llm":
        link.link_llm(concepts, graph, material, client, model, usage, cache, progress)
    else:
        link.link_baseline(concepts, graph)
    cache.save()
    linked = sum(1 for c in concepts if c.concept_id)
    progress(f"      linked {linked}/{len(concepts)}")

    missing_log = []
    if missing and client is not None and not dry_run:
        progress(f"[3/5] missing concepts -> SCRUM-89 agent -> SCRUM-90 gate")
        from validation import refd, wikidata
        from .missing import resolve_missing
        wd = wikidata.WikidataClient(config.RUNS_DIR / "wikidata-cache.json")
        wp = refd.WikipediaClient(config.RUNS_DIR / "wikipedia-cache.json")
        missing_log = resolve_missing(concepts, graph, material, client, wd, wp, model, progress)
        wd.save(); wp.save()
    else:
        progress("[3/5] missing concepts: skipped" + (" (dry run)" if dry_run else ""))

    progress(f"[4/5] scope (parent check: {judge_name})")
    anchors = {}
    for mc in concepts:
        if mc.concept_id and graph.concept_exists(mc.concept_id):
            a = anchors.get(mc.concept_id)
            if a is None or (a["role"] == "prerequisite" and mc.role == "taught"):
                anchors[mc.concept_id] = {"role": mc.role, "importance": mc.importance,
                                          "first_taught_seq": mc.first_taught_seq,
                                          "material_name": mc.name}
    pending = [{"proposal_id": mc.proposal_id, "name": mc.name, "role": mc.role,
                "parent_id": next((r.get("parent") for r in missing_log
                                   if r.get("proposal") == mc.proposal_id), None)}
               for mc in concepts if mc.concept_id is None and mc.proposal_id
               and mc.gate_decision in ("NEEDS_REVIEW", "PROPOSED")]
    judge = (scope.ClaudeParentJudge(client, model, cache, usage) if judge_name == "claude"
             else scope.HeuristicParentJudge())
    course = f"Course: {material.title[:150]} (units: " + "; ".join(
        u.title[:50] for u in material.units[:30]) + ")"
    sg = scope.build_scope(anchors, scope.ScopeView(graph), judge, course, pending)
    cache.save()
    progress(f"      {sg.stats}")

    run_info = {"extract": extract_method, "link": link_method, "judge": judge_name,
                "model": model, "seconds": round(time.time() - t0),
                "usage_extract": u1.as_dict(), "usage_link_judge": usage.as_dict(),
                "mentions": len(mentions), "concepts": len(concepts), "linked": linked,
                "missing": len(missing_log)}
    out = {"stats": sg.stats, "run": run_info}
    if run_dir:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "mentions.json").write_text(json.dumps(ex.mentions_to_dicts(mentions), ensure_ascii=False, indent=1))
        (run_dir / "unit_topics.json").write_text(json.dumps(topics, ensure_ascii=False, indent=1))
        (run_dir / "concepts.json").write_text(json.dumps([asdict(c) | {"role": c.role}
                                                           for c in concepts], ensure_ascii=False, indent=1))
        (run_dir / "missing.json").write_text(json.dumps(missing_log, ensure_ascii=False, indent=1))
        (run_dir / "scope.json").write_text(json.dumps(asdict(sg), ensure_ascii=False, indent=1, default=str))
        (run_dir / "run.json").write_text(json.dumps(run_info, ensure_ascii=False, indent=1))
        out["run_dir"] = str(run_dir)
    progress("[5/5] store" + (": skipped (dry run)" if dry_run else ""))
    if not dry_run:
        out.update(store.save(graph, material, concepts, sg, config_key=config_key, run_info=run_info))
    return out


def load_titles(path: Path | None) -> dict:
    if not path:
        return {}
    with open(path) as f:
        return {r["file"]: r["title"] for r in csv.DictReader(f, delimiter="\t")}


def print_tree(data: dict):
    m = data["material_graph"]
    print(f"{m['title']}  (id {m['material_graph_id']}, version {m['version']}, {m['status']})")
    nodes = {n["id"]: n for n in data["nodes"]}
    kids = {}
    for n in data["nodes"]:
        kids.setdefault(n["parent_id"] if n["parent_id"] in nodes else None, []).append(n["id"])
    mark = {"taught": "", "prerequisite": "  (prior knowledge)", "context": "  ·"}

    def show(cid, d):
        n = nodes[cid]
        units = ",".join(str(u["seq"] + 1) for u in sorted(n["units"], key=lambda u: u["seq"])
                         if u["role"] == "taught")
        print("  " * d + f"{n['name']}{mark.get(n['role'], '')}" + (f"  [units {units}]" if units else ""))
        for k in sorted(kids.get(cid, []), key=lambda k: nodes[k]["name"]):
            show(k, d + 1)
    for r in sorted(kids.get(None, []), key=lambda k: (nodes[k]["role"] == "prerequisite", nodes[k]["name"])):
        show(r, 0)
    for p in data["pending"]:
        print(f"PENDING {p['name']} ({p['status']}, proposal {p['proposal_id']})")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--source", required=True)
    c.add_argument("--title")
    c.add_argument("--titles", type=Path, help="TSV with columns file, title")
    c.add_argument("--extract", choices=["llm", "lexical"], default="llm")
    c.add_argument("--link", choices=["llm", "baseline"], default="llm")
    c.add_argument("--judge", choices=["claude", "heuristic"], default="claude")
    c.add_argument("--no-missing", action="store_true", help="skip the SCRUM-89/90 pipeline")
    c.add_argument("--no-llm", action="store_true", help="lexical + baseline + heuristic, free")
    c.add_argument("--dry-run", action="store_true", help="build and report, write nothing")
    c.add_argument("--new-version", action="store_true")
    c.add_argument("--model", default=config.CLAUDE_MODEL)
    for name in ("show", "export"):
        sub.add_parser(name).add_argument("material_graph_id")
    sub.add_parser("list")
    a = ap.parse_args()

    graph = Graph(connect())
    if a.cmd == "create":
        if a.no_llm:
            a.extract, a.link, a.judge, a.no_missing = "lexical", "baseline", "heuristic", True
        kw = {"titles": load_titles(a.titles)} if Path(a.source).is_dir() else {}
        if a.title and Path(a.source).is_dir():
            kw["title"] = a.title
        material = ingest.load(a.source, **kw)
        if a.title:
            material.title = a.title
        need_llm = "llm" in (a.extract, a.link) or a.judge == "claude" or not a.no_missing
        client = None
        if need_llm:
            from placement.agent import make_client
            client = make_client()
        slug = re.sub(r"[^a-z0-9]+", "-", Path(a.source).stem.lower()).strip("-")[:40] or "material"
        run_dir = config.RUNS_DIR / f"scrum91-{slug}-{datetime.now():%Y%m%d-%H%M%S}"
        print(f"material: {material.title} | {material.language} | {len(material.units)} units | "
              f"{sum(u.words for u in material.units)} words")
        out = create_material_graph(material, graph, extract_method=a.extract, link_method=a.link,
                                    judge_name=a.judge, missing=not a.no_missing, client=client,
                                    model=a.model, dry_run=a.dry_run, new_version=a.new_version,
                                    config_key=_config_key(a), run_dir=run_dir)
        print(json.dumps({k: v for k, v in out.items() if k != "stats"}, indent=1))
        if out.get("material_graph_id"):
            print_tree(store.load(graph, out["material_graph_id"]))
    elif a.cmd == "show":
        data = store.load(graph, a.material_graph_id)
        print_tree(data) if data else print("not found")
    elif a.cmd == "export":
        print(json.dumps(store.load(graph, a.material_graph_id), ensure_ascii=False, indent=1, default=str))
    else:
        for r in store.list_graphs(graph):
            print(f"{r['id']}  v{r['version']}  {r['status']:10s}  {r['concepts']:4d} concepts  {r['title']}")
    graph.driver.close()


if __name__ == "__main__":
    main()
