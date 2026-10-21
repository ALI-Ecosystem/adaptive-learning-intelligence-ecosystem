"""SCRUM-93 learner simulator: simulated learners with a known ground truth.

The simulator is a source of behaviour and truth only. It does not evaluate, diagnose,
estimate mastery or choose interventions (SCRUM-93 ownership boundary). Everything it
produces is a simulation result.

Modules:
  draws        reproducible random numbers keyed by event (common random numbers)
  concepts     the three Domain Knowledge Graph concepts and their misconceptions
  items        the multiple-choice item bank (one correct option, three distractors,
               each distractor mapped to one misconception - Li et al. 2025)
  populations  the seven populations and their parameters
  learner      the true state of one learner and how it changes
  generator    the fixed timeline with per-learner gaps; the learner and its twin
  records      writes answers, truth, items and a manifest as separate files
"""
