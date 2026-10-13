"""Settings, read from the environment and from the git-ignored .env / neo4j.env
files in the service folder. Values already in the environment win."""
import os
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


for _name in (".env", "neo4j.env"):
    _load_env_file(SERVICE_DIR / _name)

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")

CLAUDE_MODEL = os.environ.get("ALI_CLAUDE_MODEL", "claude-sonnet-5-5")
EMBED_MODEL = "minishlab/potion-base-32M"   # same model as SCRUM-88 build.py
VECTOR_INDEX = "concept_embedding"
FULLTEXT_INDEX = "concept_text"             # created by SCRUM-88 load.cypher

RUNS_DIR = SERVICE_DIR / "runs"             # traces and eval results, git-ignored


def require_neo4j_password() -> str:
    if not NEO4J_PASSWORD:
        raise SystemExit("NEO4J_PASSWORD is not set. Put it in .env or neo4j.env in "
                         f"{SERVICE_DIR} (same password start-neo4j.sh created).")
    return NEO4J_PASSWORD
