#!/bin/bash
# SCRUM-92 Learner Graph - one entry point.
#   ./scrum92.sh setup          install deps, start Postgres, create the schema, run the tests
#   ./scrum92.sh test           tests (Postgres needed; Neo4j for the projection tests)
#   ./scrum92.sh stress [N]     N random requests (default 3000) checked against a model
#   ./scrum92.sh demo           the SCRUM-92 example on the real graph: send the demo requests
#   ./scrum92.sh project        apply pending changes to the Neo4j view
#   ./scrum92.sh show [LEARNER] the learner graph (default: the demo learner)
#   ./scrum92.sh log LEARNER    every request for the learner, from the Postgres log
#   ./scrum92.sh audit [N]      last N attempts, rejected ones included
#   ./scrum92.sh resolve        concepts missing from the graph -> SCRUM-89/90 (Claude, cents)
#   ./scrum92.sh verify [LEARNER]   view equals log?
#   ./scrum92.sh rebuild [LEARNER]  drop the view and rebuild it from the log
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
PY="$HERE/.venv/bin/python"
CLI="$PY -m learner_graph.cli"

need_neo4j() {
  if ! (echo > /dev/tcp/127.0.0.1/7687) 2>/dev/null; then
    echo "Neo4j is not reachable on localhost:7687."
    echo "Start Docker Desktop, then run ./start-neo4j.sh and try again."
    exit 1
  fi
}
need_pg() {
  if ! (echo > /dev/tcp/127.0.0.1/5433) 2>/dev/null; then
    echo "Postgres is not reachable on localhost:5433. Run ./start-postgres.sh first."
    exit 1
  fi
}

case "$1" in
  setup)
    [ -x "$PY" ] || python3 -m venv .venv
    .venv/bin/pip install -q -r requirements.txt
    ./start-postgres.sh
    $CLI init
    "$PY" -m pytest tests/test_learner_graph.py -q ;;
  test) need_pg; "$PY" -m pytest tests/test_learner_graph.py -q ;;
  stress) need_pg; need_neo4j
    LG_STRESS="${2:-3000}" "$PY" -m pytest tests/test_learner_graph.py -q -s -k random_sequences \
      | grep -E "STRESS|passed|failed" ;;
  demo) need_pg; need_neo4j; $CLI init >/dev/null; $CLI demo ;;
  project|resolve|show|verify|rebuild) need_pg; need_neo4j; $CLI "$@" ;;
  log|audit) need_pg; $CLI "$@" ;;
  *) sed -n 2,14p "$0"; exit 1 ;;
esac
