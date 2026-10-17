"""A normal install must carry the data files the product reads at run time."""

import tomllib
from fnmatch import fnmatch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "mandate"


def test_runtime_data_files_are_declared_as_package_data() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = config["tool"]["setuptools"]["package-data"]["mandate"]
    declared = {
        path.relative_to(PACKAGE).as_posix()
        for path in PACKAGE.rglob("*")
        if path.is_file()
        and any(fnmatch(path.relative_to(PACKAGE).as_posix(), p) for p in patterns)
    }
    for directory, suffix in (("graph/queries", ".cypher"), ("eval/scenarios", ".yaml")):
        on_disk = {
            p.relative_to(PACKAGE).as_posix() for p in (PACKAGE / directory).glob(f"*{suffix}")
        }
        assert on_disk and on_disk <= declared, directory


def test_every_data_file_directory_the_code_reads_is_covered() -> None:
    """If code starts reading a new kind of data file, this reminds you to ship it."""
    suffixes = {
        p.suffix for p in PACKAGE.rglob("*") if p.is_file() and "__pycache__" not in p.parts
    }
    assert suffixes <= {".py", ".cypher", ".yaml", ".typed", ""}, suffixes
