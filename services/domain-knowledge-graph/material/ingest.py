"""Read learning material into units (one lecture, chapter or page each).

The material is untrusted input: files are size-capped, text is cleaned and capped, and
nothing in it is ever executed or followed (no links are fetched). Supported sources:

  folder of PDFs   one unit per PDF, ordered by file name (lecture files are usually
                   numbered: 01_intro.pdf, 02_corpora.pdf ...)
  folder of .txt / .md files   same, one unit per file
  wikibooks JSON   the output of fetch_hebrew.py (a book's chapters with their text)

Every unit keeps a content hash, so the same material always gets the same material id.
"""
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

MAX_FILE_BYTES = 25 * 1024 * 1024      # one PDF / text file
MAX_UNITS = 200
MAX_UNIT_CHARS = 60_000                # text kept per unit (the extractor reads less)
MIN_UNIT_WORDS = 40                    # shorter units are index pages, not content


@dataclass
class Unit:
    seq: int                 # position in the material (teaching order when known)
    key: str                 # stable key inside the material: file name or page title
    title: str
    text: str
    source_ref: str = ""     # URL or file name, for people
    meta: dict = field(default_factory=dict)

    @property
    def words(self) -> int:
        return len(self.text.split())


@dataclass
class Material:
    title: str
    source: str              # where it came from (URL / folder), for people
    language: str            # 'en' / 'he' / 'mixed' (detected)
    units: list[Unit]
    license: str = ""

    def content_hash(self) -> str:
        h = hashlib.sha256()
        for u in self.units:
            h.update(u.key.encode()); h.update(b"\0"); h.update(u.text.encode()); h.update(b"\1")
        return h.hexdigest()


_HEBREW = re.compile(r"[֐-׿]")
_LATIN = re.compile(r"[A-Za-z]")
_CTRL = re.compile(r"[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]")


def detect_language(text: str) -> str:
    he, en = len(_HEBREW.findall(text)), len(_LATIN.findall(text))
    if he > 0.3 * (he + en):
        return "he" if he > 0.7 * (he + en) else "mixed"
    return "en"


def clean_text(text: str) -> str:
    """Normalise, drop control characters and repeated lines. Slide decks repeat the
    same slide many times (one PDF page per animation build); keeping each line once
    removes that noise without losing content."""
    text = unicodedata.normalize("NFKC", text or "")
    text = _CTRL.sub(" ", text).replace("\r", "\n")
    seen, out = set(), []
    for line in text.split("\n"):
        line = " ".join(line.split())
        if not line:
            continue
        k = line.casefold()
        if k in seen and len(line) > 3:
            continue
        seen.add(k)
        out.append(line)
    return "\n".join(out)[:MAX_UNIT_CHARS]


def _check_size(p: Path):
    if p.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"{p.name}: larger than {MAX_FILE_BYTES // 2**20} MB")


def _pdf_text(p: Path) -> str:
    import logging
    from pypdf import PdfReader
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    reader = PdfReader(str(p))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _title_from_text(text: str, fallback: str) -> str:
    for line in text.split("\n")[:5]:
        if 3 <= len(line) <= 90:
            return line
    return fallback


def load_folder(folder: Path, title: str | None = None, titles: dict | None = None,
                source: str | None = None) -> Material:
    """titles: optional {file name: unit title} (e.g. from a course index)."""
    folder = Path(folder)
    files = sorted(f for f in folder.iterdir()
                   if f.suffix.lower() in (".pdf", ".txt", ".md") and f.is_file())
    if not files:
        raise ValueError(f"no .pdf/.txt/.md files in {folder}")
    if len(files) > MAX_UNITS:
        raise ValueError(f"{len(files)} files: more than {MAX_UNITS} units")
    units = []
    for f in files:
        _check_size(f)
        raw = _pdf_text(f) if f.suffix.lower() == ".pdf" else f.read_text(errors="replace")
        text = clean_text(raw)
        if len(text.split()) < MIN_UNIT_WORDS:
            continue
        t = (titles or {}).get(f.name) or _title_from_text(text, f.stem)
        units.append(Unit(seq=len(units), key=f.name, title=t, text=text, source_ref=f.name))
    lang = detect_language(" ".join(u.text[:3000] for u in units))
    return Material(title or folder.name, source or str(folder), lang, units)


def load_wikibooks(path: Path) -> Material:
    d = json.loads(Path(path).read_text())
    units = []
    for u in d["units"]:
        text = clean_text(u.get("text", ""))
        if len(text.split()) < MIN_UNIT_WORDS or not u.get("unit"):
            continue                     # the book's front page and part index pages
        units.append(Unit(seq=len(units), key=u["unit"], title=u["unit"].split("/")[-1],
                          text=text, source_ref=u.get("url", ""),
                          meta={"part": u["unit"].split("/")[0], "revid": u.get("revid")}))
    lang = detect_language(" ".join(u.text[:3000] for u in units))
    return Material(d.get("book", Path(path).stem), "he.wikibooks.org", lang, units,
                    license=d.get("license", ""))


def load(source: str | Path, **kw) -> Material:
    p = Path(source)
    if p.is_dir():
        return load_folder(p, **kw)
    if p.suffix == ".json":
        return load_wikibooks(p)
    raise ValueError(f"unsupported material source: {source}")
