# Blind review — coding guide (SCRUM-97)

Thank you for reviewing. You will read 30 short cases. Each case is one **simulated** learner
learning one programming concept. Because the learner is simulated, we know exactly what he
really knew at every moment ("TRUTH"). The evaluation system did not see the truth: it only saw
the learner's answers, and it produced the outputs listed under "DIMENSIONS".

Your job: for **one dimension per case** (named in the QUESTION line), decide whether the
system's output was right, and if it was wrong, which part of the system is to blame. Write your
answers in `answer_sheet.csv` (columns `label`, `layer`, and optional `notes`). Please do not
discuss the cases with the project team until you have finished — the point is an independent
judgement. Allow about 30–40 minutes.

## How to read a case

* **TRUTH** — what the simulated learner really knew (e.g. "knows at post-test: yes").
* **ANSWERS** — every test answer: when it was given (days after the lesson), whether it was
  right, whether help was shown first, the self-reported confidence (1–5), what the
  evaluator did with it (COUNTED into a dimension, or EXCLUDED with a reason, e.g. ASSISTED =
  help was shown before the answer, BEFORE_TREATMENT_END = before the lesson), and, on the
  right, the truth for that answer (did he know it then, and how the answer came about:
  KNOWS, GUESS, SLIP, MISCONCEPTION = picked the wrong option that matches a known false
  belief, HELP).
* **DIMENSIONS** — each system output next to the truth it is judged against.

## Labels

| label | use it when |
|---|---|
| CORRECT | the output says what the truth says |
| WRONG | the output makes a claim the truth contradicts (e.g. says "not yet demonstrated" while the learner knew it) |
| UNCERTAIN | the system did not commit: INSUFFICIENT_EVIDENCE / NO_SELF_REPORT, **or** it made a weaker claim that is still true (e.g. "DEMONSTRATED" when the truth is "demonstrated and retained") |

## Layers (only for WRONG)

| layer | the failure comes from… | example (not from your cases) |
|---|---|---|
| INPUT_DATA | the data the system received: a record was wrong or a needed field was missing | help was shown but not recorded; a confidence rating the measure needed was not reported (even one missing rating counts here) |
| ADAPTATION_DECISION | when or whether a check was scheduled | the system judged "not retained" from a retention test that was scheduled at the wrong moment |
| INTERACTION | the learner behaved outside the system's model of a learner | he forgot within a day, faster than the system assumes, so one test window mixed "knew" and "forgot" answers; or his errors came from a firm false belief rather than random slips |
| INFERENCE | the system's rule: the data were right and the learner behaved as the model assumes, but the rule decided wrongly on that evidence | three lucky guesses in a row were enough for "demonstrated" |

If two layers seem to apply, choose the one that comes **first** in the order of the table
(input data, adaptation decision, interaction, inference) — and write the
other one in `notes`.

## Notes

* The cases were chosen so that every label occurs; judge each case on its own.
* Disagreeing with the system is a useful result, not a mistake. If a case is unclear,
  say so in `notes`.
