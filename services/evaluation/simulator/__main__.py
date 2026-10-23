"""python -m simulator --seed 93 --n 200 --out runs/seed-93"""
import argparse

from .generator import simulate
from .records import write_run


def main():
    ap = argparse.ArgumentParser(description="SCRUM-93 learner simulator")
    ap.add_argument("--seed", type=int, default=93)
    ap.add_argument("--n", type=int, default=200, help="learners per population")
    ap.add_argument("--out", default=None)
    ap.add_argument("--post-items", type=int, default=3, help="immediate post-test length")
    ap.add_argument("--bank", type=int, default=20, help="items per concept in the bank")
    a = ap.parse_args()
    out = a.out or f"runs/seed-{a.seed}"
    m = write_run(simulate(a.seed, a.n, post_items=a.post_items,
                           items_per_concept=a.bank), out)
    print(f"{m['learners']} simulated learners ({a.n} x {len(m['populations'])} populations), "
          f"{m['records']} records ({m['evidence_records']} answers) -> {out}")
    print(f"answers.jsonl sha256 {m['sha256']['answers.jsonl'][:16]}...  (truth is in truth.jsonl)")


if __name__ == "__main__":
    main()
