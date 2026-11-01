#!/bin/bash
# SCRUM-97 case analysis log - one entry point.
#   ./scrum97.sh test          all tests (SCRUM-93 ... 97)
#   ./scrum97.sh data          the runs the SCRUM-94/95/96 reports used (skips a run that exists)
#   ./scrum97.sh log           build, select, render and check the cases -> runs/scrum97
#   ./scrum97.sh all           data, log
#   ./scrum97.sh repro         the log twice into two folders, compared byte for byte
#   ./scrum97.sh agree SHEET   agreement of a filled review answer sheet with the key
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
PY="$HERE/.venv/bin/python"
[ -x "$PY" ] || PY="python3"

data() {
  [ -f runs/calib-9400/calibration.json ] || {
    "$PY" -m simulator --seed 9400 --n 200 --post-items 16 --bank 26 --out runs/calib-9400
    "$PY" -m harness.calibrate runs/calib-9400 runs/calib-9400/calibration.json; }
  [ -f runs/seed-93-L8/answers.jsonl ] || \
    "$PY" -m simulator --seed 93 --n 200 --post-items 8 --bank 20 --out runs/seed-93-L8
  [ -f runs/calib-9500/calibration.json ] || {
    "$PY" -m simulator --seed 9500 --n 200 --post-items 16 --bank 48 --out runs/calib-9500
    "$PY" -m harness.calibrate runs/calib-9500 runs/calib-9500/calibration.json; }
  [ -f runs/confnorm-9510/norm.json ] || {
    "$PY" -m simulator --scrum95 --seed 9510 --n 200 --out runs/confnorm-9510
    "$PY" -m gap.confnorm runs/confnorm-9510 runs/confnorm-9510/norm.json; }
  [ -f runs/confnorm-9511-clean/norm.json ] || {
    "$PY" -m simulator --scrum95 --seed 9511 --n 200 --never-report 0 --report-prob 1,1,1,1,1 \
      --exclude CONFIDENT_WRONG,HELP_INFLATED --out runs/confnorm-9511-clean
    "$PY" -m gap.confnorm runs/confnorm-9511-clean runs/confnorm-9511-clean/norm.json; }
  [ -f runs/seed-95/answers.jsonl ] || "$PY" -m simulator --scrum95 --seed 95 --n 200 --out runs/seed-95
  [ -f runs/calib-9600/calibration.json ] || {
    "$PY" -m simulator --scrum96 --seed 9600 --n 200 --post-items 16 --bank 40 --out runs/calib-9600
    "$PY" -m harness.calibrate runs/calib-9600 runs/calib-9600/calibration.json; }
  [ -f runs/seed-96/answers.jsonl ] || "$PY" -m simulator --scrum96 --seed 96 --n 200 --out runs/seed-96
}

case "$1" in
  test) "$PY" -m pytest tests -q ;;
  data) data ;;
  log) "$PY" -m harness.case97 --out runs/scrum97 ;;
  all) data; "$PY" -m harness.case97 --out runs/scrum97 ;;
  repro)
    "$PY" -m harness.case97 --out runs/scrum97-a >/dev/null
    "$PY" -m harness.case97 --out runs/scrum97-b >/dev/null
    for f in cases.txt cases.jsonl all_labels.jsonl summary.json summary.md check.json manifest.json \
             review/review_cases.txt review/answer_sheet.csv review_key/key.json; do
      cmp -s "runs/scrum97-a/$f" "runs/scrum97-b/$f" && echo "identical  $f" || { echo "DIFFERENT  $f"; exit 1; }
    done ;;
  agree) "$PY" -m harness.review97 --sheet "$2" --key runs/scrum97/review_key/key.json \
           --out runs/scrum97/review_agreement ;;
  *) sed -n 2,8p "$0"; exit 1 ;;
esac
