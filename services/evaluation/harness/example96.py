"""One case followed version by version (SCRUM-96).

    python -m harness.example96 [--population LEARNS_THEN_FORGETS] [--run runs/seed-96]

Picks the first case of the population whose final outcome is the population's expected
one (or any case if none) and prints every version: when, why, the outcome, each
dimension's status and count, and the missing checks.
"""
import argparse

from harness import adapter94 as A
from harness import adapter96 as A6
from harness.validate96 import EXPECTED
from outcome import engine as E
from outcome.misconception import AnswerBuiltMisconceptions, option_map
from simulator.concepts import CONCEPTS

DAY = 86_400.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--population", default="LEARNS_THEN_FORGETS")
    ap.add_argument("--run", default="runs/seed-96")
    ap.add_argument("--calib", default="runs/calib-9600/calibration.json")
    a = ap.parse_args()
    calib = A.load_calibration(a.calib)
    run = A6.load_run96(a.run, calib)
    ls = A6.standin_for96(run)
    items = A6.load_items(a.run)
    imap = option_map(items)
    mr = AnswerBuiltMisconceptions(
        A6.concept_misconceptions(items, {c.source_id: c.concept_id for c in CONCEPTS}), imap)
    pop_of = {lid: t["population"] for (lid, _), t in A6.load_truth96(a.run).items()}
    want = EXPECTED.get(a.population)
    chosen = None
    for lid in sorted(run):
        if pop_of.get(lid) != a.population:
            continue
        L = run[lid]
        for cid in sorted(L["interventions"]):
            r = E.run_case(E.Case(L["interventions"][cid], ls, mr, L["answers"], [], L["meta"],
                                  imap, L["horizon"]))
            if chosen is None:
                chosen = (lid, cid, r)
            if want is None or r.final["outcome"] == want:
                chosen = (lid, cid, r)
                break
        else:
            continue
        break
    lid, cid, r = chosen
    name = next(c.name for c in CONCEPTS if c.concept_id == cid)
    print(f"{a.population}  learner {lid[:8]}  concept {name}")
    print(f"treatment end t0; t_R = t0 + {(r.t_r - r.t_end) / DAY:.2f} d; "
          f"overdue at t0 + {(r.overdue_at - r.t_end) / DAY:.2f} d; "
          f"known misconceptions at delivery: {r.known_misconceptions or 'none'}")
    for v in r.versions:
        d = v["dimensions"]
        dims = "  ".join(f"{k[:3]} {x['status'][:4]}/{x['n']}" for k, x in d.items())
        miss = ",".join(f"{m['dimension'][:3]}{'!' if m['state'] == E.OVERDUE else ''}"
                        for m in v["missing"]) or "-"
        print(f"v{v['version']:>2}  t0{(v['as_of'] - r.t_end) / DAY:+7.2f} d  "
              f"{v['trigger'][:22]:<22} {v['outcome']:<24} {dims}  "
              f"rep {v['error_repetition_status'][:4]}  missing {miss}")


if __name__ == "__main__":
    main()
