"""Selection, summary, rendering, consistency check and the blind-review package."""
import csv
import io
import json
from collections import Counter, defaultdict
from pathlib import Path

from simulator.concepts import CONCEPTS

from . import spec as S
from .common import DAY, keyed, label, overall

NAMES = {c.concept_id: c.name for c in CONCEPTS}
SCORED = {S.CORRECT, S.WRONG, S.UNCERTAIN}


def finish_case(c: dict) -> dict:
    c["overall"] = {"label": overall([d for d in c["dimensions"] if d["label"] in SCORED]),
                    "final_outcome": next((d["output"] for d in c["dimensions"]
                                           if d["family"] == "OUTCOME"), None)}
    return c


# ---- selection (spec.SELECTION_RULE) -----------------------------------------------------------

def select(cases_by_run: dict) -> tuple:
    """-> ({case_id: [reasons]}, empty cells, S2 group sizes)"""
    sel, empty, groups = defaultdict(list), [], {}
    for run, cases in cases_by_run.items():
        pops = sorted({c["population"] for c in cases})
        by_cell = defaultdict(list)
        wrong, unc = defaultdict(list), defaultdict(list)
        for c in cases:
            for d in c["dimensions"]:
                by_cell[(c["population"], d["family"], d["output"])].append(c["case_id"])
                if d["label"] == S.WRONG:
                    wrong[(d["family"], c["population"], d["kind"])].append((c["case_id"], d["name"]))
                elif d["label"] == S.UNCERTAIN:
                    unc[(d["family"], c["population"])].append((c["case_id"], d["name"]))
        for pop in pops:
            for fam in S.FAMILIES[run]:
                for out in S.VOCAB[fam]:
                    ids = sorted(set(by_cell.get((pop, fam, out), [])))
                    if not ids:
                        empty.append({"run": run, "population": pop, "family": fam,
                                      "output": out,
                                      "why": S.EMPTY_BY_DESIGN.get((run, fam, out),
                                                                   "no case had this output")})
                        continue
                    pick = sorted(ids, key=lambda i: (keyed(S.SELECTION_SEED, "S1", fam, out, i), i))
                    for i in pick[:S.COVER_PER_CELL]:
                        sel[i].append(f"S1 {fam}={out}")
        for (fam, pop, kind), xs in sorted(wrong.items()):
            groups[f"{run}|{fam}|{pop}|{kind}"] = len(xs)
            pick = sorted(xs, key=lambda x: (keyed(S.SELECTION_SEED, "S2", *x), x))
            for cid, dname in pick[:S.WRONG_CAP]:
                sel[cid].append(f"S2 WRONG {dname}: {kind}" + (
                    f" (sample {S.WRONG_CAP} of {len(xs)})" if len(xs) > S.WRONG_CAP else ""))
        for (fam, pop), xs in sorted(unc.items()):
            pick = sorted(xs, key=lambda x: (keyed(S.SELECTION_SEED, "S3", *x), x))
            for cid, dname in pick[:S.UNCERTAIN_PER_CELL]:
                sel[cid].append(f"S3 UNCERTAIN {dname}")
    return {k: sorted(set(v)) for k, v in sorted(sel.items())}, empty, groups


# ---- summary -----------------------------------------------------------------------------------

def summary(cases_by_run: dict) -> dict:
    out = {}
    for run, cases in cases_by_run.items():
        R = {"cases": len(cases), "overall": defaultdict(Counter), "labels": defaultdict(Counter),
             "outputs": defaultdict(Counter), "layers": defaultdict(Counter),
             "wrong_kinds": defaultdict(Counter), "uncertain_reasons": Counter()}
        for c in cases:
            p = c["population"]
            R["overall"][p][c["overall"]["label"]] += 1
            for d in c["dimensions"]:
                R["labels"][f"{p}|{d['family']}"][d["label"]] += 1
                R["outputs"][f"{p}|{d['family']}"][d["output"]] += 1
                if d["label"] == S.WRONG:
                    R["layers"][f"{p}|{d['family']}"][d["layer"]] += 1
                    R["wrong_kinds"][d["family"]][f"{d['kind']} | {d['layer']}"] += 1
                if d["label"] == S.UNCERTAIN:
                    R["uncertain_reasons"][f"{d['family']}: {d.get('uncertain_reason') or d['output']}"] += 1
        out[run] = {k: ({a: dict(sorted(b.items())) for a, b in sorted(v.items())}
                        if isinstance(v, defaultdict) else
                        dict(sorted(v.items())) if isinstance(v, Counter) else v)
                    for k, v in R.items()}
    return out


def layer_totals(summ: dict) -> dict:
    tot = Counter()
    for run, R in summ.items():
        for cell, ls in R["layers"].items():
            for layer, n in ls.items():
                tot[(run, cell.split("|")[1], layer)] += n
    return {f"{r}|{f}|{l}": n for (r, f, l), n in sorted(tot.items())}


# ---- rendering ---------------------------------------------------------------------------------

def _yn(x):
    return "-" if x is None else ("yes" if x is True else "no" if x is False else str(x))


def _f(x, nd=3):
    return "-" if x is None else f"{x:.{nd}f}"


def _truth(d):
    t = d["truth"]
    if isinstance(t, dict):
        return t["outcome"]
    return {True: "yes", False: "no", None: "-"}.get(t, t) if not isinstance(t, str) else t


def _runs(xs):
    """Run-length form of a version path: A x3 -> B x2."""
    out = []
    for x in xs:
        if out and out[-1][0] == x:
            out[-1][1] += 1
        else:
            out.append([x, 1])
    return " -> ".join(f"{a} x{n}" for a, n in out)


def _stage(v, t0) -> str:
    if not isinstance(v, dict):
        return str(v)
    parts = []
    for k in sorted(v):
        x = v[k]
        if k in ("t_end", "t_r", "overdue_at"):
            x = f"day {(x - t0) / DAY:.2f}"
        elif k == "version_outcomes":
            x = _runs(x)
        elif isinstance(x, float):
            x = f"{x:.3g}"
        elif isinstance(x, dict):
            x = "{" + ", ".join(f"{a}: {_stage(b, t0) if isinstance(b, dict) else (f'{b:.3g}' if isinstance(b, float) else b)}"
                                for a, b in sorted(x.items(), key=lambda kv: str(kv[0]))) + "}"
        parts.append(f"{k}={x}")
    return "; ".join(parts)


def answer_line(w: dict, t0: float) -> str:
    tr = w["true"] or {}
    ev = w["disposition"] + (f" {w['dimension']}" if w["dimension"] else "") + (
        f" {w['reason']}" if w["reason"] else "")
    return (f"  {(w['t'] - t0) / DAY:6.2f} {str(w['phase'])[:13]:13s} {_yn(w['round']):3s} "
            f"{str(w['item_id'])[:11]:11s} {str(w['chosen_option'] or '-'):3s} "
            f"{_yn(w['correct']):3s} {_yn(w['help_recorded']):4s} "
            f"{_yn(w['confidence_recorded']):4s} | {ev[:34]:34s} | "
            f"{_yn(tr.get('known')):3s} {tr.get('path') or '-'}")


def dim_line(d: dict, blind: bool) -> str:
    extra = f", rule {d['rule']}" if d.get("rule") else ""
    line = (f"  {d['name']:22s} output {d['output']}{extra} (answers read {d['n']}); "
            f"truth {_truth(d)}")
    if not blind:
        line += f"  ->  {d['label']}" + (f" ({d['uncertain_reason']})"
                                         if d.get("uncertain_reason") else "")
    return line


def render(c: dict, blind: bool = False) -> str:
    cfg = S.RUNS[c["run"]]
    L = [f"CASE {c['case_id']}",
         f"  run          {c['run']} ({cfg['mission']}, seed {cfg['seed']}; {cfg['note']})",
         f"  population   {'(hidden in the blind review)' if blind else c['population']}",
         f"  concept      {NAMES.get(c['concept_id'], c['concept_id'])} ({c['concept_id'][:8]})"]
    if not blind:
        L.append("  selected by  " + "; ".join(c["selected_by"]))
    L += ["", "TRUTH (simulator; scoring side only - the evaluator never sees it)"]
    t = c["truth"]
    if c["run"] == "R95":
        for r, v in t["rounds"].items():
            L.append(f"  round {r}: knows at post-test {_yn(v['knows_at_post_test'])}; expected share "
                     f"unaided {_f(v['expected_unaided_share'])}, assisted "
                     f"{_f(v['expected_assisted_share'])} (gap {_f(v['true_gap'])}); "
                     f"confidence inflation {_f(v['true_confidence_inflation'])}")
        L.append(f"  never reports confidence {_yn(t['never_reports_confidence'])}; "
                 f"knew it before the first intervention {_yn(t['known_before_intervention'])}")
    else:
        for k, v in t.items():
            if k == "judged_at":
                continue
            L.append(f"  {k.replace('_', ' '):34s} {_yn(v)}")
    t0 = c["intervention_delivered_at"]
    t0 = t0[0] if isinstance(t0, list) else t0
    L += ["", f"ANSWERS on this concept (day = days after the {'first ' if c['run'] == 'R95' else ''}"
              f"intervention; {c['practice_answers']} practice answers are part of the "
              f"intervention and not listed)",
          "  day    phase         rnd item        opt ok  help conf | evaluator                    "
          "      | truth: knows path"]
    for w in c["answers"]:
        L.append(answer_line(w, t0))
    L += ["", "STAGES"]
    for k, v in c["stages"].items():
        L.append(f"  {k:13s} {_stage(v, t0)}")
    L += ["", "DIMENSIONS (system output vs truth)"]
    for d in c["dimensions"]:
        L.append(dim_line(d, blind))
        if not blind and d["label"] == S.WRONG:
            L.append(f"      layer {d['layer']}  evidence {json.dumps(d['layer_evidence'], sort_keys=True)}")
            L.append(f"      points to {d['points_to']}")
    if not blind:
        L += ["", f"OVERALL {c['overall']['label']}"]
    return "\n".join(L) + "\n"


# ---- consistency check: every rendered case against the raw run files --------------------------

def raw_index(root, run: str, learners: set) -> dict:
    """Read the raw answers.jsonl and truth.jsonl directly (no adapter, no evaluator)."""
    d = Path(root) / S.RUNS[run]["run"]
    rec, tru = {}, {}
    with open(d / "answers.jsonl", encoding="utf-8") as f:
        for line in f:
            b = json.loads(line)
            if b["learner_id"] in learners and b["operation"] == "ADD_EVIDENCE":
                rec[b["record"]["source_record_id"]] = (b["learner_id"], b["concept"]["concept_id"],
                                                        b["record"]["payload"])
    with open(d / "truth.jsonl", encoding="utf-8") as f:
        for line in f:
            t = json.loads(line)
            if t["learner_id"] in learners:
                tru[t["learner_id"]] = t
    return {"rec": rec, "truth": tru}


def check_case(c: dict, raw: dict, text: str) -> list:
    """Problems found (empty = consistent)."""
    bad = []
    rec, tru = raw["rec"], raw["truth"][c["learner_id"]]
    trace = {r["source_record_id"]: r for r in tru["trace"]}
    if tru["population"] != c["population"]:
        bad.append("population")
    listed = {w["record_id"] for w in c["answers"]}
    on_tuple = {rid for rid, (lid, cid, p) in rec.items() if lid == c["learner_id"]
                and cid == c["concept_id"] and p["activity"] != "PRACTICE"}
    if listed != on_tuple:
        bad.append(f"answers listed {len(listed)} != raw non-practice {len(on_tuple)}")
    lines = set(text.split("\n"))
    t0 = c["intervention_delivered_at"]
    t0 = t0[0] if isinstance(t0, list) else t0
    for w in c["answers"]:
        lid, cid, p = rec[w["record_id"]]
        if lid != c["learner_id"] or cid != c["concept_id"] or p.get("item_id") != w["item_id"] or \
                p.get("chosen_option") != w["chosen_option"] or \
                bool(p.get("had_help")) != bool(w["help_recorded"]) or \
                p.get("confidence") != w["confidence_recorded"] and c["run"] == "R95":
            bad.append(f"record {w['record_id'][:8]} differs from raw")
        if w["correct"] is not None and bool(p.get("correct")) != w["correct"]:
            bad.append(f"record {w['record_id'][:8]} correctness")
        tr = trace.get(w["record_id"], {})
        if w["true"] and (tr.get("path") != w["true"]["path"] or
                          tr.get("known") != w["true"]["known"]):
            bad.append(f"record {w['record_id'][:8]} truth")
        if answer_line(w, t0) not in lines:
            bad.append(f"text answer {w['record_id'][:8]}")
    cps = tru["checkpoints"]
    imm = cps["immediate"]["concepts"][c["concept_id"]]
    expect = {}                              # dimension truths recomputed from the raw truth
    if c["run"] == "R94":
        expect["VERDICT"] = imm["known"]
    elif c["run"] == "R95":
        for r in (1, 2, 3):
            cp = cps["immediate" if r == 1 else f"immediate_r{r}"]["concepts"][c["concept_id"]]
            expect[f"VERDICT@r{r}"] = cp["known"]
    else:
        dl = cps["delayed"]["concepts"][c["concept_id"]]
        acq = next(d for d in c["dimensions"] if d["name"] == "ACQUISITION")
        pooled = any(w["phase"] == "DELAYED_TEST" for w in c["answers"]
                     if w["record_id"] in set(acq["used"]))
        expect["ACQUISITION"] = (S.NOT_SCORABLE if pooled and imm["known"] != dl["known"]
                                 else imm["known"])
        expect["RETENTION"] = dl["known"]
    for d in c["dimensions"]:
        if d["name"] in expect and d["truth"] != expect[d["name"]]:
            bad.append(f"truth {d['name']}")
        if label(d["family"], d["output"], d["truth"], d["n"]) != d["label"]:
            bad.append(f"label {d['name']}")
        if not set(d["used"]) <= listed:
            bad.append(f"{d['name']} reads answers not listed")
        if d["family"] in ("VERDICT", "ACQUISITION", "RETENTION", "TRANSFER", "ERROR_REPETITION") \
                and len(d["used"]) != d["n"]:
            bad.append(f"{d['name']} n {d['n']} != answers read {len(d['used'])}")
        if dim_line(d, False) not in lines:
            bad.append(f"text {d['name']}")
        if d["label"] == S.WRONG and (not d["layer"] or not d["points_to"]):
            bad.append(f"{d['name']} wrong without layer")
    if finish_case(dict(c))["overall"]["label"] != c["overall"]["label"] or \
            f"OVERALL {c['overall']['label']}" not in text:
        bad.append("overall")
    return bad


# ---- blind review ------------------------------------------------------------------------------

def review_items(detailed: list) -> list:
    """30 (case, focus dimension) items: 10 WRONG, 10 UNCERTAIN, 10 CORRECT, round-robin over
    the runs, one item per case, keyed draws (spec.REVIEW_SEED)."""
    used_cases, items = set(), []
    for lab, k in S.REVIEW_STRATA:
        pools = {}
        for run in S.RUNS:
            xs = [(c["case_id"], d["name"]) for c in detailed if c["run"] == run
                  for d in c["dimensions"] if d["label"] == lab]
            pools[run] = sorted(xs, key=lambda x: (keyed(S.REVIEW_SEED, lab, *x), x))
        got = 0
        while got < k and any(pools.values()):
            for run in S.RUNS:
                while pools[run] and pools[run][0][0] in used_cases:
                    pools[run].pop(0)
                if pools[run] and got < k:
                    cid, dn = pools[run].pop(0)
                    used_cases.add(cid)
                    items.append({"stratum": lab, "case_id": cid, "dimension": dn})
                    got += 1
    order = sorted(items, key=lambda x: keyed(S.REVIEW_SEED, "order", x["case_id"]))
    for i, x in enumerate(order, 1):
        x["item"] = i
    return order


def review_package(items: list, by_id: dict) -> dict:
    """{filename: text}: cases (blind), answer sheet, key (never sent to the reviewer)."""
    parts, key = [], []
    for x in items:
        c = by_id[x["case_id"]]
        d = next(d for d in c["dimensions"] if d["name"] == x["dimension"])
        parts.append(f"=== ITEM {x['item']} ===\n" + render(c, blind=True) +
                     f"\nQUESTION: label dimension {x['dimension']} - CORRECT, WRONG or "
                     f"UNCERTAIN; if WRONG, the layer.\n")
        key.append({"item": x["item"], "case_id": x["case_id"], "dimension": x["dimension"],
                    "label": d["label"], "layer": d["layer"]})
    sheet = io.StringIO()
    w = csv.writer(sheet, lineterminator="\n")
    w.writerow(["item", "case_id", "dimension", "label", "layer", "notes"])
    for x in items:
        w.writerow([x["item"], x["case_id"], x["dimension"], "", "", ""])
    return {"review_cases.txt": "\n".join(parts), "answer_sheet.csv": sheet.getvalue(),
            "key.json": json.dumps(key, indent=1, sort_keys=True) + "\n"}


def kappa(pairs: list) -> dict:
    """Cohen's kappa for (system, reviewer) labels."""
    n = len(pairs)
    if n == 0:
        return {"n": 0}
    agree = sum(a == b for a, b in pairs) / n
    cats = sorted({x for p in pairs for x in p})
    pa = Counter(a for a, _ in pairs)
    pb = Counter(b for _, b in pairs)
    pe = sum(pa[k] * pb[k] for k in cats) / (n * n)
    k = None if pe == 1 else (agree - pe) / (1 - pe)
    conf = {a: {b: sum(1 for x, y in pairs if x == a and y == b) for b in cats} for a in cats}
    return {"n": n, "percent_agreement": agree, "kappa": k, "confusion_system_by_reviewer": conf}


def agreement(sheet_csv: str, key: list) -> dict:
    rows = {int(r["item"]): r for r in csv.DictReader(io.StringIO(sheet_csv))}
    lab, lay = [], []
    for k in key:
        r = rows.get(k["item"])
        if not r or not r["label"].strip():
            continue
        rl = r["label"].strip().upper()
        lab.append((k["label"], rl))
        if k["label"] == S.WRONG and rl == S.WRONG:
            lay.append((k["layer"], r["layer"].strip().upper() or "NONE"))
    return {"label": kappa(lab), "layer_when_both_wrong": kappa(lay),
            "answered": len(lab), "items": len(key)}
