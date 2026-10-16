#!/bin/bash
# SCRUM-90 validation gate - one entry point.
#   ./scrum90.sh test          unit tests of the gate rules (free, no Neo4j needed)
#   ./scrum90.sh gate PID [--apply]   run the whole gate on a stored proposal (one or two Opus
#                              calls); read-only unless --apply writes the decision
#   ./scrum90.sh ids           give the loaded graph its UUID concept ids, once (free, safe to repeat)
#   ./scrum90.sh calibrate     test layer 2 on the 541 judged SCRUM-89 placements (free)
#   ./scrum90.sh calibrate-wd  test layer 3 (Wikidata) on the same pairs (free, network, ~10 min)
#   ./scrum90.sh testset       build the test set: correct, wrong and duplicate proposals (free)
#   ./scrum90.sh calibrate-blind  test layer 4 (blind Opus validator) on the test set (a few dollars)
#   ./scrum90.sh evaluate      the whole gate on the test set (free: reuses layer-4 answers)
#   ./scrum90.sh evaluate-agent   the whole gate on the real SCRUM-89 agent proposals (~2 dollars)
#   ./scrum90.sh prereq-eval   prerequisite links on LectureBank (network, ~1-2 dollars)
#   ./scrum90.sh add           place the Master theorem (not in the graph) from a Hebrew conversation,
#                              with prerequisites, and store it as a proposal (cents)
#   ./scrum90.sh teacher ...   queue | accept PID --parent CID [--links all] | reject PID |
#                              audit | confirm CID | flag CID
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
PY="$HERE/.venv/bin/python"
DEMO_TEXT="סטודנט: בהרצאה על אלגוריתמי הפרד ומשול למדנו את משפט המאסטר, שנותן את זמן הריצה של נוסחת נסיגה כמו T(n)=2T(n/2)+n. לא הבנתי איך יודעים באיזה מהמקרים אנחנו נמצאים. אתה יכול להסביר?"

need_neo4j() {
  if ! docker ps --format '{{.Names}}' | grep -qx ali-kg; then
    echo "Neo4j container ali-kg is not running - start it with ./start-neo4j.sh"; exit 1
  fi
}

case "$1" in
  test) "$PY" -m pytest tests/test_validation_*.py -q ;;
  gate) need_neo4j; "$PY" -m validation.gate "${@:2}" ;;
  ids)  need_neo4j; "$PY" -m placement.assign_concept_ids ;;
  calibrate) need_neo4j; "$PY" -m validation.calibrate_semantic ;;
  calibrate-wd) need_neo4j; "$PY" -m validation.calibrate_external ;;
  testset) need_neo4j; "$PY" -m validation.testset ;;
  calibrate-blind) need_neo4j; "$PY" -m validation.calibrate_blind ;;
  evaluate) need_neo4j; "$PY" -m validation.evaluate_gate --set testset ;;
  evaluate-agent) need_neo4j; "$PY" -m validation.evaluate_gate --set agent ;;
  prereq-eval) need_neo4j; "$PY" -m validation.prereq_eval ;;
  add) need_neo4j; "$PY" -m placement.place --text "$DEMO_TEXT" ;;
  teacher) need_neo4j; "$PY" -m validation.teacher "${@:2}" ;;
  *) sed -n 2,17p "$0"; exit 1 ;;
esac
