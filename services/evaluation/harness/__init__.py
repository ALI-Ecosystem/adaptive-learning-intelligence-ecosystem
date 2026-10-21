"""SCRUM-93 scoring harness.

rules.py reads ONLY answers.jsonl and decides, per learner and concept, "learned or not"
with deliberately naive rules. score.py then compares those decisions with truth.jsonl.
The two steps are separate modules and files so a rule can never see the truth.
"""
