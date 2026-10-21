import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from simulator.generator import simulate          # noqa: E402
from simulator.records import write_run           # noqa: E402

SEED, N = 2026, 150


@pytest.fixture(scope="session")
def run_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("sim")
    write_run(simulate(SEED, N), d)
    return d
