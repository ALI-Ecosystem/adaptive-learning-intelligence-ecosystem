"""Shared pieces of the case log: labels, attribution, keyed draws, answer rows."""
import hashlib
from pathlib import Path

from . import spec as S

YES = {"DEMONSTRATED", "CREDIBLE_GAP", "REDUCED", "SUPPORTED"}
NO = {"NOT_YET_DEMONSTRATED", "NO_CREDIBLE_GAP", "NOT_REDUCED", "NOT_SUPPORTED"}
DAY = 86_400.0


def keyed(*parts) -> float:
    """A reproducible draw in [0, 1) from a key - no shared random state, no order effects."""
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return (int.from_bytes(h[:8], "big") >> 11) / float(1 << 53)


def spec_sha() -> str:
    return hashlib.sha256((Path(__file__).parent / "spec.py").read_bytes()).hexdigest()


def label(family: str, output: str, truth, n_used: int) -> str:
    """The pre-registered label rule of one dimension."""
    if truth == S.NOT_SCORABLE:
        return S.NOT_SCORABLE
    if n_used == 0 and family in ("ACQUISITION", "RETENTION", "TRANSFER", "ERROR_REPETITION"):
        return S.NOT_OBSERVED
    if output in S.UNCERTAIN_OUTPUTS:
        return S.UNCERTAIN
    if family in S.YES_NO_INS:
        if output in YES:
            return S.CORRECT if truth else S.WRONG
        if output in NO:
            return S.WRONG if truth else S.CORRECT
        raise ValueError(f"{family}: unknown output {output}")
    if family == "OUTCOME":                              # R1a: truth = {"outcome", "facts"}
        if output == truth["outcome"]:
            return S.CORRECT
        return S.UNCERTAIN if not false_claims(output, truth["facts"]) else S.WRONG
    return S.CORRECT if output == truth else S.WRONG     # CONFIDENCE_GAP: classes


def false_claims(output: str, facts: dict) -> list:
    """R1a: the atomic claims of a SCRUM-96 outcome that the truth contradicts."""
    return [c for c in S.OUTCOME_CLAIMS[output] if not facts[c]]


def wrong_kind(output, truth) -> str:
    if isinstance(truth, dict):
        truth = truth["outcome"]
    return f"{output} / truth {truth}"


def overall(dims: list) -> str:
    present = {d["label"] for d in dims}
    for lab in S.PRECEDENCE:
        if lab in present:
            return lab
    return S.UNCERTAIN          # nothing observed in any dimension


def row(rec, meta: dict, tr: dict | None, disposition: str, reason, dimension) -> dict:
    """One answer of the chain: what was recorded, what the evaluator did with it, and (from
    the truth, scoring side) what really happened."""
    return {"record_id": rec.record_id, "t": rec.occurred_at, "phase": meta.get("phase"),
            "round": meta.get("round"), "activity_type": meta.get("activity_type"),
            "item_id": rec.item_id, "chosen_option": rec.chosen_option,
            "correct": rec.credit >= 1.0 if meta.get("activity_type") != "EXPLANATION" else None,
            "credit": rec.credit, "help_recorded": rec.help_before_answer,
            "attempt": rec.attempt_number, "confidence_recorded": meta.get("confidence"),
            "disposition": disposition, "reason": reason, "dimension": dimension,
            "true": None if tr is None else {
                "known": tr.get("known"), "path": tr.get("path"), "depth": tr.get("depth"),
                "misconception": tr.get("misconception"), "had_help": tr.get("had_help"),
                "confidence": tr.get("confidence_true")}}


def attribute(dim: dict, used: list, ctx: dict) -> tuple:
    """The pre-registered chain (spec.ATTRIBUTION_CHAIN) on one WRONG dimension.
    used: the answer rows the dimension read. ctx: run facts (late retention check)."""
    fam = dim["family"]
    # 1 input data
    bad = [r for r in used if r["true"] and r["true"]["had_help"] is not None
           and bool(r["true"]["had_help"]) != bool(r["help_recorded"])]
    if bad:
        return S.INPUT, {"help_not_recorded": len(bad)}
    if fam.startswith("CONFIDENCE"):
        miss = [r for r in used if r["confidence_recorded"] is None]
        if miss:
            return S.INPUT, {"self_reports_missing": len(miss), "answers_read": len(used)}
    # 2 adaptation decision (R1b): the false claim is about a check the ALE stand-in withheld
    if ctx.get("check_withheld") and fam in ("RETENTION", "OUTCOME") and (
            fam == "RETENTION" or {"lost", "retained"} & set(dim.get("false_claims") or ())):
        return S.ADAPTATION, {"retention_check": "WITHHELD_BY_ALE_STAND_IN"}
    # 3 interaction
    tru = [r["true"] for r in used if r["true"]]
    windows = {}
    for r in used:          # one window = one dimension (SCRUM-96) in one round (SCRUM-95)
        if r["true"]:
            windows.setdefault((str(r["dimension"]), str(r["round"])), []).append(r["true"])
    for (wd, wr), ts in sorted(windows.items()):
        known = {t["known"] for t in ts}
        depth = {t["depth"] for t in ts if t["known"]}
        if len(known) > 1 or len(depth) > 1:
            flips = sum(1 for a, b in zip(ts, ts[1:]) if a["known"] != b["known"])
            return S.INTERACTION, {"state_changed_in_window": wd if wr == "None" else f"{wd} r{wr}",
                                   "known_changes": flips,
                                   "depths": sorted(str(d) for d in depth)}
    mis_known = [t for t in tru if t["known"] and t["path"] == "MISCONCEPTION"]
    if mis_known and dim["output"] not in YES:
        return S.INTERACTION, {"misconception_errors_while_knowing": len(mis_known)}
    # 4 inference
    if fam == "ERROR_REPETITION":
        picks = [r for r in used if r.get("mis_pick")]
        return S.INFERENCE, {"answers": len(used), "misconception_picks": len(picks),
                             "picks_while_not_holding_it": sum(
                                 1 for r in picks if r["true"] and not r["true"]["misconception"]),
                             "picks_path": dict(sorted(
                                 __import__("collections").Counter(
                                     (r["true"] or {}).get("path") for r in picks).items()))}
    ans = [r for r in used if r["correct"] is not None]
    lucky = sum(1 for r in ans if r["correct"] and r["true"] and not r["true"]["known"])
    slips = sum(1 for r in ans if not r["correct"] and r["true"] and r["true"]["known"])
    return S.INFERENCE, {"answers": len(ans), "correct": sum(1 for r in ans if r["correct"]),
                         "correct_guesses_while_not_knowing": lucky,
                         "slips_while_knowing": slips}


def points_to(fam: str, layer: str, rule=None) -> str:
    base = S.MISSION_RULE[fam] + (f", rule {rule}" if rule is not None else "")
    return f"{base} | {S.LAYER_HINT[layer]}"


def finish_dim(dim: dict, used: list, ctx: dict) -> dict:
    """Label, and for a WRONG dimension its kind, layer, evidence and pointer."""
    dim["label"] = label(dim["family"], dim["output"], dim["truth"], dim["n"])
    dim["used"] = [r["record_id"] for r in used]
    if dim["family"] == "OUTCOME" and dim["output"] in S.OUTCOME_CLAIMS:
        dim["false_claims"] = false_claims(dim["output"], dim["truth"]["facts"])
        if dim["label"] == S.UNCERTAIN:
            dim["uncertain_reason"] = S.INCOMPLETE
    if dim["label"] == S.WRONG:
        behind = {f for c in dim.get("false_claims") or () for f in S.CLAIM_DIMS[c]}
        inherit = [d for d in ctx.get("sub_dims", []) if d["label"] == S.WRONG
                   and d["family"] in behind]
        if dim["family"] == "OUTCOME" and inherit:      # R1b: the wrong sub-dimension's layer
            order = (S.INPUT, S.ADAPTATION, S.INTERACTION, S.INFERENCE)
            src = min(inherit, key=lambda d: order.index(d["layer"]))
            layer, ev = src["layer"], dict(src["layer_evidence"], from_dimension=src["name"])
        else:
            layer, ev = attribute(dim, used, ctx)
        dim.update(kind=wrong_kind(dim["output"], dim["truth"]), layer=layer,
                   layer_evidence=ev, points_to=points_to(dim["family"], layer, dim.get("rule")))
    else:
        dim.update(kind=None, layer=None, layer_evidence=None, points_to=None)
    return dim
