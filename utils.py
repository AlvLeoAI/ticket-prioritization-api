"""
Utility functions for ticket classification
"""
import re
from typing import Dict, List, Tuple
from config import (
    CRITICAL_KEYWORDS, HIGH_KEYWORDS, POSITIVE_KEYWORDS,
    TIER_MULTIPLIERS, WEIGHTS, PRIORITY_THRESHOLDS
)


def detect_keywords(text: str) -> Dict[str, any]:
    """
    Detect presence of urgent, high-priority, and positive keywords.
    Returns counts and lists of matched keywords.
    """
    text_lower = text.lower()
    
    # Find critical keywords
    critical_found = [kw for kw in CRITICAL_KEYWORDS if kw in text_lower]
    
    # Find high priority keywords
    high_found = [kw for kw in HIGH_KEYWORDS if kw in text_lower]
    
    # Find positive keywords (these reduce urgency)
    positive_found = [kw for kw in POSITIVE_KEYWORDS if kw in text_lower]
    
    return {
        "critical_keywords": critical_found,
        "critical_count": len(critical_found),
        "high_keywords": high_found,
        "high_count": len(high_found),
        "positive_keywords": positive_found,
        "positive_count": len(positive_found),
        "total_urgent": len(critical_found) + len(high_found)
    }


def calculate_keyword_score(keyword_data: Dict) -> float:
    """
    Calculate a score based on keyword detection (0.0 to 1.0).
    Critical keywords have more weight than high keywords.
    Positive keywords reduce the score.
    """
    # Base score from keywords
    critical_score = min(keyword_data["critical_count"] * 0.35, 1.0)
    high_score = min(keyword_data["high_count"] * 0.15, 0.5)
    
    # Positive keywords reduce urgency
    positive_penalty = min(keyword_data["positive_count"] * 0.1, 0.3)
    
    # Calculate final keyword score
    keyword_score = critical_score + high_score - positive_penalty
    
    # Clamp between 0 and 1
    return max(0.0, min(1.0, keyword_score))


def calculate_sentiment_score(sentiment: str, confidence: float) -> float:
    """
    Convert sentiment analysis result to a score (0.0 to 1.0).
    Negative sentiment = higher urgency.
    """
    if sentiment.upper() == "NEGATIVE":
        # Negative sentiment increases urgency
        return confidence
    else:
        # Positive sentiment decreases urgency
        return 1.0 - confidence


def get_tier_multiplier(customer_tier: str) -> float:
    """Get the priority multiplier for a customer tier."""
    return TIER_MULTIPLIERS.get(customer_tier.lower(), 1.0)


def calculate_final_score(
    sentiment_score: float,
    keyword_score: float,
    tier_multiplier: float
) -> float:
    """
    Calculate final priority score using weighted average.
    Returns a score between 0.0 and 1.0.
    """
    # Weighted combination
    base_score = (
        sentiment_score * WEIGHTS["sentiment"] +
        keyword_score * WEIGHTS["keywords"]
    )
    
    # Apply tier multiplier
    final_score = base_score * (1 + (tier_multiplier - 1) * WEIGHTS["customer_tier"])
    
    # Clamp between 0 and 1
    return max(0.0, min(1.0, final_score))


def score_to_priority(score: float) -> str:
    """
    Convert final score to priority level.
    """
    if score >= PRIORITY_THRESHOLDS["critical"]:
        return "critical"
    elif score >= PRIORITY_THRESHOLDS["high"]:
        return "high"
    elif score >= PRIORITY_THRESHOLDS["medium"]:
        return "medium"
    else:
        return "low"


def classify_ticket_advanced(
    text: str,
    sentiment: str,
    sentiment_confidence: float,
    customer_tier: str
) -> Dict:
    """
    Main classification function using advanced multi-dimensional scoring.
    
    Returns a dict with:
    - priority: final priority level
    - final_score: combined score (0-1)
    - breakdown: detailed scoring breakdown
    """
    # Step 1: Detect keywords
    keyword_data = detect_keywords(text)
    
    # Step 2: Calculate individual scores
    sentiment_score = calculate_sentiment_score(sentiment, sentiment_confidence)
    keyword_score = calculate_keyword_score(keyword_data)
    tier_multiplier = get_tier_multiplier(customer_tier)
    
    # Step 3: Calculate final score
    final_score = calculate_final_score(
        sentiment_score,
        keyword_score,
        tier_multiplier
    )
    
    # Step 4: Determine priority
    priority = score_to_priority(final_score)
    
    # Return detailed breakdown
    return {
        "priority": priority,
        "final_score": round(final_score, 4),
        "breakdown": {
            "sentiment_score": round(sentiment_score, 4),
            "keyword_score": round(keyword_score, 4),
            "tier_multiplier": round(tier_multiplier, 2),
            "keywords_detected": {
                "critical": keyword_data["critical_keywords"],
                "high": keyword_data["high_keywords"],
                "positive": keyword_data["positive_keywords"]
            }
        }
    }