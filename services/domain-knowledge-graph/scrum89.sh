#!/bin/bash
# SCRUM-89 concept placement - one entry point.
#   ./scrum89.sh setup        install deps, build the vector index, run smoke tests (free)
#   ./scrum89.sh demo         place Tail recursion from a Hebrew conversation, dry run (~1 cent)
#   ./scrum89.sh add          same, and write it to the graph as a proposal
#   ./scrum89.sh eval-quick   hide-and-replace on 8 concepts, all methods (a few cents)
#   ./scrum89.sh eval         hide-and-replace on 200 concepts, all methods (a few dollars)
#   ./scrum89.sh baseline     hide-and-replace on 200 concepts, baseline only (free)
#   ./scrum89.sh judge RUN LLMRUN   blind Opus judge over an eval run (a few dollars)
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
PY="$HERE/.venv/bin/python"

need_neo4j() {
  if ! docker ps --format '{{.Names}}' | grep -qx ali-kg; then
    echo "Neo4j container ali-kg is not running - start it with ./start-neo4j.sh"; exit 1
  fi
}

DEMO_TEXT="סטודנט: היום בהרצאה דיברו על רקורסיית זנב, שבה הקריאה הרקורסיבית היא הפעולה האחרונה בפונקציה, ואמרו שהקומפיילר יכול להפוך אותה ללולאה. לא הבנתי למה זה חוסך זיכרון. אתה יכול להסביר?"

case "$1" in
  setup)
    need_neo4j
    [ -x "$PY" ] || python3 -m venv .venv
    .venv/bin/pip install -q -r requirements.txt
    "$PY" -m placement.build_index
    "$PY" -m pytest tests -q
    ;;
  demo)  need_neo4j; "$PY" -m placement.place --dry-run --text "$DEMO_TEXT" ;;
  add)   need_neo4j; "$PY" -m placement.place --text "$DEMO_TEXT" ;;
  eval-quick) need_neo4j; "$PY" -m placement.evaluate --n-per-level 2 --methods baseline,agent,llm_only ;;
  eval)       need_neo4j; "$PY" -m placement.evaluate --methods baseline,agent,llm_only ;;
  baseline)   need_neo4j; "$PY" -m placement.evaluate --methods baseline ;;
  judge)      need_neo4j; "$PY" -m placement.judge --run "$2" --llm-only-run "$3" ;;
  *) sed -n 2,9p "$0"; exit 1 ;;
esac
