"""Place the main concept of one conversation and add it to the graph as a proposal.

Usage:
  python -m placement.place --text "Student: what is tail recursion? ..."
  python -m placement.place --file conversation.txt
  python -m placement.place --text "..." --dry-run      (decide and explain, write nothing)
"""
import argparse
import sys
from pathlib import Path

from . import config
from .agent import make_client, run_agent
from .graph import Graph, connect
from .traces import save_trace


def main():
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--text")
    src.add_argument("--file", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--model", default=config.CLAUDE_MODEL)
    a = ap.parse_args()
    conversation = a.text if a.text is not None else a.file.read_text()

    graph = Graph(connect())
    res = run_agent(conversation, graph, make_client(), model=a.model)
    trace_path = save_trace(res)
    if res.decision is None:
        print(f"FAILED: {res.error}  (trace: {trace_path})")
        sys.exit(1)
    d = res.decision
    print(f"concept:    {d['concept_name']}  ({d.get('concept_name_original') or '-'})")
    print(f"definition: {d['description']}")

    if d["decision"] == "already_exists":
        c = graph.concept(d["existing_id"])
        print(f"ALREADY IN GRAPH: {c['name']} [{c['id']}] - nothing added")
    else:
        pending = graph.pending_proposals(d["concept_name"])
        path = " > ".join(p["name"] for p in reversed(graph.path_to_root(d["parent_id"])))
        print(f"parent:     {path}")
        print(f"confidence: {d['confidence']}")
        print(f"why:        {d['reasoning']}")
        if pending:
            print(f"ALREADY PROPOSED as {pending[0]['id']} under {pending[0]['parent_name']} "
                  f"- nothing added")
        elif a.dry_run:
            print("dry run - nothing written")
        else:
            pid = graph.write_proposal(
                name=d["concept_name"], name_original=d.get("concept_name_original") or "",
                description=d["description"], parent_id=d["parent_id"],
                confidence=d["confidence"], reasoning=d["reasoning"],
                method="agent", model=a.model, trace_id=res.trace_id)
            print(f"ADDED as proposal {pid} (status: proposed)")
    print(f"steps={res.steps} tokens={res.input_tokens}+{res.output_tokens} "
          f"time={res.seconds:.0f}s trace={trace_path}")
    graph.driver.close()


if __name__ == "__main__":
    main()
