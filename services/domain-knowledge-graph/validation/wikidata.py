"""Layer 3 of the gate: an external source that is not a language model - Wikidata.

Every SCRUM-88 concept carries its Wikidata id (Concept.wikidata), so the proposed
parent is always anchored there. The new concept is found by its name (English, then
the Hebrew original), the way it would be for a truly new concept, and its Wikidata
ancestors are collected through:
    P279 subclass of, P361 part of, P1269 facet of, P2579 studied by
    (+ P31 instance of, first step only: further up it leads to meta-classes)

Kody's decision (2026-10-16): no path in Wikidata is NOT evidence against a placement.
Wikidata is incomplete, so the layer has three answers, never two:
    support      the proposed parent is a Wikidata ancestor of the new concept
    contradict   Wikidata places the concept only in other top-level fields of our graph.
                 Calibration (541 judged pairs): it fired on 18% of correct and 16% of wrong
                 placements - noise, because many concepts belong to several fields and the
                 field is read along primary parents only. Kept as INFO, never decides.
    no evidence  not found, no ancestors, or no ancestor that is in our graph

Plus a duplicate check: when Wikidata knows the new name as a label or alias of an item
that is already a concept in our graph, the concept already exists.

Network: the public Wikidata API, with a disk cache (runs/wikidata-cache.json) so a
repeated run makes no calls and Wikidata is never hammered.
"""
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Protocol

from .contract import _QUALIFIER, Check, Proposal, Result, base_name, normalize_name

LAYER = "external"
API = "https://www.wikidata.org/w/api.php"
# Wikimedia's User-Agent policy asks for a way to reach the operator; anonymous agents
# are throttled much harder (HTTP 429).
USER_AGENT = ("ALI-final-project/0.1 "
              "(https://github.com/edelagziel/adaptive-learning-intelligence-ecosystem; "
              "student project) python-urllib")
UP_PROPS = ("P279", "P361", "P1269", "P2579")
FIRST_STEP_PROPS = UP_PROPS + ("P31",)
MAX_DEPTH = 4
SEARCH_LIMIT = 5


class WikidataClient:
    def __init__(self, cache_path: Path | None = None, pause: float = 0.5):
        self.cache_path = cache_path
        self.pause = pause
        self.api = API
        self.cache = {"search": {}, "claims": {}, "sitelinks": {}}
        self._lock = threading.Lock()
        if cache_path and cache_path.is_file():
            self.cache.update(json.loads(cache_path.read_text()))

    def save(self):
        if self.cache_path:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self.cache))

    def _get(self, **params):
        url = self.api + "?" + urllib.parse.urlencode({**params, "format": "json"})
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept": "application/json"})
        for attempt in range(7):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    time.sleep(self.pause)
                    return json.load(r)
            except urllib.error.HTTPError as e:
                if e.code not in (429, 500, 502, 503, 504) or attempt == 6:
                    raise
                wait = int(e.headers.get("Retry-After") or 0) or min(5 * 2 ** attempt, 120)
                print(f"\n  Wikidata said {e.code}, waiting {wait}s ...", flush=True)
                time.sleep(wait)
            except (urllib.error.URLError, TimeoutError):
                if attempt == 6:
                    raise
                time.sleep(5 * (attempt + 1))

    def search(self, text: str, lang: str = "en") -> list[dict]:
        key = f"{lang}:{text}"
        if key not in self.cache["search"]:
            d = self._get(action="wbsearchentities", search=text, language=lang, uselang=lang,
                          type="item", limit=SEARCH_LIMIT)
            self.cache["search"][key] = [
                {"id": h["id"], "label": h.get("label", ""), "description": h.get("description", ""),
                 "match_type": h.get("match", {}).get("type", ""),
                 "match_text": h.get("match", {}).get("text", "")}
                for h in d.get("search", [])]
        return self.cache["search"][key]

    def claims(self, qids: list[str]) -> dict[str, dict[str, list[str]]]:
        """{qid: {prop: [parent qids]}} for the properties in FIRST_STEP_PROPS."""
        todo = [q for q in dict.fromkeys(qids) if q not in self.cache["claims"]]
        for i in range(0, len(todo), 50):
            batch = todo[i:i + 50]
            d = self._get(action="wbgetentities", ids="|".join(batch), props="claims")
            for q in batch:
                cl = d.get("entities", {}).get(q, {}).get("claims", {})
                self.cache["claims"][q] = {
                    p: [c["mainsnak"]["datavalue"]["value"]["id"] for c in cl.get(p, [])
                        if c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")]
                    for p in FIRST_STEP_PROPS}
        return {q: self.cache["claims"].get(q, {}) for q in qids}

    def enwiki_title(self, qid: str) -> str | None:
        """English Wikipedia article title of a Wikidata item (used by RefD)."""
        if qid not in self.cache["sitelinks"]:
            d = self._get(action="wbgetentities", ids=qid, props="sitelinks", sitefilter="enwiki")
            sl = d.get("entities", {}).get(qid, {}).get("sitelinks", {}).get("enwiki")
            self.cache["sitelinks"][qid] = sl["title"] if sl else None
        return self.cache["sitelinks"][qid]


def ancestors(client, qid: str, depth: int = MAX_DEPTH) -> dict[str, int]:
    """{ancestor qid: distance}, breadth first."""
    seen, frontier = {}, [qid]
    for d in range(1, depth + 1):
        props = FIRST_STEP_PROPS if d == 1 else UP_PROPS
        nxt = []
        for q, cl in client.claims(frontier).items():
            for p in props:
                for a in cl.get(p, []):
                    if a != qid and a not in seen:
                        seen[a] = d
                        nxt.append(a)
        frontier = nxt
        if not frontier:
            break
    return seen


def resolve(client, p: Proposal) -> dict | None:
    """Find the new concept in Wikidata by name: English, then the name without its
    qualifier ('Indeterminate (variable)' -> 'Indeterminate'), then the Hebrew original.
    Only an exact label or alias match counts. Search also returns prefix matches
    ('Coproduct' -> 'coproduction' -> collaboration); taking those would turn a wrong
    item into a false contradiction, so no exact match means no evidence."""
    tries = [(p.name, "en")]
    if base_name(p.name) != normalize_name(p.name):
        tries.append((_QUALIFIER.sub(" ", p.name).strip(), "en"))
    if p.name_original:
        tries.append((p.name_original, "he"))
    for text, lang in tries:
        if not text:
            continue
        hits = client.search(text, lang)
        exact = [h for h in hits if normalize_name(h["match_text"]) == normalize_name(text)]
        if exact:
            return {**exact[0], "lang": lang, "exact": True, "candidates": len(exact),
                    "searched": text}
    return None


class ExternalGraphView(Protocol):
    def wikidata_of(self, cid: str) -> str | None: ...
    def concepts_by_qids(self, qids: list[str]) -> list[dict]:
        """[{id, concept_id, name, wikidata}] concepts in our graph with these Wikidata ids."""
    def field_of(self, cid: str) -> str | None:
        """id of the top-level field (level 0) above cid, along primary parents."""


def _check(name, result, message, **evidence):
    return Check(LAYER, name, result, message, evidence)


def run(p: Proposal, view: ExternalGraphView, client) -> tuple[list[Check], str | None, dict]:
    """Returns (checks, duplicate_of concept_id or None, signals)."""
    parent = p.parent_ids[0]
    parent_q = view.wikidata_of(parent)
    found = resolve(client, p)
    sig = {"resolved": found and found["id"], "resolved_exact": found and found["exact"],
           "parent_qid": parent_q, "support": None, "contradict": None, "duplicate_of": None}
    if not found:
        return [_check("wikidata_found", Result.SKIP, "the concept is not in Wikidata: no evidence",
                       searched=[p.name, p.name_original])], None, sig
    checks = [_check("wikidata_found", Result.PASS,
                     f"found as {found['id']} ({found['label']})",
                     qid=found["id"], label=found["label"], searched=found["searched"],
                     language=found["lang"], exact_matches=found["candidates"])]

    # duplicate: Wikidata knows this name as an item that is already one of our concepts
    same = [c for c in view.concepts_by_qids([found["id"]]) if c["id"] != p.id]
    # FAIL only when the name points at exactly one Wikidata item (a homonym like 'Stack'
    # matches several) AND that item is exactly one of our concepts: OpenAlex maps 4,401
    # Wikidata ids to more than one concept (10,330 concepts, e.g. 'Sensory cue' and its
    # child 'Olfactory cues'), so a shared id alone does not prove identity
    if len(same) == 1 and found["candidates"] == 1:
        dup = same[0].get("concept_id") or same[0]["id"]
        sig["duplicate_of"] = dup
        checks.append(_check("wikidata_duplicate", Result.FAIL,
                             f"Wikidata knows '{found['match_text']}' as {found['id']}, which is "
                             f"already the concept {same[0]['name']}", duplicate_of=dup,
                             match_type=found["match_type"]))
        return checks, dup, sig
    if same:
        checks.append(_check("wikidata_duplicate", Result.WARN,
                             "the Wikidata item is already used by concept(s) in our graph",
                             existing=[c["id"] for c in same]))

    anc = ancestors(client, found["id"])
    if parent_q and parent_q in anc:
        sig["support"] = anc[parent_q]
        checks.append(_check("wikidata_parent", Result.PASS,
                             f"Wikidata places it under the proposed parent ({anc[parent_q]} step(s) up)",
                             parent_qid=parent_q, distance=anc[parent_q]))
        return checks, None, sig

    mapped = [c for c in view.concepts_by_qids(list(anc)) if c["id"] != p.id]
    if not mapped:
        checks.append(_check("wikidata_parent", Result.SKIP,
                             "no Wikidata ancestor is in our graph: no evidence",
                             ancestors=len(anc)))
        return checks, None, sig

    parent_field = view.field_of(parent)
    fields = {view.field_of(c["id"]) for c in mapped} - {None}
    if parent_field and fields and parent_field not in fields:
        sig["contradict"] = sorted(fields)
        checks.append(_check("wikidata_domain", Result.INFO,
                             "Wikidata places the concept only in other top-level fields",
                             parent_field=parent_field, wikidata_fields=sorted(fields),
                             via=[c["name"] for c in mapped[:5]]))
    else:
        checks.append(_check("wikidata_parent", Result.SKIP,
                             "Wikidata ancestors are in the same field, but not the proposed parent: "
                             "no evidence either way", via=[c["name"] for c in mapped[:5]]))
    return checks, None, sig
