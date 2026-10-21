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
