"""The unit tests run on the repository alone: ALPHA_DATA (alpha_poke.paths) points at a
temporary directory filled from tests/fixtures/data (tests/make_fixture_data.py), never at the
local data/. The belief model is built there from the fixture's replay sample on first use (each
pytest-xdist worker has its own directory). Set before any alpha_poke import: paths reads it
once."""

import atexit
import gzip
import os
import shutil
import tempfile
from pathlib import Path

FIXTURE_DATA = Path(__file__).parent / "fixtures" / "data"


def _test_data() -> Path:
    root = Path(tempfile.mkdtemp(prefix="alpha-poke-test-data-"))
    atexit.register(shutil.rmtree, root, ignore_errors=True)
    for src in FIXTURE_DATA.rglob("*"):
        if not src.is_file():
            continue
        dst = root / src.relative_to(FIXTURE_DATA)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix == ".gz":
            dst.with_suffix("").write_bytes(gzip.decompress(src.read_bytes()))
        else:
            shutil.copyfile(src, dst)
    return root


os.environ["ALPHA_DATA"] = str(_test_data())
