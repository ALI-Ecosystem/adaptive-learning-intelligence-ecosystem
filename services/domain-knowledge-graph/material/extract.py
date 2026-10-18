"""Step 1 of CREATE MATERIAL GRAPH: find the concepts each unit of the material is about.

Every concept gets a role in the unit (decision 2026-10-18, option C):
  taught        the unit explains it (its definition, how it works, examples)
  prerequisite  the unit uses it and expects the learner to know it already

Two methods:
  llm      Claude reads the unit and reports concepts with a short evidence quote
  lexical  no LLM: graph concept names found word-for-word in the text (comparison
           baseline; works only where the material uses the graph's English names)
"""
import re
from collections import Counter
from dataclasses import asdict, dataclass

from placement import config

from .ingest import Material, Unit
from .llm import UNTRUSTED_MATERIAL, JsonCache, Usage, as_list, call_tool, material_block

UNIT_CHARS = 24_000          # what the extractor reads of one unit
MAX_TAUGHT, MAX_PREREQ = 12, 8


@dataclass
class Mention:
    unit_seq: int
    name: str                # English, encyclopedia-style (the linking key)
    name_original: str       # as written in the material (may be Hebrew)
    description: str         # one English sentence
    role: str                # taught | prerequisite
    importance: int          # 3 = a main topic of the unit, 2 = substantial, 1 = minor
    evidence: str            # short quote from the unit
    method: str


SYSTEM = f"""You read one unit (a lecture, chapter or page) of university course material and \
list the academic concepts in it, for a knowledge graph of the course.

For each concept report:
- name: the concept's standard English name as an encyclopedia article title would give it \
(e.g. "Hidden Markov model", "Merge sort", "Red–black tree"). The material may be in Hebrew; \
always translate the name to English.
- name_original: the name exactly as the material writes it.
- description: one plain English sentence defining it.
- role: "taught" if this unit explains the concept (defines it, shows how it works, gives \
examples or proofs); "prerequisite" if the unit only uses it and expects the learner to know it.
- importance: 3 = a main topic of the unit, 2 = explained in some depth, 1 = covered briefly.
- evidence: a short quote (at most 25 words) copied from the unit that shows the role.

What counts as a concept: a theory, method, algorithm, model, data structure, problem, \
property or technique that a learner studies - something a textbook section or encyclopedia \
article could be about. Not: people, courses, datasets or corpora by name, software tools and \
libraries, file formats, examples or exercises themselves, or single variables and symbols.

Granularity: name concepts at the level the unit teaches them; do not split one concept into \
its parts and do not list a broad field (e.g. "Computer science") unless the unit is about it.
List at most {MAX_TAUGHT} taught and {MAX_PREREQ} prerequisite concepts, most important first. \
An empty list is better than a guess.

{UNTRUSTED_MATERIAL}"""

TOOL = {
    "name": "report_concepts",
    "description": "Report the concepts of this unit.",
    "input_schema": {"type": "object", "properties": {
        "unit_topic": {"type": "string", "description": "The unit's main topic, in English, a few words"},
        "concepts": {"type": "array", "maxItems": MAX_TAUGHT + MAX_PREREQ, "items": {
            "type": "object", "properties": {
                "name": {"type": "string"},
                "name_original": {"type": "string"},
                "description": {"type": "string"},
                "role": {"type": "string", "enum": ["taught", "prerequisite"]},
                "importance": {"type": "integer", "minimum": 1, "maximum": 3},
                "evidence": {"type": "string"}},
            "required": ["name", "description", "role", "importance"]}}},
        "required": ["unit_topic", "concepts"]}}


def _clean_mentions(unit: Unit, out: dict, method: str) -> list[Mention]:
    res, seen = [], set()
    taught = prereq = 0
    for c in as_list(out.get("concepts")):
        name = " ".join(str(c.get("name", "")).split())[:120]
        role = c.get("role") if c.get("role") in ("taught", "prerequisite") else "taught"
        if len(re.sub(r"[^\w]", "", name)) < 3 or name.casefold() in seen:
            continue                     # symbols and variables such as "x" are not concepts
        if role == "taught":
            taught += 1
            if taught > MAX_TAUGHT:
                continue
        else:
            prereq += 1
            if prereq > MAX_PREREQ:
                continue
        seen.add(name.casefold())
        try:
            imp = max(1, min(3, int(c.get("importance", 1))))
        except (TypeError, ValueError):
            imp = 1
        res.append(Mention(unit.seq, name, str(c.get("name_original") or name)[:120],
                           str(c.get("description") or "")[:400], role, imp,
                           str(c.get("evidence") or "")[:300], method))
    return res


def extract_unit_llm(unit: Unit, material_title: str, client, model: str = config.CLAUDE_MODEL,
                     usage: Usage | None = None, cache: JsonCache | None = None) -> tuple[str, list[Mention]]:
    key = JsonCache.key("extract-v1", model, unit.title, unit.text[:UNIT_CHARS])
    out = cache.get(key) if cache else None
    if out is None:
        user = (f"Course: {material_title[:200]}\nUnit title: {unit.title[:200]}\n\n"
                + material_block(unit.text, UNIT_CHARS)
                + "\n\nList the concepts of this unit with report_concepts.")
        out = call_tool(client, model, SYSTEM, user, TOOL, usage)
        if cache:
            cache.put(key, out)
    return str(out.get("unit_topic", ""))[:200], _clean_mentions(unit, out, "llm")


# ---- lexical baseline ------------------------------------------------------
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9'\-]*")
_QUAL = re.compile(r"\s*\([^)]*\)")
GENERIC = {"set", "order", "time", "model", "process", "system", "function", "value", "state",
           "test", "language", "data", "point", "line", "word", "class", "example", "problem",
           "method", "theory", "field", "structure", "network", "tree", "graph", "path"}


class Lexicon:
    """Graph concept names (without qualifier), for word-for-word matching."""

    def __init__(self, rows: list[dict]):
        self.by_surface: dict[str, list[dict]] = {}
        for r in rows:
            s = " ".join(_WORD.findall(_QUAL.sub("", r["name"]))).casefold()
            if not s or s in GENERIC or len(s) < 4:
                continue
            self.by_surface.setdefault(s, []).append(r)
        self.max_len = max((len(s.split()) for s in self.by_surface), default=1)

    @classmethod
    def from_graph(cls, graph):
        return cls(graph._read("MATCH (c:Concept) RETURN c.id AS id, c.name AS name, "
                               "c.level AS level, c.works_count AS works ORDER BY c.works_count DESC"))


def extract_unit_lexical(unit: Unit, lex: Lexicon, top: int = 15) -> list[Mention]:
    words = [w.casefold() for w in _WORD.findall(unit.text)]
    counts = Counter()
    for n in range(min(lex.max_len, 5), 0, -1):
        for i in range(len(words) - n + 1):
            s = " ".join(words[i:i + n])
            if s in lex.by_surface:
                counts[s] += 1
    # rank: frequent and specific (deeper level, longer name) first
    def score(s):
        best = lex.by_surface[s][0]
        return counts[s] * (1 + (best.get("level") or 0)) * len(s.split())
    res = []
    for s in sorted(counts, key=score, reverse=True)[:top]:
        best = lex.by_surface[s][0]
        res.append(Mention(unit.seq, best["name"], s, "", "taught",
                           3 if len(res) < 3 else (2 if len(res) < 8 else 1),
                           f"'{s}' x{counts[s]}", "lexical"))
    return res


def extract(material: Material, method: str, client=None, lexicon: Lexicon | None = None,
            model: str = config.CLAUDE_MODEL, cache: JsonCache | None = None,
            progress=print) -> tuple[list[Mention], dict, Usage]:
    usage, topics, mentions = Usage(), {}, []
    for u in material.units:
        if method == "llm":
            topics[u.seq], ms = extract_unit_llm(u, material.title, client, model, usage, cache)
        else:
            topics[u.seq], ms = "", extract_unit_lexical(u, lexicon)
        mentions += ms
        if cache:
            cache.save()                 # a crash later never throws away paid answers
        if progress:
            progress(f"  unit {u.seq + 1}/{len(material.units)} {u.title[:40]}: {len(ms)} concepts")
    return mentions, topics, usage


def mentions_to_dicts(ms):
    return [asdict(m) for m in ms]
