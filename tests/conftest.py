"""Test setup.

`main.py` builds the Hugging Face pipeline at import time, which would download a ~250MB
model. Before anything imports `main`, this file installs a stub `transformers` module whose
`pipeline()` returns a controllable fake, so the suite runs offline and without torch.
"""

import json
import sys
import types
from pathlib import Path
from typing import Dict, List

import pytest

EVIDENCE_DIR = Path(__file__).parent / "fixtures" / "evidence"


def load_evidence(name: str):
    """Parse one synthetic evidence fixture (see tests/fixtures/evidence/generate.py)."""
    from triage.evidence import parse_evidence

    with open(EVIDENCE_DIR / f"{name}.json", encoding="utf-8") as handle:
        return parse_evidence(json.load(handle))


@pytest.fixture
def evidence():
    return load_evidence


class FakeSentimentPipeline:
    """Stands in for the HF sentiment pipeline. Tests set `label`/`score` per case."""

    def __init__(self) -> None:
        self.label = "NEGATIVE"
        self.score = 0.9
        self.calls: List[str] = []

    def set(self, label: str, score: float) -> None:
        self.label = label
        self.score = score

    def __call__(self, text: str) -> List[Dict[str, object]]:
        self.calls.append(text)
        return [{"label": self.label, "score": self.score}]


FAKE_PIPELINE = FakeSentimentPipeline()


def _install_transformers_stub() -> None:
    stub = types.ModuleType("transformers")

    def pipeline(task: str, model: str = "", **_: object) -> FakeSentimentPipeline:
        assert task == "sentiment-analysis"
        return FAKE_PIPELINE

    stub.pipeline = pipeline  # type: ignore[attr-defined]
    sys.modules["transformers"] = stub


_install_transformers_stub()


@pytest.fixture
def sentiment() -> FakeSentimentPipeline:
    """Reset the fake to a strongly negative default and hand it to the test."""
    FAKE_PIPELINE.set("NEGATIVE", 0.9)
    FAKE_PIPELINE.calls.clear()
    return FAKE_PIPELINE


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    import main

    return TestClient(main.app)
