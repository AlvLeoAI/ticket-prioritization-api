from fastapi import FastAPI
from pydantic import BaseModel
from transformers import pipeline
from typing import Optional
import logging

# Import our classification logic
from utils import classify_ticket_advanced

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Ticket Prioritization API",
    description="Advanced sentiment analysis API for support ticket urgency classification",
    version="0.2.0"  # Updated version!
)

# Load Hugging Face model
logger.info("Loading sentiment analysis model...")
sentiment_analyzer = pipeline(
    "sentiment-analysis",
    model="distilbert-base-uncased-finetuned-sst-2-english"
)
logger.info("Model loaded successfully!")


# Define request/response models
class TicketRequest(BaseModel):
    ticket_id: Optional[str] = None
    text: str
    customer_tier: Optional[str] = "standard"

    class Config:
        json_schema_extra = {
            "example": {
                "ticket_id": "TKT-001",
                "text": "URGENT! Production system is down and customers cannot checkout!",
                "customer_tier": "enterprise"
            }
        }


class TicketResponse(BaseModel):
    ticket_id: Optional[str]
    priority: str
    confidence: float
    sentiment: str
    sentiment_score: float
    final_score: float
    breakdown: dict


@app.get("/")
async def root():
    return {
        "message": "Ticket Prioritization API v0.2.0",
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
        "version": "0.2.0"
    }


@app.post("/classify-ticket", response_model=TicketResponse)
async def classify_ticket(ticket: TicketRequest):
    """
    Classify a support ticket using advanced multi-dimensional scoring.
    
    Combines:
    - Sentiment analysis (35%)
    - Keyword detection (45%) 
    - Customer tier (20%)
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
        customer_tier=ticket.customer_tier
    )
    
    logger.info(
        f"Ticket {ticket.ticket_id}: {classification['priority'].upper()} "
        f"(score: {classification['final_score']:.3f})"
    )
    
    return TicketResponse(
        ticket_id=ticket.ticket_id,
        priority=classification['priority'],
        confidence=sentiment_score,
        sentiment=sentiment.lower(),
        sentiment_score=sentiment_score,
        final_score=classification['final_score'],
        breakdown=classification['breakdown']
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)