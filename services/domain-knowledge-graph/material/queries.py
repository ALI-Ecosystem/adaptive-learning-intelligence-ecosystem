"""What a stored Course Material Graph is good for: questions other parts of ALI can ask it.

  python -m material.queries MATERIAL_GRAPH_ID order          taught concepts in teaching order
  python -m material.queries MATERIAL_GRAPH_ID unit N         what unit N teaches and what it needs:
                                                              taught earlier / taught later / never taught
  python -m material.queries MATERIAL_GRAPH_ID concept NAME   where a concept sits in the course
  python -m material.queries MATERIAL_GRAPH_ID prior          the course's prior knowledge
"""
import argparse

from placement.graph import Graph, connect

from . import store


def _by_unit(data):
    first, units = {}, {}
    for n in data["nodes"]:
        for u in n["units"]:
            units.setdefault(u["seq"], []).append((n, u["role"]))
            if u["role"] == "taught":
                first[n["id"]] = min(first.get(n["id"], 10**6), u["seq"])
    return first, units


def order(data):
    first, _ = _by_unit(data)
    titles = {u["seq"]: u["title"] for u in data["units"]}
    nodes = {n["id"]: n for n in data["nodes"]}
    return [(titles.get(s, s), nodes[c]["name"]) for c, s in sorted(first.items(), key=lambda x: (x[1], nodes[x[0]]["name"]))]


def unit(data, seq: int):
    first, units = _by_unit(data)
    out = {"teaches": [], "needs_taught_earlier": [], "needs_taught_later": [], "needs_never_taught": []}
    for n, role in units.get(seq, []):
        if role == "taught":
            out["teaches"].append(n["name"])
            continue
        f = first.get(n["id"])
        key = ("needs_never_taught" if f is None else
               "needs_taught_earlier" if f < seq else "needs_taught_later" if f > seq else None)
        if key:
            out[key].append(n["name"] + ("" if f is None else f" (unit {f + 1})"))
    return out


def concept(data, name: str):
    nodes = {n["id"]: n for n in data["nodes"]}
    hits = [n for n in data["nodes"] if n["name"].lower() == name.lower()] or \
           [n for n in data["nodes"] if name.lower() in n["name"].lower()]
    if not hits:
        return None
    n = hits[0]
    chain, cur = [], n
    while cur.get("parent_id") in nodes:
        cur = nodes[cur["parent_id"]]
        chain.append(cur["name"])
    children = [m["name"] for m in data["nodes"] if m.get("parent_id") == n["id"]]
    pre = [nodes[e["src"]]["name"] for e in data["edges"] if e["type"] == "PREREQUISITE_OF" and e["dst"] == n["id"]]
    titles = {u["seq"]: u["title"] for u in data["units"]}
    return {"concept": n["name"], "concept_id": n["concept_id"], "role": n["role"],
            "path_in_course": " > ".join(list(reversed(chain)) + [n["name"]]),
            "children_in_course": children, "prerequisites_in_course": pre,
            "units": [f"{u['seq'] + 1}. {titles.get(u['seq'], '')} ({u['role']})"
                      for u in sorted(n["units"], key=lambda u: u["seq"])]}


def prior(data):
    return sorted(n["name"] for n in data["nodes"] if n["role"] == "prerequisite")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("material_graph_id")
    ap.add_argument("what", choices=["order", "unit", "concept", "prior"])
    ap.add_argument("arg", nargs="?")
    a = ap.parse_args()
    g = Graph(connect())
    data = store.load(g, a.material_graph_id)
    if not data:
        raise SystemExit("not found")
    if a.what == "order":
        last = None
        for t, c in order(data):
            if t != last:
                print(f"\n{t}"); last = t
            print(f"  {c}")
    elif a.what == "unit":
        res = unit(data, int(a.arg) - 1)
        for k, v in res.items():
            print(f"{k}: {', '.join(v) if v else '-'}")
    elif a.what == "concept":
        res = concept(data, a.arg or "")
        if not res:
            print("not in this material graph")
        else:
            for k, v in res.items():
                print(f"{k}: {v}")
    else:
        print("\n".join(prior(data)))
    g.driver.close()


if __name__ == "__main__":
    main()
