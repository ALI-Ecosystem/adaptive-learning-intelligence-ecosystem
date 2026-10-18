"""Download the two sample courses of SCRUM-91 into materials/ (git-ignored).

  1 ENLP, Georgetown COSC-572 (Nathan Schneider, 2018): 25 lecture PDFs, listed in
    LectureBank (Li et al., AAAI 2019) - URLs in schneider-enlp-2018.tsv
  2 "מבני נתונים ואלגוריתמים - מחברת קורס", Hebrew Wikibooks (CC BY-SA): lecture notes
    of Tel Aviv University course 0512-2510, via the MediaWiki API

Run from the service folder:  .venv/bin/python -m material.samples.fetch_samples
"""
import csv
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent.parent / "materials"
UA = {"User-Agent": "ALI-research/0.1 (student final project, Shenkar College)"}
BOOK = "מבני נתונים ואלגוריתמים - מחברת קורס"
API = "https://he.wikibooks.org/w/api.php?"
MAX_BYTES = 25 * 1024 * 1024


def _get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError(f"{url}: too large")
    return data


def schneider():
    d = OUT / "schneider-enlp-2018"
    d.mkdir(parents=True, exist_ok=True)
    with open(HERE / "schneider-enlp-2018.tsv") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    for r in rows:
        p = d / r["file"]
        if p.exists():
            continue
        if not r["url"].startswith(("http://people.cs.georgetown.edu/", "https://people.cs.georgetown.edu/")):
            raise ValueError(f"unexpected URL {r['url']}")
        data = _get(r["url"])
        if not data.startswith(b"%PDF"):
            raise ValueError(f"{r['file']}: not a PDF")
        p.write_bytes(data)
        print("  ", r["file"])
    print(f"ENLP: {len(rows)} PDFs in {d}")


def _api(**p):
    p["format"] = "json"
    return json.loads(_get(API + urllib.parse.urlencode(p)))


def hebrew():
    out = OUT / "hebrew-ds-wikibooks.json"
    if out.exists():
        print(f"Hebrew book: {out} exists"); return
    links = _api(action="parse", page="תבנית:" + BOOK, prop="links")["parse"]["links"]
    titles = [l["*"] for l in links if l["ns"] == 0 and "תרגילים" not in l["*"]]
    units = []
    for i, title in enumerate(titles):
        q = _api(action="query", prop="extracts|revisions", titles=title, explaintext=1, rvprop="ids|timestamp")
        page = next(iter(q["query"]["pages"].values()))
        rev = page.get("revisions", [{}])[0]
        units.append({"seq": i, "title": title, "unit": title.split(BOOK)[-1].strip("/"),
                      "text": page.get("extract", ""), "revid": rev.get("revid"),
                      "url": "https://he.wikibooks.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))})
        time.sleep(1.0)                                   # be polite to the API
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"book": BOOK, "license": "CC BY-SA 4.0", "units": units},
                              ensure_ascii=False, indent=1))
    print(f"Hebrew book: {len(units)} pages in {out}")


if __name__ == "__main__":
    schneider()
    hebrew()
