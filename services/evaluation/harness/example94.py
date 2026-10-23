"""One verdict, explained: the task's 'Dani' example on a simulated learner.

    python -m harness.example94 [run_dir] [population]

Picks the first learner of the population (default LEARNS) in the run (default
runs/seed-93-L8), and prints what the verdict saw and decided for each concept. The truth
is printed last, separately, from the scoring side.
"""
import sys
from datetime import timedelta

from harness import adapter94 as A
from verdict import engine


def fmt_t(s):
    return (A.EPOCH + timedelta(seconds=s)).strftime("%Y-%m-%d %H:%M")


def main():
    run_dir = sys.argv[1] if len(sys.argv) > 1 else "runs/seed-93-L8"
    pop = sys.argv[2] if len(sys.argv) > 2 else "LEARNS"
    calib = A.load_calibration("runs/calib-9400/calibration.json")
    run = A.load_run(run_dir, calib)
    truth = A.load_truth(run_dir)
    lid = next(l for (l, _), t in sorted(truth.items()) if t["population"] == pop)
    L = run[lid]
    ls = A.standin_for({lid: L})
    print(f"learner {lid[:8]}  (run {run_dir})\n")
    for cid in sorted(L["interventions"]):
        iv = L["interventions"][cid]
        v = engine.evaluate(iv, ls, L["answers"], [], L["as_of"][cid], trace=True)
        b = ls.baseline(lid, cid, iv.delivered_at)
        print(f"concept {cid[:8]}  intervention {iv.intent} delivered {fmt_t(iv.delivered_at)}"
              f"  target mastery {iv.target_mu}")
        print(f"  baseline at delivery: Beta({b.alpha:.2f}, {b.beta:.2f})  mean {b.mean:.3f}"
              f"  90% [{b.ci90[0]:.3f}, {b.ci90[1]:.3f}]")
        phase = L["phase"]
        for j in v.answers:
            mark = "COUNTED " if j.counted else f"excluded {j.exclusion}"
            print(f"    {fmt_t(j.occurred_at)}  {phase[j.record_id]:12s} {j.item_id:6s} "
                  f"{'right' if j.credit else 'wrong'}  {mark}")
        for n, st, p, bf in v.trace:
            print(f"    after {n} counted: P {p:.3f}  BF {bf:8.3f}  -> {st}")
        print(f"  VERDICT {v.outcome.value}: {v.reason}")
        t = truth[(lid, cid)]
        print(f"  [truth, scoring side] knows at post-test: {t['known']}; learned because of "
              f"the intervention: {t['learned_due_to_intervention']}\n")


if __name__ == "__main__":
    main()
