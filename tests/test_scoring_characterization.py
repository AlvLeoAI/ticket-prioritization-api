"""Characterization tests for the frozen baseline (tag `v0-baseline`).

These tests pin the scoring engine's *current* behaviour, right or wrong, so later phases can
show exactly what they changed. Known defects are marked `xfail(strict=True)`: each of those
tests asserts the behaviour we would want, fails today, and will start passing (and so fail
the suite, flagging the test for review) the moment the defect is fixed.
"""

import pytest

from config import PRIORITY_THRESHOLDS, TIER_MULTIPLIERS, WEIGHTS
from utils import (
    calculate_final_score,
    calculate_keyword_score,
    calculate_sentiment_score,
    classify_ticket_advanced,
    detect_keywords,
    get_tier_multiplier,
    score_to_priority,
)

PRIORITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


# --- formula, exactly as implemented ---------------------------------------------------


def test_weights_and_thresholds_are_the_documented_ones():
    assert WEIGHTS == {"sentiment": 0.35, "keywords": 0.45, "customer_tier": 0.20}
    assert PRIORITY_THRESHOLDS == {"critical": 0.80, "high": 0.60, "medium": 0.40, "low": 0.0}
    assert TIER_MULTIPLIERS == {"enterprise": 1.3, "premium": 1.15, "standard": 1.0, "free": 0.85}


def test_sentiment_score_is_negative_confidence_or_its_complement():
    assert calculate_sentiment_score("NEGATIVE", 0.9) == 0.9
    assert calculate_sentiment_score("negative", 0.9) == 0.9
    assert calculate_sentiment_score("POSITIVE", 0.9) == pytest.approx(0.1)


def test_keyword_score_is_capped_sum_minus_capped_penalty():
    def score(critical, high, positive):
        return calculate_keyword_score(
            {"critical_count": critical, "high_count": high, "positive_count": positive}
        )

    assert score(1, 0, 0) == pytest.approx(0.35)
    assert score(3, 0, 0) == pytest.approx(1.0)  # 0.35 per critical keyword, capped at 1.0
    assert score(4, 0, 0) == pytest.approx(1.0)
    assert score(0, 1, 0) == pytest.approx(0.15)
    assert score(0, 5, 0) == pytest.approx(0.5)  # 0.15 per high keyword, capped at 0.5
    assert score(0, 0, 1) == pytest.approx(0.0)  # penalty is clamped at 0
    assert score(3, 0, 5) == pytest.approx(0.7)  # 0.10 per positive keyword, capped at 0.3


@pytest.mark.parametrize(
    ("tier", "effective_factor"),
    [("enterprise", 1.06), ("premium", 1.03), ("standard", 1.0), ("free", 0.97)],
)
def test_tier_multiplier_is_damped_to_a_few_percent(tier, effective_factor):
    # final = base * (1 + (multiplier - 1) * 0.20): the "1.3x" enterprise tier moves the
    # score by 6%, not 30%. This is the documented formula, not a separate 20% term.
    base = 0.5
    final = calculate_final_score(
        sentiment_score=1.0, keyword_score=0.0, tier_multiplier=get_tier_multiplier(tier)
    )
    assert final == pytest.approx(0.35 * effective_factor)
    assert calculate_final_score(base, base, get_tier_multiplier(tier)) == pytest.approx(
        base * 0.8 * effective_factor
    )


def test_unknown_tier_falls_back_to_multiplier_1_inside_the_engine():
    # The API now rejects unknown tiers with 422; the engine itself still has this fallback.
    assert get_tier_multiplier("platinum") == 1.0
    assert get_tier_multiplier("ENTERPRISE") == 1.3


@pytest.mark.parametrize(
    ("score", "priority"),
    [
        (0.80, "critical"),
        (0.7999, "high"),
        (0.60, "high"),
        (0.5999, "medium"),
        (0.40, "medium"),
        (0.3999, "low"),
        (0.0, "low"),
    ],
)
def test_thresholds_are_inclusive_lower_bounds(score, priority):
    assert score_to_priority(score) == priority


# --- end-to-end snapshots of the baseline -----------------------------------------------


@pytest.mark.parametrize(
    ("text", "label", "confidence", "tier", "priority", "final_score"),
    [
        (
            "URGENT! Production database is down and all customers are affected! "
            "We're losing revenue every minute!",
            "NEGATIVE", 0.99, "enterprise", "critical", 0.8443,
        ),
        (
            "We have a security breach. Hackers may have compromised customer data. "
            "Need immediate help!",
            "NEGATIVE", 0.98, "premium", "critical", 0.8168,
        ),
        (
            "I can't login to my account. This is frustrating and I need access soon.",
            "NEGATIVE", 0.95, "standard", "low", 0.4,
        ),
        (
            "Hello! I have a question about changing my profile picture. Thanks for your help!",
            "POSITIVE", 0.99, "standard", "low", 0.0035,
        ),
        (
            "I'm urgently excited about this new feature! Thanks so much for the amazing update!",
            "POSITIVE", 0.99, "premium", "low", 0.0268,
        ),
    ],
)  # fmt: skip
def test_baseline_snapshots(text, label, confidence, tier, priority, final_score):
    result = classify_ticket_advanced(text, label, confidence, tier)
    assert (result["priority"], result["final_score"]) == (priority, final_score)


# --- known defects (xfail: these assert the desired behaviour) --------------------------


@pytest.mark.xfail(
    strict=True,
    reason="Defect (a): substring matching flags 'down' inside 'download' and 'prod' inside "
    "'product', so a documentation request scores two critical keywords.",
)
def test_defect_a_download_product_documentation_has_no_critical_keywords():
    assert detect_keywords("download the product documentation")["critical_keywords"] == []


@pytest.mark.xfail(
    strict=True,
    reason="Defect (b): 'production' also matches the shorter keyword 'prod', counting one "
    "word as two critical keywords.",
)
def test_defect_b_production_matches_once():
    assert detect_keywords("production")["critical_keywords"] == ["production"]


@pytest.mark.xfail(
    strict=True,
    reason="Defect (b): 'thanks' matches both 'thank' and 'thanks', doubling the positive "
    "penalty for one word.",
)
def test_defect_b_thanks_matches_once():
    assert detect_keywords("thanks")["positive_keywords"] == ["thanks"]


@pytest.mark.xfail(
    strict=True,
    reason="Defect (c): with sentiment held at NEGATIVE 0.9, appending 'Thanks!' to 'The "
    "application is down.' drops the priority from medium (0.4725) to low (0.3825).",
)
def test_defect_c_politeness_must_not_lower_priority():
    plain = classify_ticket_advanced("The application is down.", "NEGATIVE", 0.9, "standard")
    polite = classify_ticket_advanced(
        "The application is down. Thanks!", "NEGATIVE", 0.9, "standard"
    )
    assert PRIORITY_RANK[polite["priority"]] >= PRIORITY_RANK[plain["priority"]]


@pytest.mark.xfail(
    strict=True,
    reason="Defect (d): the maximum reachable score for a standard-tier ticket is "
    "0.35*confidence + 0.45; it only reaches the 0.80 critical threshold if the sentiment "
    "confidence is exactly 1.0, which the model never returns.",
)
def test_defect_d_standard_tier_can_reach_critical():
    result = classify_ticket_advanced(
        "urgent critical emergency", "NEGATIVE", 0.9999, "standard"
    )
    assert result["breakdown"]["keyword_score"] == 1.0  # keywords are saturated
    assert result["priority"] == "critical"


@pytest.mark.xfail(
    strict=True,
    reason="Defect (d): a free-tier ticket tops out at 0.80 * 0.97 = 0.776 even with "
    "saturated keywords and sentiment confidence 1.0, so it can never be critical.",
)
def test_defect_d_free_tier_can_reach_critical():
    result = classify_ticket_advanced("urgent critical emergency", "NEGATIVE", 1.0, "free")
    assert result["breakdown"]["keyword_score"] == 1.0
    assert result["priority"] == "critical"


@pytest.mark.xfail(
    strict=True,
    reason="Found during Phase 0: `final_score` is rounded to 4 decimals for the response but "
    "the priority is derived from the unrounded value, so a response can report 0.8 with "
    "priority 'high'.",
)
def test_reported_score_and_priority_agree_at_the_threshold():
    result = classify_ticket_advanced(
        "urgent critical emergency", "NEGATIVE", 0.9999, "standard"
    )
    assert result["final_score"] == 0.8
    assert score_to_priority(result["final_score"]) == result["priority"]
