"""Validation of proposed PREREQUISITE links, one decision per link (Kody, 2026-10-16:
a wrong link must not sink a right concept - the concept is decided on its own, and each
link is accepted, rejected or sent to the teacher by itself).

Every link starts or ends at the new concept N:
    requires  (r)-[:PREREQUISITE_OF]->(N)   r must be learned before N
    enables   (N)-[:PREREQUISITE_OF]->(e)   N must be learned before e

Evidence per link:
  1 structural   (deterministic) the other concept exists, no self-link, no cycle through N,
                 N is never a prerequisite of its own parent/ancestors, at most 5 links
  2 RefD         (Wikipedia links, no model) supports / reversed / no evidence - mainly a
                 DIRECTION check
  3 blind        one Opus call for all links of the proposal: the validator sees the concept
                 and a shuffled list of candidates (the proposed ones mixed with nearby
                 concepts as decoys) and marks which must come BEFORE it and which AFTER it,
                 without knowing what was proposed

Decision per link, first match wins:
  E1 structural fail                                   REJECT
  E2 the concept itself was rejected                   REJECT (no concept, no link)
  E3 the concept went to the teacher                   NEEDS_REVIEW (decided with it)
  E4 validator marked it, in the proposed direction:
        RefD says the direction is reversed            NEEDS_REVIEW
        otherwise                                      ACCEPT_PROVISIONAL
  E5 validator marked it in the OPPOSITE direction     REJECT (wrong direction)
  E6 validator did not mark it:
        RefD supports it strongly (>= 0.10)            NEEDS_REVIEW (sources disagree)
        otherwise                                      REJECT
  E7 no validator answer                               NEEDS_REVIEW
"""
import os
import random

from placement.embedder import concept_text

from . import refd as refd_mod
from .contract import Decision, Proposal
from .structural import MAX_PREREQ_EDGES

MODEL = os.environ.get("ALI_VALIDATOR_MODEL", "claude-opus-5-5")
N_DECOYS = 4

EDGE_RULES = {
    "E1": "a deterministic rule is broken",
    "E2": "the concept itself was rejected",
    "E3": "the concept goes to the teacher; the link is decided with it",
    "E4a": "the validator agrees but Wikipedia points the other way: a person decides",
    "E4": "the blind validator independently marked this prerequisite",
    "E5": "the validator says the direction is reversed",
    "E6a": "the validator did not mark it but Wikipedia supports it: a person decides",
    "E6": "neither the validator nor Wikipedia supports this link",
    "E7": "the blind validator gave no usable answer",
}

PROMPT = """You are checking LEARNING ORDER in a knowledge graph of academic concepts.

Concept: {name}
Definition: {description}

Candidate concepts:
{options}

For each candidate decide:
- "before": a learner must understand it BEFORE learning {name} (a direct prerequisite);
- "after": {name} is a direct prerequisite of it (learn {name} first);
- otherwise leave it out (related, or the same level, or no clear order).
Only direct, essential order counts - not mere relatedness. Empty lists are fine.

Answer with the submit_order tool."""


def edges_of(p: Proposal):
    return [("requires", r) for r in p.requires] + [("enables", e) for e in p.enables]


def structural_edge(p: Proposal, kind: str, other: str, view) -> str | None:
    """None when the link passes, else the reason it fails."""
    if other == p.id:
        return "a concept cannot be its own prerequisite"
    if view.get_concept(other) is None:
        return "the other concept is not in the graph"
    if len(edges_of(p)) > MAX_PREREQ_EDGES:
        return f"more than {MAX_PREREQ_EDGES} prerequisite links in one proposal"
    if other in p.requires and other in p.enables:
        return "the concept would both require and enable it (a 2-cycle)"
    if kind == "requires":
        if any(view.prereq_reachable(e, other) for e in p.enables):
            return "this link would close a prerequisite cycle through the new concept"
    else:
        if any(view.prereq_reachable(other, r) for r in p.requires):
            return "this link would close a prerequisite cycle through the new concept"
        if p.parent_ids:
            above = {p.parent_ids[0]} | view.ancestors(p.parent_ids[0])
            if other in above:
                return "the new concept cannot be a prerequisite of its own parent or ancestor"
    return None


def ask_order(client, p: Proposal, graph, proposed: list[str], decoys: list[str]):
    ids = list(dict.fromkeys(proposed + decoys))
    random.Random(p.id + "|order|" + "|".join(sorted(ids))).shuffle(ids)
    keys = [chr(ord("A") + i) for i in range(len(ids))]
    opts = dict(zip(keys, ids))

    def describe(cid):
        c = graph.concept(cid) or {"name": cid, "description": ""}
        return f"{c['name']} — {(c.get('description') or '')[:140]}"

    prompt = PROMPT.format(name=p.name, description=p.description or "(none given)",
                           options="\n".join(f"{k}. {describe(c)}" for k, c in opts.items()))
    tool = {"name": "submit_order", "description": "Submit the learning order.",
            "input_schema": {"type": "object", "properties": {
                "before": {"type": "array", "items": {"type": "string", "enum": keys}},
                "after": {"type": "array", "items": {"type": "string", "enum": keys}},
                "why": {"type": "string"}}, "required": ["before", "after"]}}
    ans, tokens = None, 0
    for _ in range(2):
        resp = client.messages.create(model=MODEL, max_tokens=800, tools=[tool],
                                      tool_choice={"type": "auto"},
                                      messages=[{"role": "user", "content": prompt}])
        tokens += resp.usage.input_tokens + resp.usage.output_tokens
        ans = next((b.input for b in resp.content if b.type == "tool_use"), None)
        if ans is not None:
            break
    if ans is None:
        return None
    return {"before": [opts[k] for k in ans.get("before", []) if k in opts],
            "after": [opts[k] for k in ans.get("after", []) if k in opts],
            "why": ans.get("why", ""), "options": opts, "decoys": decoys,
            "model": MODEL, "tokens": tokens}


def decide_edge(kind, other, structural_error, concept_decision, order, refd_value):
    if structural_error:
        return Decision.REJECT, "E1"
    if concept_decision is Decision.REJECT:
        return Decision.REJECT, "E2"
    if concept_decision is Decision.NEEDS_REVIEW:
        return Decision.NEEDS_REVIEW, "E3"
    if order is None:
        return Decision.NEEDS_REVIEW, "E7"
    same = "before" if kind == "requires" else "after"
    opposite = "after" if kind == "requires" else "before"
    # RefD is computed in learning order: positive = 'first' is a prerequisite of 'second'
    rv = refd_mod.verdict(refd_value)
    if other in order[same]:
        return (Decision.NEEDS_REVIEW, "E4a") if rv == "reversed" else (Decision.ACCEPT_PROVISIONAL, "E4")
    if other in order[opposite]:
        return Decision.REJECT, "E5"
    strong = refd_value is not None and refd_value >= refd_mod.RESCUE_THRESHOLD
    return (Decision.NEEDS_REVIEW, "E6a") if strong else (Decision.REJECT, "E6")


def validate_edges(p: Proposal, concept_decision, graph, view, client=None,
                   wp=None, wd=None, new_title: str | None = None, decoys=None,
                   order_override=None, ext_view=None) -> list[dict]:
    """One result per proposed link. `new_title`: Wikipedia title of the new concept
    (from layer 3's Wikidata match), needed for RefD. `decoys`: nearby concept ids that
    were not proposed, used to blind the validator."""
    links = edges_of(p)
    if not links:
        return []
    order = order_override
    if order is None and client is not None and concept_decision is Decision.ACCEPT_PROVISIONAL:
        proposed = [o for _, o in links]
        pool = [d for d in (decoys or []) if d not in proposed and d != p.id]
        order = ask_order(client, p, graph, proposed, pool[:N_DECOYS])
    out = []
    for kind, other in links:
        err = structural_edge(p, kind, other, view)
        rv, refd_info = None, None
        if not err and wp is not None and wd is not None and new_title and ext_view is not None:
            q = ext_view.wikidata_of(other) if ext_view is not None else None
            other_title = wd.enwiki_title(q) if q else None
            if other_title:
                first, second = (other_title, new_title) if kind == "requires" else (new_title, other_title)
                refd_info = refd_mod.refd(wp, first, second)
                rv = refd_info["refd"]
        dec, rule = decide_edge(kind, other, err, concept_decision, order, rv)
        out.append({"kind": kind, "other": other,
                    "from": other if kind == "requires" else p.id,
                    "to": p.id if kind == "requires" else other,
                    "decision": dec.value, "rule": rule, "reason": err or EDGE_RULES[rule],
                    "refd": refd_info,
                    "validator": None if order is None else
                    ("before" if other in order["before"] else
                     "after" if other in order["after"] else "neither")})
    return out


def audit_priority(edge_results: list[dict]) -> bool:
    """Kody's caveat: when most proposed links fail, the agent may have misread the
    concept itself - an accepted concept then goes to the front of the audit sample."""
    decided = [e for e in edge_results if e["rule"] not in ("E2", "E3")]
    return bool(decided) and sum(e["decision"] == "REJECT" for e in decided) > len(decided) / 2
