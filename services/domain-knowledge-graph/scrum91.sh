#!/bin/bash
# SCRUM-91 Course Material Graph - one entry point.
#   ./scrum91.sh setup        install deps, download the two sample courses, run the tests (free)
#   ./scrum91.sh offline      build both sample graphs with no LLM: lexical baseline (free)
#   ./scrum91.sh enlp         CREATE MATERIAL GRAPH for the English NLP course (Claude, ~2-4 dollars)
#   ./scrum91.sh hebrew       CREATE MATERIAL GRAPH for the Hebrew data-structures course (Claude)
#   ./scrum91.sh eval RUN_DIR [--judge]   validate a run against its gold file (--judge: Opus, ~1 dollar)
#   ./scrum91.sh show ID | export ID | list
#   ./scrum91.sh q ID order | q ID unit N | q ID concept NAME | q ID prior
#   ./scrum91.sh test         unit tests only (no Neo4j, no API key)
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
PY="$HERE/.venv/bin/python"
ENLP="--source materials/schneider-enlp-2018 --titles material/samples/schneider-enlp-2018.tsv"
ENLP_TITLE="ENLP - Georgetown COSC-572 (Nathan Schneider, 2018)"
HEB="--source materials/hebrew-ds-wikibooks.json"

need_neo4j() {
  if ! (echo > /dev/tcp/127.0.0.1/7687) 2>/dev/null; then
    echo "Neo4j is not reachable on localhost:7687."
    echo "Start Docker Desktop, then run ./start-neo4j.sh and try again."
    exit 1
  fi
}

gold_for() {
  case "$1" in
    *schneider*) echo "$ENLP --gold material/samples/gold-schneider-enlp-2018.tsv" ;;
    *hebrew*) echo "$HEB --gold material/samples/gold-hebrew-ds-wikibooks.tsv" ;;
    *) echo "cannot tell which course $1 is" >&2; exit 1 ;;
  esac
}

case "$1" in
  setup)
    [ -x "$PY" ] || python3 -m venv .venv
    .venv/bin/pip install -q -r requirements.txt
    "$PY" -m material.samples.fetch_samples
    "$PY" -m pytest tests -q ;;
  test) "$PY" -m pytest tests/test_material.py -q ;;
  offline)
    need_neo4j
    "$PY" -m material.create create $ENLP --title "$ENLP_TITLE" --no-llm
    "$PY" -m material.create create $HEB --no-llm ;;
  enlp) need_neo4j; "$PY" -m material.create create $ENLP --title "$ENLP_TITLE" "${@:2}" ;;
  hebrew) need_neo4j; "$PY" -m material.create create $HEB "${@:2}" ;;
  eval) need_neo4j; "$PY" -m material.evaluate "$2" $(gold_for "$2") "${@:3}" ;;
  show|export) need_neo4j; "$PY" -m material.create "$1" "$2" ;;
  list) need_neo4j; "$PY" -m material.create list ;;
  q) need_neo4j; "$PY" -m material.queries "${@:2}" ;;
  *) sed -n 2,11p "$0"; exit 1 ;;
esac
