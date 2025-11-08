"""
Configuration file for ticket prioritization system
"""

# Urgent keywords that indicate critical issues
CRITICAL_KEYWORDS = [
    "urgent", "critical", "emergency", "asap", "immediately",
    "down", "outage", "offline", "crash", "crashed",
    "hack", "hacked", "breach", "security breach", "compromised",
    "data loss", "lost data", "deleted", "cannot access",
    "production", "prod", "live environment",
    "revenue", "losing money", "financial impact",
    "customers affected", "all users", "nobody can"
]

# High priority keywords
HIGH_KEYWORDS = [
    "broken", "not working", "doesn't work", "failed", "failure",
    "error", "bug", "issue", "problem", "trouble",
    "slow", "timeout", "performance", "stuck",
    "cannot", "can't", "unable to", "won't", "doesn't"
]

# Positive keywords (reduce urgency even if other keywords present)
POSITIVE_KEYWORDS = [
    "thank", "thanks", "appreciate", "great", "excellent",
    "love", "excited", "happy", "pleased", "wonderful"
]

# Customer tier multipliers
TIER_MULTIPLIERS = {
    "enterprise": 1.3,
    "premium": 1.15,
    "standard": 1.0,
    "free": 0.85
}

# Scoring weights
WEIGHTS = {
    "sentiment": 0.35,      # 35% weight on sentiment analysis
    "keywords": 0.45,       # 45% weight on keyword detection
    "customer_tier": 0.20   # 20% weight on customer tier
}

# Priority thresholds (final score -> priority level)
PRIORITY_THRESHOLDS = {
    "critical": 0.80,  # Score >= 0.80 → critical
    "high": 0.60,      # Score >= 0.60 → high
    "medium": 0.40,    # Score >= 0.40 → medium
    "low": 0.0         # Score < 0.40 → low
}