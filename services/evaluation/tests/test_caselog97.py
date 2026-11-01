"""SCRUM-97 case analysis log: label rules, attribution chain, selection, agreement, and a
small end-to-end run (mini simulated runs) - reproducible byte for byte, every rendered case
consistent with the raw files, every cell filled or listed empty, every WRONG with a layer."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from caselog import log as G
from caselog import spec as S
from caselog.common import attribute, keyed, label, overall

ROOT = Path(__file__).resolve().parents[1]


# ---- label rules -------------------------------------------------------------------------------

def test_yes_no_labels():
    assert label("VERDICT", "DEMONSTRATED", True, 8) == S.CORRECT
    assert label("VERDICT", "DEMONSTRATED", False, 8) == S.WRONG
    assert label("VERDICT", "NOT_YET_DEMONSTRATED", True, 8) == S.WRONG
    assert label("VERDICT", "NOT_YET_DEMONSTRATED", False, 8) == S.CORRECT
    assert label("VERDICT", "INSUFFICIENT_EVIDENCE", True, 8) == S.UNCERTAIN
    assert label("VERDICT", "INSUFFICIENT_EVIDENCE", True, 0) == S.UNCERTAIN   # verdict ran
    assert label("RETENTION", "INSUFFICIENT", True, 0) == S.NOT_OBSERVED       # check missing
    assert label("TRANSFER", "SUPPORTED", S.NOT_SCORABLE, 4) == S.NOT_SCORABLE


def test_outcome_claims_r1a():
    facts = {"shown": True, "not_shown": False, "lost": False, "retained": True,
             "misconception": False, "pattern": False}
    t = {"outcome": "DEMONSTRATED_RETAINED", "facts": facts}
    assert label("OUTCOME", "DEMONSTRATED_RETAINED", t, 9) == S.CORRECT
    assert label("OUTCOME", "DEMONSTRATED", t, 9) == S.UNCERTAIN          # weaker, true
    assert label("OUTCOME", "NOT_YET_DEMONSTRATED", t, 9) == S.WRONG      # false claim
    assert label("OUTCOME", "MISCONCEPTION_PERSISTS", t, 9) == S.WRONG
    assert label("OUTCOME", "INSUFFICIENT_EVIDENCE", t, 9) == S.UNCERTAIN


def test_overall_precedence_ignores_unobserved():
    d = lambda lab: {"label": lab}
    assert overall([d(S.CORRECT), d(S.UNCERTAIN)]) == S.UNCERTAIN
    assert overall([d(S.CORRECT), d(S.UNCERTAIN), d(S.WRONG)]) == S.WRONG
    assert overall([d(S.CORRECT)]) == S.CORRECT
    assert overall([]) == S.UNCERTAIN


# ---- attribution chain -------------------------------------------------------------------------

def _row(known, path="KNOWS", correct=True, help_rec=False, had_help=False, conf=3,
         dim="ACQUISITION", rnd=None):
    return {"record_id": f"r{id(object())}", "correct": correct, "help_recorded": help_rec,
            "confidence_recorded": conf, "dimension": dim, "round": rnd,
            "true": {"known": known, "path": path, "depth": "IDEA" if known else None,
                     "had_help": had_help}}


def test_chain_order():
    dim = {"family": "VERDICT", "output": "NOT_YET_DEMONSTRATED"}
    # help not recorded beats everything
    assert attribute(dim, [_row(True, had_help=True), _row(False)], {})[0] == S.INPUT
    # state changed inside one window
    assert attribute(dim, [_row(True), _row(False, "GUESS")], {})[0] == S.INTERACTION
    # ... but not across two different windows
    rows = [_row(True, dim="ACQUISITION"), _row(False, "GUESS", dim="RETENTION")]
    assert attribute(dict(dim, family="OUTCOME"), rows, {})[0] == S.INFERENCE
    # a knowing learner's misconception errors behind a "not yet"
    assert attribute(dim, [_row(True), _row(True, "MISCONCEPTION", False)], {})[0] == S.INTERACTION
    # otherwise inference, with the evidence counted
    lay, ev = attribute(dim, [_row(True, "SLIP", False), _row(True)], {})
    assert lay == S.INFERENCE and ev["slips_while_knowing"] == 1


def test_chain_confidence_missing_is_input():
    dim = {"family": "CONFIDENCE_GAP", "output": "PERCEIVED_ABOVE"}
    assert attribute(dim, [_row(True, conf=None), _row(True)], {})[0] == S.INPUT
    assert attribute(dim, [_row(True), _row(True)], {})[0] == S.INFERENCE


def test_chain_adaptation_only_for_a_withheld_check():
    rows = [_row(True), _row(True)]
    out = {"family": "OUTCOME", "output": "NOT_RETAINED", "false_claims": ["lost"]}
    assert attribute(out, rows, {"check_withheld": True})[0] == S.ADAPTATION
    assert attribute(out, rows, {"check_withheld": False})[0] == S.INFERENCE
    assert attribute(dict(out, false_claims=["pattern"]), rows,
                     {"check_withheld": True})[0] == S.INFERENCE


# ---- selection, draws, agreement ---------------------------------------------------------------

def _case(cid, pop, out, lab, kind=None):
    return {"case_id": cid, "population": pop,
            "dimensions": [{"name": "VERDICT", "family": "VERDICT", "output": out, "label": lab,
                            "kind": kind}]}


def test_selection_is_keyed_not_order_dependent():
    cs = [_case(f"R94-{i:04d}", "P", "DEMONSTRATED", S.CORRECT) for i in range(20)] + \
         [_case(f"R94-w{i:03d}", "P", "NOT_YET_DEMONSTRATED", S.WRONG, "k") for i in range(9)]
    a = G.select({"R94": cs})
    b = G.select({"R94": list(reversed(cs))})
    assert a == b
    sel, empty, groups = a
    assert groups == {"R94|VERDICT|P|k": 9}
    assert sum(1 for v in sel.values() for r in v if r.startswith("S2")) == S.WRONG_CAP
    assert any(e["output"] == "INSUFFICIENT_EVIDENCE" for e in empty)   # listed, not hidden


def test_keyed_draw_is_stable():
    assert keyed(97, "x") == keyed(97, "x") and keyed(97, "x") != keyed(97, "y")


def test_kappa():
    assert G.kappa([("A", "A"), ("B", "B")])["kappa"] == 1.0
    k = G.kappa([("A", "A"), ("A", "B"), ("B", "A"), ("B", "B")])
    assert k["percent_agreement"] == 0.5 and abs(k["kappa"]) < 1e-12


def test_agreement_reads_sheet():
    key = [{"item": 1, "label": "WRONG", "layer": "INFERENCE"},
           {"item": 2, "label": "CORRECT", "layer": None}]
    sheet = "item,case_id,dimension,label,layer,notes\n1,a,V,wrong,inference,\n2,b,V,CORRECT,,\n"
    r = G.agreement(sheet, key)
    assert r["label"]["percent_agreement"] == 1.0 and r["layer_when_both_wrong"]["n"] == 1


# ---- end to end on mini runs -------------------------------------------------------------------

MINI = [
    ["-m", "simulator", "--seed", "19400", "--n", "6", "--post-items", "16", "--bank", "26",
     "--out", "runs/calib-9400"],
    ["-m", "harness.calibrate", "runs/calib-9400", "runs/calib-9400/calibration.json"],
    ["-m", "simulator", "--seed", "193", "--n", "4", "--post-items", "8", "--bank", "20",
     "--out", "runs/seed-93-L8"],
    ["-m", "simulator", "--seed", "19500", "--n", "6", "--post-items", "16", "--bank", "48",
     "--out", "runs/calib-9500"],
    ["-m", "harness.calibrate", "runs/calib-9500", "runs/calib-9500/calibration.json"],
    ["-m", "simulator", "--scrum95", "--seed", "19510", "--n", "6", "--out", "runs/confnorm-9510"],
    ["-m", "gap.confnorm", "runs/confnorm-9510", "runs/confnorm-9510/norm.json"],
    ["-m", "simulator", "--scrum95", "--seed", "19511", "--n", "6", "--never-report", "0",
     "--report-prob", "1,1,1,1,1", "--exclude", "CONFIDENT_WRONG,HELP_INFLATED",
     "--out", "runs/confnorm-9511-clean"],
    ["-m", "gap.confnorm", "runs/confnorm-9511-clean", "runs/confnorm-9511-clean/norm.json"],
    ["-m", "simulator", "--scrum95", "--seed", "195", "--n", "4", "--out", "runs/seed-95"],
    ["-m", "simulator", "--scrum96", "--seed", "19600", "--n", "6", "--post-items", "16",
     "--bank", "40", "--out", "runs/calib-9600"],
    ["-m", "harness.calibrate", "runs/calib-9600", "runs/calib-9600/calibration.json"],
    ["-m", "simulator", "--scrum96", "--seed", "196", "--n", "4", "--out", "runs/seed-96"],
]


@pytest.fixture(scope="module")
def mini(tmp_path_factory):
    root = tmp_path_factory.mktemp("mini97")
    env = {"PYTHONPATH": str(ROOT)}
    import os
    env = dict(os.environ, **env)
    for args in MINI:
        subprocess.run([sys.executable, *args], cwd=root, env=env, check=True,
                       stdout=subprocess.DEVNULL)
    outs = []
    for name in ("a", "b"):
        subprocess.run([sys.executable, "-m", "harness.case97", "--root", str(root), "--out",
                        str(root / f"out-{name}"), "--workers", "2"], cwd=ROOT, env=env,
                       check=True, stdout=subprocess.DEVNULL)
        outs.append(root / f"out-{name}")
    return outs


FILES = ("cases.txt", "cases.jsonl", "all_labels.jsonl", "summary.json", "summary.md",
         "check.json", "manifest.json", "review/review_cases.txt", "review/answer_sheet.csv",
         "review_key/key.json")


def test_mini_byte_identical(mini):
    a, b = mini
    for f in FILES:
        assert (a / f).read_bytes() == (b / f).read_bytes(), f


def test_mini_consistent_and_attributed(mini):
    a = mini[0]
    assert json.loads((a / "check.json").read_text())["problems"] == 0
    for line in (a / "cases.jsonl").read_text().splitlines():
        c = json.loads(line)
        for d in c["dimensions"]:
            if d["label"] == S.WRONG:
                assert d["layer"] in S.LAYERS and d["points_to"]
        assert c["selected_by"]


def test_mini_every_cell_filled_or_empty(mini):
    a = mini[0]
    summ = json.loads((a / "summary.json").read_text())
    empty = {(e["run"], e["population"], e["family"], e["output"]) for e in summ["empty_cells"]}
    labels = [json.loads(x) for x in (a / "all_labels.jsonl").read_text().splitlines()]
    have = set()
    for c in labels:
        run = c["case_id"][:3]
        for name, out, _, _ in c["dims"]:
            have.add((run, c["population"], name.split("@")[0], out))
    for run, fams in S.FAMILIES.items():
        pops = {c["population"] for c in labels if c["case_id"].startswith(run)}
        for p in pops:
            for f in fams:
                for o in S.VOCAB[f]:
                    assert ((run, p, f, o) in have) != ((run, p, f, o) in empty), (run, p, f, o)


def test_blind_review_hides_labels(mini):
    a = mini[0]
    txt = (a / "review" / "review_cases.txt").read_text()
    assert "->  CORRECT" not in txt and "->  WRONG" not in txt and "layer " not in txt
    assert "OVERALL" not in txt and "selected by" not in txt


def test_check_catches_mutations(mini):
    """Independent review: the consistency check must be able to fail on every field shown."""
    import copy
    a = mini[0]
    root = a.parent
    cases = [json.loads(x) for x in (a / "cases.jsonl").read_text().splitlines()]
    for c in cases[:6]:
        raw = G.raw_index(root, c["run"], {c["learner_id"]})
        assert G.check_case(c, raw, G.render(c)) == []
        m = copy.deepcopy(c)                        # truth column of one answer flipped
        w = next(w for w in m["answers"] if w["true"])
        w["true"]["known"] = not w["true"]["known"]
        assert G.check_case(m, raw, G.render(m))
        m = copy.deepcopy(c)                        # the text says another output
        txt = G.render(m).replace(f"output {m['dimensions'][0]['output']} ",
                                  f"output {m['dimensions'][0]['output']}_X ", 1)
        assert G.check_case(m, raw, txt)
        m = copy.deepcopy(c)                        # a dimension truth changed
        d = m["dimensions"][0]
        if isinstance(d["truth"], bool):
            d["truth"] = not d["truth"]
            assert G.check_case(m, raw, G.render(m))
        m = copy.deepcopy(c)                        # an answer dropped from the list
        m["answers"] = m["answers"][1:]
        assert G.check_case(m, raw, G.render(m))
