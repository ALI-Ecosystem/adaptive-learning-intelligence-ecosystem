#!/bin/bash
# SCRUM-95 perceived-versus-demonstrated gap - one entry point.
#   ./scrum95.sh test          all tests (SCRUM-93 + SCRUM-94 + SCRUM-95)
#   ./scrum95.sh data [N]      the SCRUM-95 simulator run (seed 95, N learners per population,
#                              10 populations, 3 rounds) -> runs/seed-95
#   ./scrum95.sh regress       seed 93 with the defaults must still give the SCRUM-93 hashes
#   ./scrum95.sh validate      assisted gap -> runs/scrum95/results.md,
#                              confidence gap -> runs/scrum95/results_confidence.md
#   ./scrum95.sh all [N]       data, validate
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
PY="$HERE/.venv/bin/python"
[ -x "$PY" ] || PY="python3"
N="${2:-200}"

case "$1" in
  test) "$PY" -m pytest tests -q ;;
  data)
    "$PY" -m simulator --seed 9500 --n "$N" --post-items 16 --bank 48 --out runs/calib-9500
    "$PY" -m harness.calibrate runs/calib-9500 runs/calib-9500/calibration.json
    "$PY" -m simulator --scrum95 --seed 9510 --n "$N" --out runs/confnorm-9510
    "$PY" -m gap.confnorm runs/confnorm-9510 runs/confnorm-9510/norm.json
    "$PY" -m simulator --scrum95 --seed 9511 --n "$N" --never-report 0 --report-prob 1,1,1,1,1 \
      --exclude CONFIDENT_WRONG,HELP_INFLATED --out runs/confnorm-9511-clean
    "$PY" -m gap.confnorm runs/confnorm-9511-clean runs/confnorm-9511-clean/norm.json
    "$PY" -m simulator --scrum95 --seed 95 --n "$N" --out runs/seed-95 ;;
  validate)
    rm -f runs/scrum95/inputs.pkl
    "$PY" -m harness.validate95 --run runs/seed-95 --calib runs/calib-9500 --out runs/scrum95
    "$PY" -m harness.validate95c --run runs/seed-95 --calib runs/calib-9500 --out runs/scrum95 ;;
  all) "$0" data "$N" && "$0" validate ;;
  regress)
    "$PY" -m simulator --seed 93 --n 200 --out runs/regress-93 >/dev/null
    "$PY" - <<'PYEOF'
import json
m = json.load(open("runs/regress-93/manifest.json"))["sha256"]
ok = m["answers.jsonl"].startswith("9a5c0a8cad24d389") and m["truth.jsonl"].startswith("eaf57bdcbdfb8d0f")
print("identical to SCRUM-93" if ok else "DIFFERENT from SCRUM-93")
raise SystemExit(0 if ok else 1)
PYEOF
    ;;
  *) sed -n 2,9p "$0"; exit 1 ;;
esac
