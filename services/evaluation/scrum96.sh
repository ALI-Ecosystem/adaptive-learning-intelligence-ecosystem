#!/bin/bash
# SCRUM-96 retention, transfer and error-repetition checks - one entry point.
#   ./scrum96.sh test          all tests (SCRUM-93 + 94 + 95 + 96)
#   ./scrum96.sh data [N]      calibration run (seed 9600, 16-item post-test, transfer bank)
#                              + calibration, and the SCRUM-96 run (seed 96, N learners per
#                              population, 9 populations) -> runs/seed-96
#   ./scrum96.sh validate      outcomes, coverage, baselines, variants -> runs/scrum96/results.md
#   ./scrum96.sh all [N]       data, validate
#   ./scrum96.sh regress       the defaults still give the SCRUM-93 and SCRUM-95 files
#   ./scrum96.sh repro         validate twice into two folders, compare byte for byte
#   ./scrum96.sh example       one case followed version by version
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
PY="$HERE/.venv/bin/python"
[ -x "$PY" ] || PY="python3"
N="${2:-200}"

data() {
  "$PY" -m simulator --scrum96 --seed 9600 --n "$N" --post-items 16 --bank 40 --out runs/calib-9600
  "$PY" -m harness.calibrate runs/calib-9600 runs/calib-9600/calibration.json
  "$PY" -m simulator --scrum96 --seed 96 --n "$N" --out runs/seed-96
}

case "$1" in
  test) "$PY" -m pytest tests -q ;;
  data) data ;;
  validate) "$PY" -m harness.validate96 --run runs/seed-96 --calib runs/calib-9600 --out runs/scrum96 ;;
  all) data; "$PY" -m harness.validate96 --run runs/seed-96 --calib runs/calib-9600 --out runs/scrum96 ;;
  regress) "$PY" -m pytest tests/test_simulator96.py -q -k byte_identical ;;
  repro)
    "$PY" -m harness.validate96 --out runs/scrum96-a >/dev/null
    "$PY" -m harness.validate96 --out runs/scrum96-b >/dev/null
    for f in results.json results.md cases.jsonl; do
      cmp -s "runs/scrum96-a/$f" "runs/scrum96-b/$f" && echo "identical  $f" || { echo "DIFFERENT  $f"; exit 1; }
    done ;;
  example) "$PY" -m harness.example96 ;;
  *) sed -n 2,11p "$0"; exit 1 ;;
esac
