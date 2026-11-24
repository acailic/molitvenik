"""Shared test helpers: where the fixtures are and how to load them."""

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def fixtures() -> Path:
    """Directory of test fixtures (real OCR pages cut from the book, transcriptions)."""
    return FIXTURES


def load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def load_fixture():
    """load_fixture(kind, "p-110") reads tests/fixtures/<kind>/p-110.json."""

    def _load(kind: str, name: str) -> dict:
        return load_json(FIXTURES / kind / f"{name}.json")

    return _load
