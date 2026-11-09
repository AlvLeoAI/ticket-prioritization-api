"""Run the baseline classifier over eval/cases.jsonl and report how it did.

Usage:
    python eval/run_eval.py [--cases PATH] [--json]

For each case the script predicts a priority with the scoring engine in `utils.py`. The
sentiment comes from the case's `sentiment_override` when present, otherwise from the real
Hugging Face pipeline (loaded lazily, only if some case needs it).

The report has three parts:
  * one line per case (expected vs predicted);
  * a confusion matrix over the cases that have an `expected_priority`;
  * recall on the critical class, i.e. the share of truly critical tickets the baseline
    caught. Missing a critical ticket is the costliest error, so this number gets its own line.

Cases whose `expected_priority` is null are listed but excluded from the metrics. The script
never invents a label.
"""

import argparse
import json
import os
import sys
from typing import Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import classify_ticket_advanced  # noqa: E402

PRIORITIES = ["critical", "high", "medium", "low"]
TIERS = {"standard", "premium", "enterprise", "free"}
DEFAULT_CASES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cases.jsonl")

Pair = Tuple[Optional[str], str]  # (expected, predicted)


class CaseError(ValueError):
    pass


def validate_case(case: Dict, line_no: int) -> None:
    """Mirror of eval/cases.schema.json, kept dependency-free."""
    allowed = {"id", "text", "customer_tier", "expected_priority", "sentiment_override", "notes"}
    extra = set(case) - allowed
    if extra:
        raise CaseError(f"line {line_no}: unknown fields {sorted(extra)}")
    for key in ("id", "text", "customer_tier", "expected_priority"):
        if key not in case:
            raise CaseError(f"line {line_no}: missing required field {key!r}")
    if not isinstance(case["id"], str) or not case["id"]:
        raise CaseError(f"line {line_no}: id must be a non-empty string")
    if not isinstance(case["text"], str) or not case["text"]:
        raise CaseError(f"line {line_no}: text must be a non-empty string")
    if case["customer_tier"] not in TIERS:
        raise CaseError(f"line {line_no}: customer_tier must be one of {sorted(TIERS)}")
    if case["expected_priority"] is not None and case["expected_priority"] not in PRIORITIES:
        raise CaseError(f"line {line_no}: expected_priority must be null or one of {PRIORITIES}")
    override = case.get("sentiment_override")
    if override is not None:
        if set(override) != {"label", "confidence"}:
            raise CaseError(f"line {line_no}: sentiment_override needs exactly label, confidence")
        if override["label"] not in ("NEGATIVE", "POSITIVE"):
            raise CaseError(f"line {line_no}: sentiment_override.label must be NEGATIVE/POSITIVE")
        confidence = override["confidence"]
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise CaseError(f"line {line_no}: sentiment_override.confidence must be in [0, 1]")


def load_cases(path: str) -> List[Dict]:
    cases: List[Dict] = []
    seen = set()
    with open(path, encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            case = json.loads(line)
            validate_case(case, line_no)
            if case["id"] in seen:
                raise CaseError(f"line {line_no}: duplicate id {case['id']!r}")
            seen.add(case["id"])
            cases.append(case)
    return cases


class SentimentSource:
    """Returns (label, confidence) for a case, loading the HF model only if needed."""

    def __init__(self) -> None:
        self._pipeline = None

    def for_case(self, case: Dict) -> Tuple[str, float]:
        override = case.get("sentiment_override")
        if override is not None:
            return override["label"], float(override["confidence"])
        if self._pipeline is None:
            from transformers import pipeline

            self._pipeline = pipeline(
                "sentiment-analysis", model="distilbert-base-uncased-finetuned-sst-2-english"
            )
        result = self._pipeline(case["text"])[0]
        return result["label"], float(result["score"])


def predict(case: Dict, sentiment: SentimentSource) -> Dict:
    label, confidence = sentiment.for_case(case)
    result = classify_ticket_advanced(case["text"], label, confidence, case["customer_tier"])
    return {
        "id": case["id"],
        "expected": case["expected_priority"],
        "predicted": result["priority"],
        "final_score": result["final_score"],
        "sentiment": {"label": label, "confidence": confidence},
        "sentiment_source": "override" if case.get("sentiment_override") else "model",
        "breakdown": result["breakdown"],
    }


def confusion_matrix(pairs: Iterable[Pair]) -> Dict[str, Dict[str, int]]:
    """rows = expected, columns = predicted; unlabeled pairs are skipped."""
    matrix = {row: {col: 0 for col in PRIORITIES} for row in PRIORITIES}
    for expected, predicted in pairs:
        if expected is not None:
            matrix[expected][predicted] += 1
    return matrix


def critical_recall(pairs: Iterable[Pair]) -> Optional[float]:
    """Share of expected-critical cases predicted critical. None when there are none."""
    labeled_critical = [p for e, p in pairs if e == "critical"]
    if not labeled_critical:
        return None
    return sum(1 for p in labeled_critical if p == "critical") / len(labeled_critical)


def format_report(predictions: List[Dict]) -> str:
    pairs: List[Pair] = [(p["expected"], p["predicted"]) for p in predictions]
    labeled = [p for p in pairs if p[0] is not None]
    lines = ["Per case", "-" * 72]
    for p in predictions:
        expected = p["expected"] or "(unlabeled)"
        lines.append(
            f"{p['id']:<36} expected={expected:<12} predicted={p['predicted']:<9} "
            f"score={p['final_score']:.4f} sentiment={p['sentiment_source']}"
        )
    lines += ["", f"Labeled cases: {len(labeled)}   Unlabeled: {len(pairs) - len(labeled)}", ""]
    if not labeled:
        lines.append("No labeled cases: confusion matrix and recall are not computed.")
        return "\n".join(lines)

    matrix = confusion_matrix(pairs)
    corner = "expected \\ predicted"
    header = f"{corner:<22}" + "".join(f"{c:>10}" for c in PRIORITIES)
    lines += ["Confusion matrix", "-" * 72, header]
    for row in PRIORITIES:
        lines.append(f"{row:<22}" + "".join(f"{matrix[row][col]:>10}" for col in PRIORITIES))
    correct = sum(matrix[p][p] for p in PRIORITIES)
    lines += ["", f"Accuracy (labeled): {correct}/{len(labeled)} = {correct / len(labeled):.3f}"]
    recall = critical_recall(pairs)
    recall_text = "n/a (no expected-critical cases)" if recall is None else f"{recall:.3f}"
    lines.append(f"Critical-class recall: {recall_text}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", default=DEFAULT_CASES, help="path to a cases .jsonl file")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args(argv)

    try:
        cases = load_cases(args.cases)
    except (CaseError, json.JSONDecodeError) as exc:
        print(f"Invalid cases file: {exc}", file=sys.stderr)
        return 2

    sentiment = SentimentSource()
    predictions = [predict(case, sentiment) for case in cases]
    pairs: List[Pair] = [(p["expected"], p["predicted"]) for p in predictions]

    if args.json:
        print(
            json.dumps(
                {
                    "predictions": predictions,
                    "confusion_matrix": confusion_matrix(pairs),
                    "critical_recall": critical_recall(pairs),
                },
                indent=2,
            )
        )
    else:
        print(format_report(predictions))
    return 0


if __name__ == "__main__":
    sys.exit(main())
