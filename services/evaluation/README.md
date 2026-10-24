# Evaluation / Validation System

## SCRUM-93 — learner simulator with known ground truth

Simulated learners whose true knowledge is known, so later Evaluation components can be
checked against the truth. The simulator produces behaviour and keeps the truth. It does
not evaluate, diagnose, estimate mastery or choose interventions. **Every number it
produces is a simulation result**: simulated learners can validate components, but they
cannot replace a study with real learners (Greer & Mark 2016).

```
./scrum93.sh setup            # .venv + pytest, then the tests
./scrum93.sh test             # validation tests
./scrum93.sh run 93 200       # 200 learners per population, seed 93 -> runs/seed-93/
./scrum93.sh score 93         # naive rules on answers only, scored against the truth
./scrum93.sh repro 93 50      # two runs, byte-for-byte comparison
```

Only the Python standard library is used (pytest for the tests).

### Model

Discrete state per (learner, concept) in the style of BKT (Corbett & Anderson 1995):
knows / does not know, with prior knowledge, learning per answered item, slip, and a
1-in-4 guess. Added: power-law forgetting, an intervention (one immediate chance to learn
plus a higher learning rate afterwards), misconceptions held independently of knowing,
help that only raises correctness, and calibrated self-confidence with a per-learner bias.

The generator deliberately differs from the evaluator's model (evaluation architecture
§3.4: a continuous ability on a logistic curve with item difficulty, exponential decay
from Learner State's half-life). See the SCRUM-93 report for the full comparison.

Only PRACTICE items are learning opportunities; test items give no feedback, so they
neither teach nor reset the forgetting clock.

Every learner also runs as a **twin** with the same random numbers and no intervention.
Truth "learned because of the intervention" = knows when the test begins and the twin
does not.

### Files of a run (`runs/seed-N/`, git-ignored)

| file | content | who may read it |
|---|---|---|
| `answers.jsonl` | Learner Graph update bodies (`ali.learner-graph.update/v1`, `ADD_EVIDENCE` / `ADD_EXPOSURE`), unsigned, in time order | anything under test |
| `items.json` | the item bank: options and the misconception each distractor maps to | anything under test |
| `truth.jsonl` | population, parameters, true states, twin, checkpoint labels, transitions, per-answer trace | scoring only |
| `manifest.json` | seed, sizes, SHA-256 of every file and of the simulator source | scoring only — the seed regenerates the whole truth |
| `decisions.jsonl`, `score.json`, `score.md` | naive-rule decisions and their scores | — |

### Layout

```
simulator/   draws, concepts, items, populations, learner, generator, records
harness/     rules.py (answers only) -> score.py (decisions vs truth)
tests/       validation tests
```

## SCRUM-94 — intervention verdict

After a learning intervention, decides whether the learner **now demonstrates the target
unaided**: `DEMONSTRATED`, `NOT_YET_DEMONSTRATED` or `INSUFFICIENT_EVIDENCE`. It is a
measurement: it reads Learner State (at the moment of delivery), never writes it, does not
diagnose, does not choose what comes next, and claims nothing about cause.

```
./scrum94.sh test              # all tests (SCRUM-93 + SCRUM-94)
./scrum94.sh all 200           # data (calibration run, seed 93, longer post-tests) + validation
./scrum94.sh validate          # validation only -> runs/scrum94/results.md
./scrum94.sh example           # one learner's verdicts, explained
./scrum94.sh repro             # validation twice, byte-for-byte comparison
```

### Method (evaluation architecture §3.3–3.4)

* **Eligibility gate** — an answer counts only if it is on the case's tuple, applied,
  observed directly, from a known plan item, not part of the intervention, after the
  intervention and before the moment judged (and before the retention point), with no
  help before it, a first attempt, on an item not answered or shown before, not
  drift-flagged, with a difficulty. The first failing rule is recorded as the reason.
* **Prior** — from the Learner State baseline at delivery, centred on *no change*, as wide
  as Learner State's own 90% interval plus the distance its own learning model allows.
* **Decision** — against the intervention's fixed target (mastery 0.70): `DEMONSTRATED`
  needs evidence from the answers alone (Bayes factor ≥ 4) **and** belief (posterior > 0.5);
  `NOT_YET_DEMONSTRATED` the mirror; anything else is `INSUFFICIENT_EVIDENCE`.

### Layout

```
verdict/     contracts, standin (read-only Learner State interface + oracle stand-in),
             betafn (Beta in the standard library), model (prior, grid, BF), engine (gate + evaluate)
harness/     adapter94 (simulator -> verdict inputs), calibrate (item difficulty, separate run),
             baselines94 (naive rule, BKT 0.95), contaminate (injected answers),
             validate94 (all experiments), report94 (generated tables), example94
```

Simulator additions (defaults leave every SCRUM-93 file byte-identical — a test checks it):
`--post-items` (length of the immediate post-test) and `--bank` (items per concept).

## SCRUM-95 — perceived-versus-demonstrated gap

Status: **simulator extensions, assisted-gap and confidence-gap measures done and validated**; report next.

### Simulator extensions (`simulator/config.py`, three new populations)

With the defaults every SCRUM-93/94 file is byte-identical (`tests/test_simulator95.py`
checks five recorded hashes, including the seed-93 run `9a5c0a8c…`). `--scrum95` turns on:

| Decision | Extension |
|---|---|
| Q1 | 3 fixed rounds of intervention → practice → post-test, ~1 day apart, then one delayed test. Adaptive stopping is deliberately not used: it would bias the measured reduction (survivors, stopping on a lucky answer). |
| Q2 | `HELP_DEPENDENT` (asks for help often, learns a little, calibrated confidence) and `HELP_INFLATED` (same, plus help raises confidence) — each switches on one gap; the first is the control for the second. |
| Q3 | `LEARNS_FROM_HELP`: a helped **practice** item can teach (`p_T_help`). Help on test items never teaches. |
| Q4 | 2 assisted items per concept per round, **after** the unaided post-test items, added (not replacing): assisted and unaided answers at the same moment. |
| Q5 | Help raises later confidence by +1.5, halving every day since the latest help. Direction: Bassner et al. (2025), fluency read as learning; size and fading are project assumptions. |
| Q6 | Confidence missing not at random: 20% of learners never report; the rest report with probability 0.40–0.95 rising with their confidence. |

The new populations are not in `POPULATIONS` (that would reshuffle every SCRUM-93/94
learner); a SCRUM-95 run uses `ALL_POPULATIONS`.

```
./scrum95.sh test        all tests (SCRUM-93, 94, 95)
./scrum95.sh data [N]    the SCRUM-95 run -> runs/seed-95 (seed 95, N per population)
./scrum95.sh regress     re-run seed 93 with the defaults and compare with the recorded hashes
```

### Assisted-versus-unaided gap (`gap/assisted.py`, decisions M1–M3)

Per round, for one learner and concept: unaided side = the answers the SCRUM-94 gate counted
for that round's verdict; assisted side = the answers the gate excluded **only** because help
reached the learner. Both on the raw share-correct scale, each a Beta(k+1, n−k+1) posterior;
the gap is their difference (deterministic keyed draws, `gap/betadiff.py`).

* `CREDIBLE_GAP` if P(gap > 0.2) ≥ 0.8, `NO_CREDIBLE_GAP` if P(gap < 0.2) ≥ 0.8, else
  `INSUFFICIENT_EVIDENCE`. The round's verdict is reported next to the gap.
* Reduction = gap(round 1) − gap(round 3): `REDUCED` if P(> 0.1) ≥ 0.8, `NOT_REDUCED` if
  P(< 0.1) ≥ 0.8; with the change of each side and the path of round statuses.
* Output: a measurement record for Diagnosis — no label about the learner, no advice.

```
gap/         betadiff (keyed Beta draws), assisted (the measure)
harness/     adapter95 (rounds, gate split, truth for scoring), validate95, report95
```

### Perceived-versus-demonstrated gap (`gap/confidence.py`, `gap/confnorm.py`, decisions C1–C5)

* **Perceived** = mean of an empirical norm over the learner's ratings: norm[c] = share correct
  of unaided test answers rated c in a separate calibration cohort (no invented 5 → 100%).
  Main norm: all populations, missing not at random (realistic); clean norm: calibrated
  learners only (sensitivity).
* **Demonstrated** = share correct of the round's counted unaided answers that carry a rating,
  with a prior centred on *no gap* weighing 4 answers (one wrong answer never decides).
* `PERCEIVED_ABOVE` / `PERCEIVED_BELOW` / `NO_CREDIBLE_GAP` / `INSUFFICIENT_EVIDENCE`, and
  `NO_SELF_REPORT` for a learner with no rating at all. Schraw's discrimination index beside it.
* Validation truth = what actually inflated the rating (bias, help boost) on the clean-norm
  scale: a gap-to-correctness truth labelled calibrated weak learners overconfident (regression
  artifact) — the measure did not, the truth did.
