"""Layer 4 of the gate: a second, blind AI validator (Kody's choice B, 2026-10-16).

The validator never sees which parent was proposed. It gets the concept and a shuffled
multiple-choice list, so agreeing with the proposal is a real independent pick, not a nod:

    the proposed parent
    the 2 best alternatives from layer 2's neighbourhood vote
    the proposed parent's own parent        (would mean: the proposal is too specific)
    a child of the proposed parent          (would mean: the proposal is too broad)
    "none of these"

In the same call it is shown the concepts nearest in meaning (layer 2) and asked whether
the new concept is the same as one of them - this settles layer 2's near-duplicate warnings.

Model: Opus by default (ALI_VALIDATOR_MODEL); the placement agent is Sonnet, so the two are
at least different models. They are still one family - a known limit, see the report.
"""
import json
import os
import random
import re

from placement.embedder import concept_text

from .contract import Check, Proposal, Result

LAYER = "independent"
MODEL = os.environ.get("ALI_VALIDATOR_MODEL", "claude-opus-5-5")
N_ALTERNATIVES = 2
N_NEAREST = 3

PROMPT = """You are checking where a new concept belongs in a knowledge graph of academic \
concepts. A concept goes under a parent: the broader concept of which it is a kind, a part \
or a sub-topic. The best parent is the most specific one that still contains the concept.

New concept: {name}{original}
Definition: {description}

Candidate parents (each with its path up to a top-level field):
{options}
{none_key}. None of these is a good parent.

Existing concepts closest in meaning:
{nearest}

Answer two questions:
1. Which candidate is the best parent? Pick exactly one key.
2. Is the new concept the SAME concept as one of the existing ones (a synonym, spelling \
variant or abbreviation - not merely related)? Give its id, or null.

Answer with the submit_answer tool (same_as: an id, or "none"; confidence between 0 and 1; \
each "why" one short sentence)."""


def _json(text):
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else None


def build_options(p: Proposal, graph, sem_signals: dict, view):
    """[(role, concept)] with role in proposed/alternative/broader/narrower."""
    parent = p.parent_ids[0]
    roles = {parent: "proposed"}
    for alt in sem_signals.get("alternatives", [])[:N_ALTERNATIVES]:
        roles.setdefault(alt, "alternative")
    up = graph.path_to_root(parent)
    if len(up) > 1:
        roles.setdefault(up[1]["id"], "broader")
    kids = [k for k in view.children(parent) if k != p.id]
    if kids:
        embs = view.embeddings(kids)
        vec = view.embed_text(concept_text(p.name, p.description))
        if embs:
            roles.setdefault(max(embs, key=lambda k: float(vec @ embs[k])), "narrower")
    return roles


def _describe(graph, cid):
    c = graph.concept(cid)
    path = " > ".join(x["name"] for x in reversed(graph.path_to_root(cid)))
    desc = (c.get("description") or "")[:140]
    return f"{c['name']} — {desc} (path: {path})"


def ask(client, p: Proposal, graph, roles: dict, nearest: list[dict]):
    ids = list(roles)
    random.Random(p.id + "|".join(sorted(ids))).shuffle(ids)
    keys = "ABCDEFG"
    opts = {keys[i]: cid for i, cid in enumerate(ids)}
    none_key = keys[len(ids)]
    prompt = PROMPT.format(
        name=p.name, original=f" (learner's words: {p.name_original})" if p.name_original else "",
        description=p.description or "(none given)",
        options="\n".join(f"{k}. {_describe(graph, cid)}" for k, cid in opts.items()),
        none_key=none_key,
        nearest="\n".join(f"- id {n['id']}: {_describe(graph, n['id'])}" for n in nearest) or "(none)")
    # Answer through a tool with a schema, so it is machine-readable (free-text JSON was
    # unreadable in ~3% of calls). Forcing the tool (tool_choice "tool") is not supported
    # for this model, so the choice is "auto" and a text answer is parsed as a fallback.
    near_ids = [n["id"] for n in nearest]
    tool = {"name": "submit_answer", "description": "Submit the best parent and the duplicate check.",
            "input_schema": {"type": "object", "properties": {
                "parent": {"type": "string", "enum": list(opts) + [none_key]},
                "confidence": {"type": "number"},
                "why": {"type": "string"},
                "same_as": {"type": "string", "enum": near_ids + ["none"]},
                "same_why": {"type": "string"}},
                "required": ["parent", "confidence", "why", "same_as"]}}
    ans, text, tokens = None, "", 0
    for _ in range(2):
        resp = client.messages.create(model=MODEL, max_tokens=1000, tools=[tool],
                                      tool_choice={"type": "auto"},
                                      messages=[{"role": "user", "content": prompt}])
        tokens += resp.usage.input_tokens + resp.usage.output_tokens
        ans = next((b.input for b in resp.content if b.type == "tool_use"), None)
        text = "".join(getattr(b, "text", "") or "" for b in resp.content if b.type == "text")
        if not ans:
            try:
                ans = _json(text)
            except ValueError:
                ans = None
        if ans and ans.get("parent"):
            break
    ans = ans or {}
    key = str(ans.get("parent", "")).strip().upper()[:1]
    chosen = opts.get(key)
    role = roles.get(chosen) if chosen else ("none" if key == none_key else "invalid")
    same = ans.get("same_as")
    same = same if same in near_ids else None
    return {"model": MODEL, "options": {k: [cid, roles[cid]] for k, cid in opts.items()},
            "picked": key, "picked_id": chosen, "picked_role": role,
            "confidence": ans.get("confidence"), "why": ans.get("why", ""),
            "same_as": same, "same_why": ans.get("same_why", ""),
            "tokens": tokens, "raw": None if ans else text[:500]}


def _check(name, result, message, **evidence):
    return Check(LAYER, name, result, message, evidence)


MESSAGES = {
    "proposed": (Result.PASS, "the blind validator picked the proposed parent on its own"),
    "broader": (Result.WARN, "the validator prefers the parent's parent: the proposal may be too specific"),
    "narrower": (Result.WARN, "the validator prefers a child of the parent: the proposal may be too broad"),
    "alternative": (Result.WARN, "the validator picked a different parent"),
    "none": (Result.WARN, "the validator found none of the candidates a good parent"),
    "invalid": (Result.SKIP, "the validator's answer could not be read"),
}


def run(p: Proposal, graph, view, client, sem_signals: dict, nearest: list[dict]):
    """Returns (checks, signals). Duplicates found here are WARN + evidence; the decision
    layer turns an agreed duplicate (layer 2 near-duplicate + validator same_as) into REJECT."""
    roles = build_options(p, graph, sem_signals, view)
    s = ask(client, p, graph, roles, nearest)
    res, msg = MESSAGES[s["picked_role"]]
    checks = [_check("blind_parent", res, msg, picked=s["picked_id"], role=s["picked_role"],
                     confidence=s["confidence"], why=s["why"], model=s["model"],
                     options=s["options"])]
    if s["same_as"]:
        checks.append(_check("blind_duplicate", Result.WARN,
                             f"the validator says it is the same concept as {s['same_as']}",
                             same_as=s["same_as"], why=s["same_why"]))
    return checks, s
