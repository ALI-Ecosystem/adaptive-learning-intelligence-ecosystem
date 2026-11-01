"""SCRUM-97 case analysis log - the PRE-REGISTERED part.

Everything in this file was fixed before any case was generated or any result looked at:
the case format, the label rules, the selection rule and the failure-attribution chain.
The log records this file's SHA-256 in manifest.json, so a later change to it is visible.

Decisions (2026-11-01, with Kody):
  1  runs        the SCRUM-94, 95 and 96 runs stay separate (the cases explain the rates the
                 reports published); a stage that did not run in a case's run is shown as
                 NOT_RUN_IN_THIS_RUN. The SCRUM-96 table row ILLUSION_SUSPECTED needs SCRUM-95
                 input, so its cells are reported empty, with that reason.
  2  truth       the verdict, retention and transfer are judged against "knows now" (the
                 state when the test began); "learned because of the intervention" is shown,
                 never used for a label. Each dimension uses its own mission's truth.
  3  labels      one label per dimension + one overall label, precedence WRONG > UNCERTAIN
                 > CORRECT (dimensions that observed nothing take no part).
  4  layers      fixed precedence chain over recorded facts (input data -> adaptation
                 timing -> interaction -> inference); a counterfactual replay on the
                 selected wrong dimensions is a robustness check only. Every wrong
                 dimension has a layer AND a points_to (the rule it points to).
  5  review      one external blind reviewer, 30 cases, coding guide, % agreement + kappa.

The component is a reporting tool: it never changes a rule, a verdict or a threshold. It
calls the SCRUM-94/95/96 code exactly as their validations do.

Revision R2 (after the independent review of this code, before the report): a wrong OUTCOME
inherits a layer only from a wrong sub-dimension behind its FALSE claim (CLAIM_DIMS), else it
is attributed on that claim's answers; ERROR_REPETITION reads (and counts) only the records of
the misconception(s) that decided its status; ACQUISITION is NOT_SCORABLE when it pooled
delayed answers (before t_R) and the truth changed between the two tests - the definition
already used for TRANSFER. The consistency check was made able to fail on every field shown.

Revision R1 (after the first run of the R96 labels, BEFORE any case was selected or read;
only aggregate counts had been seen). Two rules of THIS file were wrong, not the SCRUM-96 code:
  a. OUTCOME was labelled by exact equality with the true outcome, so "DEMONSTRATED" for a
     learner who truly retained it counted as WRONG (426 such in R96). The outcome table falls back
     to a weaker claim when a check is undecided; a weaker claim that is TRUE is incomplete,
     not false. Now: equal -> CORRECT; every atomic claim of the output true -> UNCERTAIN
     (INCOMPLETE); any atomic claim false -> WRONG (OUTCOME_CLAIMS below).
  b. "retention check resolved late -> ADAPTATION" fired for 332 wrong outcomes whatever was
     wrong. In the simulation the truth is taken when the check BEGINS, so a late check can
     only measure a later state, never make a claim false. ADAPTATION now requires that the
     ALE stand-in withheld the check the false claim is about; this cannot happen with the
     present truth (a withheld check gives no retention claim), and the layer is reported
     empty with that reason. A wrong OUTCOME inherits the layer of its wrong sub-dimension.
"""

FORMAT = "ali.eval.case/v1"
POLICY = "eval-caselog/0.1 (SCRUM-97)"

# ---- labels ------------------------------------------------------------------------------------
CORRECT, WRONG, UNCERTAIN = "CORRECT", "WRONG", "UNCERTAIN"
NOT_OBSERVED = "NOT_OBSERVED"     # the dimension had no answer: a coverage gap, not a claim
NOT_SCORABLE = "NOT_SCORABLE"     # the truth itself changed inside the pooled window
LABELS = (CORRECT, WRONG, UNCERTAIN)
PRECEDENCE = (WRONG, UNCERTAIN, CORRECT)
NOT_RUN = "NOT_RUN_IN_THIS_RUN"
NOT_BUILT = "NOT_BUILT_YET"

# ---- dimension families: the outputs each can give (the cells exist even when empty) -----------
YES_NO_INS = {
    "VERDICT": ("DEMONSTRATED", "NOT_YET_DEMONSTRATED", "INSUFFICIENT_EVIDENCE"),
    "ASSISTED_GAP": ("CREDIBLE_GAP", "NO_CREDIBLE_GAP", "INSUFFICIENT_EVIDENCE"),
    "ASSISTED_REDUCTION": ("REDUCED", "NOT_REDUCED", "INSUFFICIENT_EVIDENCE"),
    "CONFIDENCE_REDUCTION": ("REDUCED", "NOT_REDUCED", "INSUFFICIENT_EVIDENCE"),
    "ACQUISITION": ("SUPPORTED", "NOT_SUPPORTED", "INSUFFICIENT"),
    "RETENTION": ("SUPPORTED", "NOT_SUPPORTED", "INSUFFICIENT"),
    "TRANSFER": ("SUPPORTED", "NOT_SUPPORTED", "INSUFFICIENT"),
    "ERROR_REPETITION": ("SUPPORTED", "NOT_SUPPORTED", "INSUFFICIENT"),
}
VOCAB = dict(YES_NO_INS)
VOCAB["CONFIDENCE_GAP"] = ("PERCEIVED_ABOVE", "PERCEIVED_BELOW", "NO_CREDIBLE_GAP",
                           "INSUFFICIENT_EVIDENCE", "NO_SELF_REPORT")
VOCAB["OUTCOME"] = ("NOT_EVALUABLE", "ILLUSION_SUSPECTED", "NOT_YET_DEMONSTRATED",
                    "NOT_RETAINED", "MISCONCEPTION_PERSISTS", "SHALLOW",
                    "DEMONSTRATED_RETAINED", "DEMONSTRATED", "INSUFFICIENT_EVIDENCE")
UNCERTAIN_OUTPUTS = {"INSUFFICIENT_EVIDENCE", "INSUFFICIENT", "NOT_EVALUABLE", "NO_SELF_REPORT"}
OUTCOME_CLAIMS = {   # R1a: what each SCRUM-96 outcome asserts about the learner
    "NOT_YET_DEMONSTRATED": ("not_shown",),
    "NOT_RETAINED": ("shown", "lost"),
    "MISCONCEPTION_PERSISTS": ("shown", "misconception"),
    "SHALLOW": ("shown", "pattern"),
    "DEMONSTRATED_RETAINED": ("shown", "retained"),
    "DEMONSTRATED": ("shown",),
    "ILLUSION_SUSPECTED": ("not_shown",),
}
INCOMPLETE = "INCOMPLETE"   # reason of an UNCERTAIN outcome: a weaker claim that is true
CLAIM_DIMS = {      # the dimensions behind each claim: a wrong OUTCOME inherits only from these
    "not_shown": ("ACQUISITION", "RETENTION"), "shown": ("ACQUISITION", "RETENTION"),
    "lost": ("ACQUISITION", "RETENTION"), "retained": ("RETENTION",),
    "misconception": ("ERROR_REPETITION",), "pattern": ("TRANSFER",),
}
CLAIM_WINDOWS = {   # the answers behind each claim: a wrong OUTCOME is attributed on these only
    "not_shown": ("ACQUISITION", "RETENTION"), "shown": ("ACQUISITION", "RETENTION"),
    "lost": ("ACQUISITION", "RETENTION"), "retained": ("RETENTION",),
    "misconception": ("ACQUISITION", "RETENTION"), "pattern": ("TRANSFER",),
}

FAMILIES = {   # run -> families, in chain order (truth -> verdict -> 96 -> 95 -> outcome)
    "R94": ("VERDICT",),
    "R95": ("VERDICT", "ASSISTED_GAP", "ASSISTED_REDUCTION", "CONFIDENCE_GAP",
            "CONFIDENCE_REDUCTION"),
    "R96": ("ACQUISITION", "RETENTION", "TRANSFER", "ERROR_REPETITION", "OUTCOME"),
}
EMPTY_BY_DESIGN = {   # (run, family, output) -> why the cell can never be filled in this run
    ("R96", "OUTCOME", "ILLUSION_SUSPECTED"):
        "needs the SCRUM-95 perceived input; the runs are separate (decision 1)",
    ("R96", "OUTCOME", "NOT_EVALUABLE"):
        "the Learner State stand-in always has a baseline",
    ("R96", "ERROR_REPETITION", "NOT_SUPPORTED"):
        "with the state prior (SCRUM-96 decision 3d) about 33 clean answers are needed to "
        "declare a misconception repaired and about 12 are available (SCRUM-96 limitation)",
}

# ---- runs (the runs the published reports used) ------------------------------------------------
RUNS = {
    "R94": {"mission": "SCRUM-94", "run": "runs/seed-93-L8", "calib": "runs/calib-9400",
            "seed": 93, "note": "the 8-item post-test run of the SCRUM-94 main result"},
    "R95": {"mission": "SCRUM-95", "run": "runs/seed-95", "calib": "runs/calib-9500",
            "norm": "runs/confnorm-9510/norm.json",
            "clean_norm": "runs/confnorm-9511-clean/norm.json", "seed": 95,
            "note": "3 rounds; assisted items; confidence missing not at random"},
    "R96": {"mission": "SCRUM-96", "run": "runs/seed-96", "calib": "runs/calib-9600",
            "seed": 96, "note": "delayed test, transfer bank, ALE stand-in (20% never checked)"},
}

# ---- selection rule (fixed before the results) -------------------------------------------------
SELECTION_SEED = 97
COVER_PER_CELL = 1      # S1: >= 1 case per (run, population, family, output); empty cells listed
WRONG_CAP = 5           # S2: every wrong case per (run, family, population, wrong kind), or a
                        #     fixed random sample of WRONG_CAP when there are more
UNCERTAIN_PER_CELL = 2  # S3: a sample of uncertain cases per (run, family, population)
SELECTION_RULE = (
    "S1 coverage: for every run, population, dimension family and output the family can give, "
    f"{COVER_PER_CELL} case drawn at random (seed {SELECTION_SEED}); a cell with no case is "
    "listed as empty. "
    f"S2 failures: every WRONG dimension of each (run, family, population, wrong kind), or a "
    f"fixed random sample of {WRONG_CAP} when there are more (the count of all is reported). "
    f"S3 uncertainty: {UNCERTAIN_PER_CELL} UNCERTAIN dimensions per (run, family, "
    "population). A case picked by several rules appears once with every reason. Draws are "
    "keyed hashes of the case id, so they do not depend on the order of processing.")

# ---- failure attribution (Weibelzahl's layers, Jeremic et al. 2009) ----------------------------
INPUT, ADAPTATION, INTERACTION, INFERENCE = ("INPUT_DATA", "ADAPTATION_DECISION",
                                             "INTERACTION", "INFERENCE")
LAYERS = (INPUT, INFERENCE, ADAPTATION, INTERACTION)
ATTRIBUTION_CHAIN = (
    (INPUT, "a record the dimension read disagrees with what happened (help, attempt), or a "
            "field it needs is missing (an unreported self-confidence in a round it read)"),
    (ADAPTATION, "the false claim is about a check the ALE stand-in withheld or mistimed so "
                 "that the claim rests on the wrong moment (R1: a late check measures the state "
                 "when it begins, which is also when the truth is taken, so lateness alone "
                 "never makes a claim false; a withheld check gives NOT_OBSERVED)"),
    (INTERACTION, "the learner behaved outside the evaluator's model while the dimension's "
                  "answers were collected: his true state changed inside the window (the "
                  "model assumes one level per window - e.g. a fast forgetter whose delayed "
                  "test fell before the single-half-life retention point), or a knowing "
                  "learner's errors came from a held misconception (the model treats errors "
                  "as random slips)"),
    (INFERENCE, "otherwise: the input was right and the learner stayed inside the model, and "
                "the rule decided wrongly on the evidence it had"),
)
# Out of scope until the Adaptive Learning Engine exists, kept as a category: the choice of
# activity. Here ADAPTATION_DECISION covers only the ALE stand-in's check timing (SCRUM-96).

MISSION_RULE = {   # family -> the rule a failure points to
    "VERDICT": "SCRUM-94 verdict: DEMONSTRATED iff BF >= 4 and P(mastery >= target) > 0.5 "
               "(target 0.70, prior from Learner State at delivery)",
    "ASSISTED_GAP": "SCRUM-95 assisted gap: CREDIBLE_GAP iff P(gap > 0.2) >= 0.8, raw shares",
    "ASSISTED_REDUCTION": "SCRUM-95 reduction: REDUCED iff P(gap r1 - gap r3 > 0.1) >= 0.8",
    "CONFIDENCE_GAP": "SCRUM-95 confidence gap: empirical norm, prior weight 4, "
                      "P(gap > 0.2) >= 0.8",
    "CONFIDENCE_REDUCTION": "SCRUM-95 confidence reduction: first vs last round, 0.1",
    "ACQUISITION": "SCRUM-96 acquisition window (SCRUM-94 statistic before t_R)",
    "RETENTION": "SCRUM-96 retention window (t_R = treatment end + h log2(1/0.9), "
                 "one half-life h for all learners)",
    "TRANSFER": "SCRUM-96 transfer (TRANSFER_PROBLEM answers, pooled over time)",
    "ERROR_REPETITION": "SCRUM-96 error repetition (r0 = slip/3, prior = misconception state "
                        "at delivery, shown windows only)",
    "OUTCOME": "SCRUM-96 outcome table (first match wins)",
}
LAYER_HINT = {
    INPUT: "the record producer (Evidence block / learner interface) or how the measure "
           "treats a missing field",
    ADAPTATION: "the ALE's check scheduling (SCRUM-96 coverage)",
    INTERACTION: "the evaluator's model assumption (one level per window / random slips): "
                 "needs a real Learner State (per-learner half-life, misconception state)",
    INFERENCE: "the rule's evidence threshold and the amount of evidence (test length)",
}

# ---- blind review ------------------------------------------------------------------------------
REVIEW_SEED = 9797
REVIEW_STRATA = ((WRONG, 10), (UNCERTAIN, 10), (CORRECT, 10))
