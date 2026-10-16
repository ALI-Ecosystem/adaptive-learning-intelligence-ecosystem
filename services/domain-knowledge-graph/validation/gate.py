"""The validation gate: run layers 1-5 on one proposal.

Usage: python -m validation.gate P-ea10b6e6493b      (read-only: prints the result)

Layers run cheapest first and stop as soon as one decides, so a structural error never
costs a model call:
  1 structural (free)  2 semantic (free)  3 Wikidata (free, network)
  4 blind validator (one Opus call)  5 decision
"""
import argparse
import dataclasses
import json
import sys

from placement import config
from placement.graph import Graph, connect

from . import blind, decision, prereq, refd, semantic, structural, wikidata
from .contract import Decision, Proposal, Result, ValidationResult
from .neo4j_view import (Neo4jExternalView, Neo4jSemanticView, Neo4jView, ensure_indexes,
                         load_proposal)


def _public_id(graph: Graph, cid):
    """Internal concept id -> the public UUID other services use."""
    if not cid:
        return None
    rows = graph._read("MATCH (c:Concept {id: $cid}) RETURN c.concept_id AS u", cid=cid)
    return (rows[0]["u"] if rows and rows[0]["u"] else cid)


def validate(p: Proposal, graph: Graph, llm_client=None, wd_client=None,
             blind_override: dict | None = None, wp_client=None,
             order_override: dict | None = None) -> ValidationResult:
    """blind_override / order_override: stored layer-4 answers, used by the evaluation to
    avoid paying for the same Opus call twice. The concept is decided without its
    prerequisite links; each link is decided afterwards on its own (validation/prereq.py)."""
    full, p = p, dataclasses.replace(p, requires=[], enables=[])
    checks, early, duplicate_of = structural.run(p, Neo4jView(graph))
    signals = {}
    one_parent = len(p.parent_ids) == 1
    if early is None and one_parent:
        sem_view = Neo4jSemanticView(graph)
        sem_checks, reject, signals["semantic"] = semantic.run(p, sem_view)
        checks += sem_checks
        if not reject and wd_client is not None:
            ext_checks, _, signals["external"] = wikidata.run(p, Neo4jExternalView(graph), wd_client)
            checks += ext_checks
        if not reject and not any(c.result is Result.FAIL for c in checks):
            if blind_override is not None:
                signals["blind"] = blind_override
            elif llm_client is not None:
                b_checks, signals["blind"] = blind.run(p, graph, sem_view, llm_client,
                                                       signals["semantic"],
                                                       signals["semantic"]["nearest_list"])
                checks += b_checks

    dec, rule, extra = decision.decide(checks, signals)
    if early is not None and dec is not early:          # layer 1 decided; keep its word
        dec = early
    if not duplicate_of and extra.get("duplicate_of"):
        d = extra["duplicate_of"]                 # layer 3 gives a UUID, layer 4 an internal id
        duplicate_of = d if (signals.get("external") or {}).get("duplicate_of") == d \
            else _public_id(graph, d)

    reasons = [f"rule {rule}: {decision.RULES[rule]}"]
    reasons += [f"{c.layer}/{c.check}: {c.message}" for c in checks
                if c.result in (Result.FAIL, Result.REVIEW, Result.WARN)]
    review = None
    if dec is Decision.NEEDS_REVIEW:
        options = [p.parent_ids[0]] if p.parent_ids else []
        if extra.get("validator_parent"):
            options.append(extra["validator_parent"])
        review = {"role": "teacher", "rule": rule,
                  "question": (f"Where does '{p.name}' belong?" if options else
                               f"Is '{p.name}' a new top-level field of study?"),
                  "options": [{"id": o, "name": (graph.concept(o) or {}).get("name"),
                               "path": " > ".join(x["name"] for x in reversed(graph.path_to_root(o)))}
                              for o in options],
                  "priority": p.confidence if p.confidence is not None else 0.5}
    edges = []
    if full.requires or full.enables:
        ext_view = Neo4jExternalView(graph)
        sem = signals.get("semantic") or {}
        decoys = [n["id"] for n in sem.get("nearest_list", [])] + sem.get("alternatives", [])
        qid = (signals.get("external") or {}).get("resolved")
        title = wd_client.enwiki_title(qid) if (qid and wd_client is not None) else None
        edges = prereq.validate_edges(full, dec, graph, Neo4jView(graph), llm_client, wp_client,
                                      wd_client, title, decoys, order_override, ext_view)
    return ValidationResult(p.id, p.concept_id, dec, checks, reasons, duplicate_of, review,
                            rule=rule, suggested_parent=extra.get("suggested_parent"),
                            signals=signals, edges=edges,
                            audit_priority=prereq.audit_priority(edges))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("proposal_id")
    ap.add_argument("--no-llm", action="store_true", help="skip layer 4 (no API key needed)")
    ap.add_argument("--apply", action="store_true",
                    help="write the decision (and an audit record) to the graph")
    a = ap.parse_args()
    graph = Graph(connect())
    p = load_proposal(graph, a.proposal_id)
    if p is None:
        sys.exit(f"no proposal {a.proposal_id}")
    if not p.concept_id:
        sys.exit("the proposal has no concept_id yet - run ./scrum90.sh ids once")
    ensure_indexes(graph)
    wd = wikidata.WikidataClient(config.RUNS_DIR / "wikidata-cache.json")
    llm = None
    if not a.no_llm:
        from placement.agent import make_client
        llm = make_client()
    wp = refd.WikipediaClient(config.RUNS_DIR / "wikipedia-cache.json")
    res = validate(p, graph, llm, wd, wp_client=wp)
    wd.save(); wp.save()
    print(json.dumps(res.to_dict(), ensure_ascii=False, indent=2))
    print(f"\ndecision: {res.decision.value}   ({res.reasons[0]})")
    for e in res.edges:
        print(f"  link {e['from']} -> {e['to']}: {e['decision']}  ({e['reason']})")
    if a.apply:
        from . import store
        run_id = store.record_run(graph, res)
        print(f"\nrecorded as {run_id}; {store.apply(graph, p, res)}")
    else:
        print("\nread-only: nothing written (use --apply)")
    graph.driver.close()


if __name__ == "__main__":
    main()
