"""SCRUM-97 blind review: agreement between the reviewer's answer sheet and the system's key.

    python -m harness.review97 --sheet filled_answer_sheet.csv \
        --key runs/scrum97/review_key/key.json --out runs/scrum97/review_agreement

Reports percent agreement and Cohen's kappa for the label (all answered items) and for the
layer (items both the system and the reviewer labelled WRONG). With one reviewer there is no
agreement BETWEEN reviewers; Greer & Mark (2016) warn that experts often disagree, and that a
system better than its experts can score low agreement - the number is reported, not judged.
"""
import argparse
import json
from pathlib import Path

from caselog.log import agreement


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--key", default="runs/scrum97/review_key/key.json")
    ap.add_argument("--out", default="runs/scrum97/review_agreement")
    a = ap.parse_args()
    key = json.loads(Path(a.key).read_text(encoding="utf-8"))
    res = agreement(Path(a.sheet).read_text(encoding="utf-8"), key)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(res, indent=1, sort_keys=True) + "\n",
                                        encoding="utf-8")
    lab, lay = res["label"], res["layer_when_both_wrong"]
    L = ["# SCRUM-97 blind review - agreement (generated)", "",
         f"Answered {res['answered']} of {res['items']} items. One reviewer: no between-reviewer "
         "agreement can be computed.", "",
         "| measure | n | % agreement | Cohen's kappa |", "|---|---|---|---|"]
    for name, x in (("label (CORRECT / WRONG / UNCERTAIN)", lab), ("layer, both said WRONG", lay)):
        if x["n"]:
            k = "-" if x["kappa"] is None else f"{x['kappa']:.2f}"
            L.append(f"| {name} | {x['n']} | {x['percent_agreement']:.0%} | {k} |")
        else:
            L.append(f"| {name} | 0 | - | - |")
    for name, x in (("label", lab), ("layer", lay)):
        if x["n"]:
            cats = sorted(x["confusion_system_by_reviewer"])
            L += ["", f"Confusion ({name}): rows = system, columns = reviewer", "",
                  "| system \\ reviewer | " + " | ".join(cats) + " |",
                  "|---|" + "---|" * len(cats)]
            for r in cats:
                L.append(f"| {r} | " + " | ".join(str(x["confusion_system_by_reviewer"][r][c])
                                                  for c in cats) + " |")
    out.with_suffix(".md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
