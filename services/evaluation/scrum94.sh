#!/bin/bash
# SCRUM-94 intervention verdict - one entry point.
#   ./scrum94.sh test              all tests (SCRUM-93 + SCRUM-94)
#   ./scrum94.sh data [N]          calibration run (seed 9400) + calibration, the SCRUM-93 run
#                                  (seed 93, unchanged) and the same learners with longer
#                                  post-tests (5, 8, 12, 16 items) - N learners per population
#   ./scrum94.sh validate          verdicts + baselines + experiments -> runs/scrum94/results.md
#   ./scrum94.sh all [N]           data, validate
#   ./scrum94.sh repro             validate twice into two folders, compare results byte for byte
#   ./scrum94.sh example           one verdict, explained
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
PY="$HERE/.venv/bin/python"
[ -x "$PY" ] || PY="python3"
N="${2:-200}"

data() {
  "$PY" -m simulator --seed 9400 --n "$N" --post-items 16 --bank 26 --out runs/calib-9400
  "$PY" -m harness.calibrate runs/calib-9400 runs/calib-9400/calibration.json
  "$PY" -m simulator --seed 93 --n "$N" --out runs/seed-93
  for L in 5 8 12 16; do
    B=$(( L + 10 > 20 ? L + 10 : 20 ))
    "$PY" -m simulator --seed 93 --n "$N" --post-items "$L" --bank "$B" --out "runs/seed-93-L$L"
  done
}

case "$1" in
  test) "$PY" -m pytest tests -q ;;
  data) data ;;
  validate) "$PY" -m harness.validate94 --runs runs --out runs/scrum94 ;;
  all) data; "$PY" -m harness.validate94 --runs runs --out runs/scrum94 ;;
  repro)
    "$PY" -m harness.validate94 --runs runs --out runs/scrum94-a >/dev/null
    "$PY" -m harness.validate94 --runs runs --out runs/scrum94-b >/dev/null
    for f in results.json results.md cases_L3.jsonl; do
      cmp -s "runs/scrum94-a/$f" "runs/scrum94-b/$f" && echo "identical  $f" || { echo "DIFFERENT  $f"; exit 1; }
    done ;;
  example) "$PY" -m harness.example94 ;;
  *) sed -n 2,10p "$0"; exit 1 ;;
esac
