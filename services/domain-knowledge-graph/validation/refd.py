"""RefD - reference distance (Liang et al., 2015, "Measuring Prerequisite Relations Among
Concepts"): an external, non-LLM signal for the DIRECTION of a prerequisite link.

Idea: if the Wikipedia article of B links to many articles that themselves point to A,
and A's article rarely does the same towards B, then A is more likely needed to learn B.

    RefD(A, B) =  share of B's links w that reference A (w is A, or w links to A)
                - share of A's links w that reference B
    > 0  A is a prerequisite of B        < 0  B is a prerequisite of A        ~0  no signal

Computed with the public Wikipedia API: the outgoing links of each article (redirects
resolved) and the backlinks of each article (pages that link to it, through redirects too).
Backlinks of very popular articles are capped (MAX_BACKLINK_PAGES); the result then says
"truncated" and the signal for that pair is weaker. Everything is cached on disk.
"""
from .wikidata import WikidataClient

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
MAX_LINK_PAGES = 4          # x 500 outgoing links
MAX_BACKLINK_PAGES = 10     # x 500 backlinks
THRESHOLD = 0.02            # |RefD| below this is "no signal" (direction check)
RESCUE_THRESHOLD = 0.10     # a link the validator did NOT mark reaches the teacher only when
                            # RefD is at least this strong. At 0.02 the teacher got 16% of all
                            # LectureBank links, 65% of them wrong; at 0.10 5% (Kody, 2026-10-16)


class WikipediaClient(WikidataClient):
    def __init__(self, cache_path=None, pause: float = 0.3):
        super().__init__(cache_path, pause)
        self.api = WIKIPEDIA_API
        self.cache.setdefault("links", {})
        self.cache.setdefault("backlinks", {})

    def links(self, title: str) -> list[str]:
        if title not in self.cache["links"]:
            out, cont = set(), {}
            for _ in range(MAX_LINK_PAGES):
                d = self._get(action="query", generator="links", titles=title, gpllimit="max",
                              gplnamespace=0, redirects=1, **cont)
                out |= {pg["title"] for pg in d.get("query", {}).get("pages", {}).values()
                        if "missing" not in pg}
                if "continue" not in d:
                    break
                cont = {k: v for k, v in d["continue"].items()}
            self.cache["links"][title] = sorted(out)
        return self.cache["links"][title]

    def backlinks(self, title: str) -> dict:
        if title not in self.cache["backlinks"]:
            out, cont, truncated = set(), {}, True
            for _ in range(MAX_BACKLINK_PAGES):
                d = self._get(action="query", list="backlinks", bltitle=title, bllimit="max",
                              blnamespace=0, blredirect=1, **cont)
                for b in d.get("query", {}).get("backlinks", []):
                    out.add(b["title"])
                    for r in b.get("redirlinks", []):
                        out.add(r["title"])
                if "continue" not in d:
                    truncated = False
                    break
                cont = {k: v for k, v in d["continue"].items()}
            self.cache["backlinks"][title] = {"titles": sorted(out), "truncated": truncated}
        return self.cache["backlinks"][title]


def _share(links_of_b: list[str], a: str, backlinks_a: set[str]) -> float:
    if not links_of_b:
        return 0.0
    return sum(1 for w in links_of_b if w == a or w in backlinks_a) / len(links_of_b)


def refd(wp: WikipediaClient, a: str, b: str) -> dict:
    """RefD(A, B) between two article titles. Positive: A is a prerequisite of B."""
    la, lb = wp.links(a), wp.links(b)
    ba, bb = wp.backlinks(a), wp.backlinks(b)
    if not la or not lb:
        return {"refd": None, "reason": "an article has no links", "a": a, "b": b}
    value = _share(lb, a, set(ba["titles"])) - _share(la, b, set(bb["titles"]))
    return {"refd": round(value, 4), "a": a, "b": b,
            "truncated": ba["truncated"] or bb["truncated"]}


def verdict(value) -> str:
    if value is None:
        return "no_evidence"
    if value >= THRESHOLD:
        return "supports"
    if value <= -THRESHOLD:
        return "reversed"
    return "no_evidence"
