import logging
from enum import Enum
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, field_validator
from transformers import pipeline

# Import our classification logic
from utils import classify_ticket_advanced

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Ticket Prioritization API",
    description="Advanced sentiment analysis API for support ticket urgency classification",
    version="0.3.0"
)

# Load Hugging Face model
logger.info("Loading sentiment analysis model...")
sentiment_analyzer = pipeline(
    "sentiment-analysis",
    model="distilbert-base-uncased-finetuned-sst-2-english"
)
logger.info("Model loaded successfully!")


# Define request/response models
class CustomerTier(str, Enum):
    """Tiers the scoring engine knows about (see TIER_MULTIPLIERS in config.py)."""

    standard = "standard"
    premium = "premium"
    enterprise = "enterprise"
    free = "free"


class TicketRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ticket_id": "TKT-001",
                "text": "URGENT! Production system is down and customers cannot checkout!",
                "customer_tier": "enterprise",
            }
        }
    )

    ticket_id: Optional[str] = None
    text: str
    # Omitting the field defaults to "standard"; an explicit null or unknown tier is a 422.
    customer_tier: CustomerTier = CustomerTier.standard

    @field_validator("customer_tier", mode="before")
    @classmethod
    def _lowercase_tier(cls, value):
        # The scoring engine always lower-cased the tier, so "Enterprise" stays valid.
        return value.lower() if isinstance(value, str) else value


class TicketResponse(BaseModel):
    ticket_id: Optional[str]
    priority: str
    # Renamed from `confidence` in 0.3.0: this is the sentiment model's confidence in its
    # label, not a confidence in the priority.
    sentiment_confidence: float
    sentiment: str
    sentiment_score: float
    final_score: float
    breakdown: dict


@app.get("/")
async def root():
    return {
        "message": "Ticket Prioritization API v0.3.0",
        "status": "running",
        "features": [
            "Multi-dimensional scoring",
            "Keyword detection",
            "Sentiment analysis",
            "Customer tier weighting"
        ],
        "endpoints": {
            "health": "/health",
            "classify": "/classify-ticket",
            "docs": "/docs"
        }
    }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "model_loaded": True,
        "version": "0.3.0"
    }


@app.post("/classify-ticket", response_model=TicketResponse)
def classify_ticket(ticket: TicketRequest):
    """
    Classify a support ticket using multi-dimensional scoring.

    Combines sentiment analysis, keyword detection and a customer-tier multiplier;
    the exact formula is documented in README.md.

    Deliberately a plain `def`: the Hugging Face pipeline call is synchronous and
    CPU-bound, so FastAPI runs this handler in its threadpool instead of blocking
    the event loop.
    """

    # Get sentiment from Hugging Face model
    result = sentiment_analyzer(ticket.text)[0]
    sentiment = result['label']
    sentiment_score = result['score']

    # Use advanced classification
    classification = classify_ticket_advanced(
        text=ticket.text,
        sentiment=sentiment,
        sentiment_confidence=sentiment_score,
        customer_tier=ticket.customer_tier.value
    )
    
    logger.info(
        f"Ticket {ticket.ticket_id}: {classification['priority'].upper()} "
        f"(score: {classification['final_score']:.3f})"
    )
    
    return TicketResponse(
        ticket_id=ticket.ticket_id,
        priority=classification['priority'],
        sentiment_confidence=sentiment_score,
        sentiment=sentiment.lower(),
        sentiment_score=sentiment_score,
        final_score=classification['final_score'],
        breakdown=classification['breakdown']
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)