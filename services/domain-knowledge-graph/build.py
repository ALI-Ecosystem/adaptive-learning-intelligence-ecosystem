"""Build the SCRUM-88 Domain Knowledge Graph baseline import files.

Joins OpenAlex Concepts (nodes) with the MAG 2020-01-23 hierarchy (CHILD_OF)
and related-concept links (RELATED_TO), scores every parent link with a
static embedding model and flags suspicious structure. Nothing is deleted.

Usage: python build.py [--raw raw] [--out import]
"""
import argparse, collections, csv, gzip, json, os
import numpy as np
from model2vec import StaticModel

MODEL = "minishlab/potion-base-32M"
FANIN_FACTOR = 10      # parent flagged if child count > FANIN_FACTOR x p99 of its level
MAX_PARENTS = 10       # child flagged if it has more parents than this


def load_concepts(raw):
    c = {}
    with gzip.open(os.path.join(raw, "part_0000.gz"), "rt") as f:
        for line in f:
            d = json.loads(line)
            i = int(d["id"].rsplit("C", 1)[1])
            c[i] = dict(id="C%d" % i, name=d["display_name"], desc=d.get("description") or "",
                        level=d["level"], wikidata=(d.get("wikidata") or "").rsplit("/", 1)[-1],
                        works=d.get("works_count") or 0)
    return c


def load_parents(raw, c):
    par = collections.defaultdict(set)
    with gzip.open(os.path.join(raw, "FieldOfStudyChildren.txt.gz"), "rt") as f:
        for line in f:
            p, ch = map(int, line.split("\t")[:2])
            if p in c and ch in c and p != ch:
                par[ch].add(p)
    return par


def write_related(raw, out, c):
    seen, n = set(), 0
    with gzip.open(os.path.join(raw, "RelatedFieldOfStudy.txt.gz"), "rt") as f, \
            gzip.open(os.path.join(out, "edges_related.csv.gz"), "wt", newline="") as g:
        w = csv.writer(g)
        w.writerow(["a_id", "b_id", "a_type", "b_type", "score"])
        for line in f:
            a, t1, b, t2, r = line.rstrip("\n").split("\t")
            a, b = int(a), int(b)
            k = (min(a, b), max(a, b))
            if a in c and b in c and a != b and k not in seen:
                seen.add(k)
                w.writerow(["C%d" % a, "C%d" % b, t1, t2, round(float(r), 6)])
                n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="raw")
    ap.add_argument("--out", default="import")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    c = load_concepts(a.raw)
    par = load_parents(a.raw, c)
    kids = collections.Counter(p for ch in par for p in par[ch])

    ids = list(c)
    idx = {i: k for k, i in enumerate(ids)}
    text = lambda i: c[i]["name"] + (": " + c[i]["desc"] if c[i]["desc"] else "")
    V = np.asarray(StaticModel.from_pretrained(MODEL).encode([text(i) for i in ids]), dtype=np.float32)
    V /= np.linalg.norm(V, axis=1, keepdims=True)

    by_level = collections.defaultdict(list)
    for p, n in kids.items():
        by_level[c[p]["level"]].append(n)
    p99 = {L: sorted(v)[int(len(v) * 0.99)] for L, v in by_level.items()}
    outlier = {p for p, n in kids.items() if n > FANIN_FACTOR * p99[c[p]["level"]]}

    edges = 0
    with open(os.path.join(a.out, "edges_child_of.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["child_id", "parent_id", "similarity", "primary", "flags"])
        for ch, ps in par.items():
            sims = {p: float(V[idx[ch]] @ V[idx[p]]) for p in ps}
            best = max(sims, key=sims.get)
            for p in ps:
                flags = []
                if p in outlier:
                    flags.append("PARENT_FANIN_OUTLIER")
                if len(ps) > MAX_PARENTS:
                    flags.append("CHILD_TOO_MANY_PARENTS")
                if c[p]["level"] >= c[ch]["level"]:
                    flags.append("LEVEL_INVERSION")
                w.writerow([c[ch]["id"], c[p]["id"], round(sims[p], 4), p == best, "|".join(flags)])
                edges += 1

    with open(os.path.join(a.out, "concepts.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "description", "level", "wikidata", "works_count",
                    "disambiguation_suspect", "parent_count", "child_count"])
        for i in ids:
            d = c[i]
            w.writerow([d["id"], d["name"], d["desc"], d["level"], d["wikidata"], d["works"],
                        d["desc"] == "Wikimedia disambiguation page", len(par.get(i, ())), kids.get(i, 0)])

    related = write_related(a.raw, a.out, c)
    print(f"concepts={len(c)} child_of={edges} related={related} "
          f"outlier_parents={[c[p]['name'] for p in outlier]}")


if __name__ == "__main__":
    main()
