"""HTTP contract of the FastAPI app, with the sentiment model stubbed."""

import inspect

import main

TICKET = "URGENT! Production database is down and all customers are affected!"


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_classify_endpoint_is_sync_so_inference_runs_in_threadpool():
    # A plain `def` route is run by FastAPI in a worker thread; an `async def` one would
    # block the event loop for the whole model call.
    assert not inspect.iscoroutinefunction(main.classify_ticket)


def test_classify_happy_path_matches_engine_output(client, sentiment):
    sentiment.set("NEGATIVE", 0.99)
    response = client.post(
        "/classify-ticket",
        json={"ticket_id": "TKT-001", "text": TICKET, "customer_tier": "enterprise"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ticket_id"] == "TKT-001"
    assert body["priority"] == "critical"
    assert body["final_score"] == 0.8443
    assert body["sentiment"] == "negative"
    assert body["sentiment_score"] == 0.99
    assert body["breakdown"]["tier_multiplier"] == 1.3
    assert body["breakdown"]["keywords_detected"]["critical"] == [
        "urgent",
        "down",
        "production",
        "prod",
    ]
    assert sentiment.calls == [TICKET]


def test_confidence_field_is_named_sentiment_confidence(client, sentiment):
    sentiment.set("POSITIVE", 0.8)
    body = client.post("/classify-ticket", json={"text": "hello"}).json()
    assert body["sentiment_confidence"] == 0.8
    assert "confidence" not in body


def test_missing_tier_defaults_to_standard(client, sentiment):
    body = client.post("/classify-ticket", json={"text": "hello"}).json()
    assert body["breakdown"]["tier_multiplier"] == 1.0


def test_null_tier_returns_422(client, sentiment):
    response = client.post("/classify-ticket", json={"text": "hello", "customer_tier": None})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "customer_tier"]
    assert sentiment.calls == []


def test_unknown_tier_returns_422(client, sentiment):
    response = client.post(
        "/classify-ticket", json={"text": "hello", "customer_tier": "platinum"}
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "customer_tier"]


def test_tier_is_case_insensitive_as_before(client, sentiment):
    body = client.post(
        "/classify-ticket", json={"text": "hello", "customer_tier": "Enterprise"}
    ).json()
    assert body["breakdown"]["tier_multiplier"] == 1.3


def test_free_tier_is_still_accepted(client, sentiment):
    body = client.post("/classify-ticket", json={"text": "hello", "customer_tier": "free"}).json()
    assert body["breakdown"]["tier_multiplier"] == 0.85


def test_missing_text_returns_422(client, sentiment):
    response = client.post("/classify-ticket", json={"customer_tier": "standard"})
    assert response.status_code == 422


def test_openapi_lists_tier_enum(client):
    schema = client.get("/openapi.json").json()
    tier = schema["components"]["schemas"]["CustomerTier"]
    assert sorted(tier["enum"]) == ["enterprise", "free", "premium", "standard"]
