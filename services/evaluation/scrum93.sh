#!/bin/bash
# SCRUM-93 learner simulator - one entry point.
#   ./scrum93.sh setup              create .venv and install pytest
#   ./scrum93.sh test               the validation tests
#   ./scrum93.sh run [SEED] [N]     simulate N learners per population (default seed 93, N 200)
#                                   -> runs/seed-SEED/{answers.jsonl, truth.jsonl, items.json, manifest.json}
#   ./scrum93.sh score [SEED]       run the naive rules on answers.jsonl only, then score them
#                                   against truth.jsonl -> runs/seed-SEED/{decisions.jsonl, score.json, score.md}
#   ./scrum93.sh repro [SEED] [N]   run twice into two folders and compare the files byte for byte
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
PY="$HERE/.venv/bin/python"
[ -x "$PY" ] || PY="python3"
SEED="${2:-93}"
N="${3:-200}"

case "$1" in
  setup)
    python3 -m venv .venv
    .venv/bin/pip install -q -r requirements.txt
    .venv/bin/python -m pytest tests -q ;;
  test) "$PY" -m pytest tests -q ;;
  run) "$PY" -m simulator --seed "$SEED" --n "$N" --out "runs/seed-$SEED" ;;
  score)
    [ -f "runs/seed-$SEED/answers.jsonl" ] || { echo "No run for seed $SEED. Run ./scrum93.sh run $SEED first."; exit 1; }
    "$PY" -m harness.rules "runs/seed-$SEED" >/dev/null
    "$PY" -m harness.score "runs/seed-$SEED" ;;
  repro)
    "$PY" -m simulator --seed "$SEED" --n "$N" --out "runs/repro-a" >/dev/null
    "$PY" -m simulator --seed "$SEED" --n "$N" --out "runs/repro-b" >/dev/null
    for f in answers.jsonl truth.jsonl items.json manifest.json; do
      cmp -s "runs/repro-a/$f" "runs/repro-b/$f" && echo "identical  $f" || { echo "DIFFERENT  $f"; exit 1; }
    done ;;
  *) sed -n 2,10p "$0"; exit 1 ;;
esac
