"""Concepts of the material that the global graph does not have (decision 2026-10-18,
option A): each goes through the existing pipeline instead of being invented locally.

    SCRUM-89 placement agent  ->  ProposedConcept  ->  SCRUM-90 gate  ->  decision
      already_exists            : the agent found it after all -> link to that concept
      ACCEPT_PROVISIONAL        : now a provisional :Concept -> link to it
      NEEDS_REVIEW              : in the teacher's queue -> the material graph keeps a
                                  pending link to the proposal; it resolves when the teacher
                                  accepts (ProposedConcept -[:BECAME]-> Concept)
      REJECT (duplicate_of X)   : link to X
      REJECT                    : left out of the material graph, recorded in the report

Only SUBSTANTIAL concepts go to the global graph (decision 2026-10-18, after the first ENLP
run sent 129 concepts, many of them lecture details such as "Most frequent tag baseline"):
taught in some unit with importance 2 or 3. A minor or prerequisite-only concept without a
match is not proposed; it is logged as "not sent" with its unit and quote, so a person can
still send it later. The global graph is the backbone for every course; one course's details
belong in that course's material graph report, not in the shared graph.

The agent's input is built from the material (unit title, the concept's definition and
the evidence quote). It is untrusted text, handled exactly like a learner conversation:
the agent only has read tools and the one write happens in code after checks.
"""
from placement import config
from placement.agent import run_agent
from placement.traces import save_trace

from .link import MaterialConcept
from .llm import one_line


def agent_input(mc: MaterialConcept, material) -> str:
    occ = sorted(mc.occurrences, key=lambda o: (-o["importance"], o["unit_seq"]))[0]
    unit = next((u for u in material.units if u.seq == occ["unit_seq"]), None)
    return (f"Course material, course \"{one_line(material.title, 150)}\", unit "
            f"\"{one_line(unit.title if unit else '', 120)}\".\n"
            f"The unit {'teaches' if occ['role'] == 'taught' else 'uses'} the concept "
            f"\"{one_line(mc.name, 120)}\" (written in the material as "
            f"\"{one_line(mc.names_original[0] if mc.names_original else mc.name, 120)}\").\n"
            f"Definition: {one_line(mc.description, 400)}\n"
            f"Quote from the unit: \"{one_line(occ['evidence'], 300)}\"")


def _internal_id(graph, concept_uuid: str):
    rows = graph._read("MATCH (c:Concept {concept_id: $u}) RETURN c.id AS id", u=concept_uuid)
    return rows[0]["id"] if rows else None


def _existing_proposal(graph, name: str):
    """A proposal with this name from an earlier run: reuse it, never propose twice."""
    rows = graph._read(
        """MATCH (p:ProposedConcept) WHERE toLower(p.name) = toLower($name)
           OPTIONAL MATCH (p)-[:BECAME]->(c:Concept)
           RETURN p.id AS pid, p.status AS status, p.duplicate_of AS dup, c.id AS became
           ORDER BY p.created_at DESC LIMIT 1""", name=name)
    return rows[0] if rows else None


MIN_IMPORTANCE = 2


def is_substantial(mc: MaterialConcept) -> bool:
    return mc.taught_importance >= MIN_IMPORTANCE


def resolve_missing(concepts: list[MaterialConcept], graph, material, client,
                    wd_client=None, wp_client=None, model: str = config.CLAUDE_MODEL,
                    progress=print) -> list[dict]:
    """Run the pipeline for every concept without a canonical link. Returns one log row each."""
    from validation import gate, store
    from validation.neo4j_view import ensure_indexes, load_proposal
    ensure_indexes(graph)
    log = []
    todo = [mc for mc in concepts if mc.concept_id is None]
    for n, mc in enumerate(todo, 1):
        row = {"concept": mc.name, "role": mc.role, "importance": mc.taught_importance}
        prev = _existing_proposal(graph, mc.name)
        if prev:
            mc.proposal_id = prev["pid"]
            if prev["became"]:
                mc.concept_id, mc.gate_decision = prev["became"], "ACCEPT_PROVISIONAL"
            elif prev["status"] == "rejected" and prev["dup"]:
                mc.concept_id, mc.gate_decision = _internal_id(graph, prev["dup"]), "REJECT"
            else:
                mc.gate_decision = {"needs_review": "NEEDS_REVIEW", "rejected": "REJECT"}.get(
                    prev["status"], "PROPOSED")
            row.update(outcome="reused earlier proposal", proposal=mc.proposal_id,
                       decision=mc.gate_decision,
                       audit_candidate=not is_substantial(mc))   # a detail already in the graph
            log.append(row)
            continue
        if not is_substantial(mc):
            occ = sorted(mc.occurrences, key=lambda o: (-o["importance"], o["unit_seq"]))[0]
            row.update(outcome="not sent: minor or prerequisite-only", unit_seq=occ["unit_seq"],
                       evidence=occ.get("evidence", ""))
            log.append(row)
            continue

        res = run_agent(agent_input(mc, material), graph, client, model=model)
        trace = save_trace(res)
        row.update(trace=str(trace), tokens=res.input_tokens + res.output_tokens)
        d = res.decision
        if d is None:
            row["outcome"] = f"agent failed: {res.error}"
        elif d["decision"] == "already_exists":
            mc.concept_id, mc.link_method = d["existing_id"], "agent"
            mc.link_note = "placement agent found it in the graph"
            row.update(outcome="already in graph", concept_id=d["existing_id"])
        else:
            pid = graph.write_proposal(
                name=d["concept_name"], name_original=d.get("concept_name_original") or "",
                description=d["description"], parent_id=d["parent_id"],
                confidence=d["confidence"], reasoning=d["reasoning"], method="scrum91-material",
                model=model, trace_id=res.trace_id,
                requires=d.get("prerequisite_ids") or [], enables=d.get("enables_ids") or [],
                prerequisite_reasoning=d.get("prerequisite_reasoning") or "")
            mc.proposal_id = pid
            p = load_proposal(graph, pid)
            v = gate.validate(p, graph, client, wd_client, wp_client=wp_client)
            store.record_run(graph, v)
            summary = store.apply(graph, p, v)
            mc.gate_decision = v.decision.value
            if v.decision.value == "ACCEPT_PROVISIONAL":
                mc.concept_id = pid                      # the promoted Concept keeps the id
            elif v.decision.value == "REJECT" and v.duplicate_of:
                mc.concept_id = _internal_id(graph, v.duplicate_of) or v.duplicate_of
            if mc.concept_id:
                mc.link_method = "scrum89-90"
            row.update(outcome=summary, proposal=pid, decision=v.decision.value,
                       parent=d["parent_id"], rule=v.rule)
        log.append(row)
        if progress and not row["outcome"].startswith("not sent"):
            progress(f"  missing {n}/{len(todo)} {mc.name}: {row.get('outcome')}")
    if progress:
        sent = sum(1 for r in log if not r["outcome"].startswith("not sent"))
        progress(f"  {sent} sent to the SCRUM-89/90 pipeline, {len(log) - sent} not sent (minor)")
    return log
