"""python -m simulator --seed 93 --n 200 --out runs/seed-93
   python -m simulator --scrum95 --seed 95 --n 200 --out runs/seed-95   (SCRUM-95 preset)"""
import argparse
from dataclasses import replace

from .config import DEFAULT, SCRUM95, SCRUM95_POST_ITEMS, items_needed
from .generator import simulate
from .populations import ALL_POPULATIONS, POPULATIONS
from .records import write_run


def main():
    ap = argparse.ArgumentParser(description="SCRUM-93 learner simulator")
    ap.add_argument("--seed", type=int, default=93)
    ap.add_argument("--n", type=int, default=200, help="learners per population")
    ap.add_argument("--out", default=None)
    ap.add_argument("--post-items", type=int, default=None, help="immediate post-test length")
    ap.add_argument("--bank", type=int, default=None, help="items per concept in the bank")
    g = ap.add_argument_group("SCRUM-95 (all off by default)")
    g.add_argument("--scrum95", action="store_true",
                   help="preset: 10 populations, 3 rounds, 2 assisted items, 8-item post-test, "
                        "confidence missing not at random")
    g.add_argument("--rounds", type=int)
    g.add_argument("--assisted-items", type=int)
    g.add_argument("--never-report", type=float)
    g.add_argument("--report-prob", help="five numbers, P(report) for confidence 1..5")
    g.add_argument("--exclude", default="", help="comma-separated populations to leave out "
                   "(e.g. the confidence-norm calibration run of calibrated learners only)")
    a = ap.parse_args()

    cfg = SCRUM95 if a.scrum95 else DEFAULT
    changes = {k: v for k, v in (("rounds", a.rounds), ("assisted_items", a.assisted_items),
                                 ("never_report", a.never_report)) if v is not None}
    if a.report_prob:
        changes["report_prob"] = tuple(float(x) for x in a.report_prob.split(","))
    cfg = replace(cfg, **changes)
    pops = ALL_POPULATIONS if a.scrum95 else POPULATIONS
    drop = {x for x in a.exclude.split(",") if x}
    unknown = drop - {p.name for p in pops}
    if unknown:
        ap.error(f"unknown populations: {sorted(unknown)}")
    pops = tuple(p for p in pops if p.name not in drop)
    post = a.post_items if a.post_items is not None else (SCRUM95_POST_ITEMS if a.scrum95 else 3)
    bank = a.bank if a.bank is not None else max(20, items_needed(post, cfg))
    out = a.out or f"runs/seed-{a.seed}"
    m = write_run(simulate(a.seed, a.n, populations=pops, post_items=post,
                           items_per_concept=bank, config=cfg), out)
    print(f"{m['learners']} simulated learners ({a.n} x {len(m['populations'])} populations), "
          f"{m['records']} records ({m['evidence_records']} answers) -> {out}")
    print(f"answers.jsonl sha256 {m['sha256']['answers.jsonl'][:16]}...  (truth is in truth.jsonl)")


if __name__ == "__main__":
    main()
