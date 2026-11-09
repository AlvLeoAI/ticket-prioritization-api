"""The eval harness runs offline against the seed cases and computes its metrics correctly."""

import json

import pytest

import eval.run_eval as run_eval


def test_seed_cases_are_valid_and_unlabeled():
    cases = run_eval.load_cases(run_eval.DEFAULT_CASES)
    assert len(cases) == 5
    assert all(case["expected_priority"] is None for case in cases)


def test_seed_run_reports_unlabeled_and_skips_metrics(capsys, sentiment):
    # Cases without a sentiment_override go through the (stubbed) pipeline.
    assert run_eval.main([]) == 0
    out = capsys.readouterr().out
    assert "Unlabeled: 5" in out
    assert "No labeled cases" in out


def test_override_holds_sentiment_constant_and_shows_defect_c(sentiment):
    sentiment.set("POSITIVE", 0.99)  # would be used if the override were ignored
    cases = {c["id"]: c for c in run_eval.load_cases(run_eval.DEFAULT_CASES)}
    source = run_eval.SentimentSource()
    plain = run_eval.predict(cases["defect-c-down-plain"], source)
    polite = run_eval.predict(cases["defect-c-down-thanks"], source)
    assert plain["sentiment_source"] == polite["sentiment_source"] == "override"
    assert (plain["predicted"], polite["predicted"]) == ("medium", "low")
    assert sentiment.calls == []


def test_confusion_matrix_and_recall():
    pairs = [
        ("critical", "critical"),
        ("critical", "high"),
        ("low", "low"),
        (None, "medium"),  # unlabeled: excluded
    ]
    matrix = run_eval.confusion_matrix(pairs)
    assert matrix["critical"] == {"critical": 1, "high": 1, "medium": 0, "low": 0}
    assert matrix["low"]["low"] == 1
    assert sum(sum(row.values()) for row in matrix.values()) == 3
    assert run_eval.critical_recall(pairs) == 0.5
    assert run_eval.critical_recall([("low", "low")]) is None


def test_invalid_case_file_is_rejected(tmp_path, capsys):
    bad = tmp_path / "cases.jsonl"
    bad.write_text(
        json.dumps({"id": "x", "text": "t", "customer_tier": "gold", "expected_priority": None})
        + "\n"
    )
    assert run_eval.main(["--cases", str(bad)]) == 2
    assert "customer_tier" in capsys.readouterr().err


@pytest.mark.parametrize(
    "case",
    [
        {"id": "x", "text": "t", "customer_tier": "standard"},  # missing expected_priority
        {"id": "x", "text": "t", "customer_tier": "standard", "expected_priority": "urgent"},
        {"id": "x", "text": "", "customer_tier": "standard", "expected_priority": None},
        {
            "id": "x", "text": "t", "customer_tier": "standard", "expected_priority": None,
            "sentiment_override": {"label": "NEUTRAL", "confidence": 0.5},
        },
    ],
)  # fmt: skip
def test_validate_case_rejects_schema_violations(case):
    with pytest.raises(run_eval.CaseError):
        run_eval.validate_case(case, line_no=1)
