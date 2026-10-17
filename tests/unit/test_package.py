import importlib

import pytest

SUBPACKAGES = [
    "graph",
    "models",
    "authority",
    "lineage",
    "gateway",
    "gateway.sandbox",
    "agents",
    "api",
    "api.routes",
    "eval",
]


def test_version() -> None:
    import mandate

    assert mandate.__version__ == "0.0.0"


@pytest.mark.parametrize("name", SUBPACKAGES)
def test_subpackage_imports(name: str) -> None:
    importlib.import_module(f"mandate.{name}")
