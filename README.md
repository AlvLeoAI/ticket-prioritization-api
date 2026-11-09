# Ticket Priority Classifier

A support-ticket triage service that assigns one of four priority levels (critical, high,
medium, low) by combining a pretrained sentiment model with keyword matching and a
customer-tier multiplier. It ships as a FastAPI service plus a Streamlit demo UI.

![Python](https://img.shields.io/badge/Python-3.9+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.104-009688)
![Streamlit](https://img.shields.io/badge/Streamlit-1.51-FF4B4B)

**Status: demo / baseline.** This is a portfolio project under a staged refactor. The scoring
logic is frozen as the `v0-baseline` tag so that later versions can be measured against it;
see [Known limitations](#known-limitations) and [Roadmap](#roadmap) before relying on any
output. There are no accuracy, latency or throughput figures because none have been measured.

## What it does

- **Sentiment analysis** with `distilbert-base-uncased-finetuned-sst-2-english` (Hugging Face
  Transformers). Negative sentiment raises urgency.
- **Keyword detection**: case-insensitive substring matching against three lists in
  `config.py` (28 critical, 19 high-priority, 10 positive keywords).
- **Customer-tier multiplier** for `standard`, `premium`, `enterprise` and `free`.
- **Scoring breakdown** in every response, so you can see which component drove the result.
- **Streamlit UI** for single-ticket classification with pre-loaded examples.
- **OpenAPI docs** at `/docs`.

## Quick start

Requires Python 3.9+. The first API start downloads the ~250 MB sentiment model and needs
network access; it is cached afterwards.

```bash
git clone https://github.com/AlvLeoAI/ticket-prioritization-api.git
cd ticket-prioritization-api
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Start the API, then the UI in a second terminal:

```bash
python main.py                # http://localhost:8000  (docs at /docs)
```

```bash
streamlit run app.py          # http://localhost:8501
```

## API

### `POST /classify-ticket`

Request:

```json
{
  "ticket_id": "TKT-001",
  "text": "URGENT! Production database is down and customers are affected!",
  "customer_tier": "enterprise"
}
```

| Field | Type | Notes |
|---|---|---|
| `ticket_id` | string, optional | Echoed back. |
| `text` | string, required | The ticket body. |
| `customer_tier` | enum, optional | One of `standard`, `premium`, `enterprise`, `free`; case-insensitive. Defaults to `standard` when omitted. An explicit `null` or any other value returns **422**. |

Response (values shown for the model returning `NEGATIVE` with confidence 0.99; this exact
case is pinned in `tests/test_api.py`):

```json
{
  "ticket_id": "TKT-001",
  "priority": "critical",
  "sentiment_confidence": 0.99,
  "sentiment": "negative",
  "sentiment_score": 0.99,
  "final_score": 0.8443,
  "breakdown": {
    "sentiment_score": 0.99,
    "keyword_score": 1.0,
    "tier_multiplier": 1.3,
    "keywords_detected": {
      "critical": ["urgent", "down", "production", "prod"],
      "high": [],
      "positive": []
    }
  }
}
```

`sentiment_confidence` and `sentiment_score` are both the sentiment model's confidence in
its own label. Neither is a confidence in the priority; the system has no such measure.

### Other endpoints

- `GET /health` — liveness check.
- `GET /` — version and endpoint list.

### API changes in 0.3.0

- **Breaking:** the response field `confidence` is renamed `sentiment_confidence`. It was
  always the sentiment model's confidence, and the old name suggested it described the priority.
- `customer_tier` is validated. Unknown values and `null` return 422 instead of being
  silently scored as `standard` (unknown values) or crashing with a 500 (`null`).

```python
import requests

payload = {"ticket_id": "TKT-001", "text": "Production database is down!", "customer_tier": "enterprise"}
result = requests.post("http://localhost:8000/classify-ticket", json=payload, timeout=30).json()
print(result["priority"], result["final_score"])
```

## Scoring formula (as implemented)

This is the exact computation in `utils.py` and `config.py`; the characterization tests in
`tests/test_scoring_characterization.py` pin it.

```
sentiment_score = confidence          if the model's label is NEGATIVE
                = 1 - confidence      if the label is POSITIVE

keyword_score   = clamp[0, 1]( min(0.35 * n_critical, 1.0)
                             + min(0.15 * n_high,     0.5)
                             - min(0.10 * n_positive, 0.3) )

base_score      = 0.35 * sentiment_score + 0.45 * keyword_score          # max 0.80

final_score     = clamp[0, 1]( base_score * (1 + (tier_multiplier - 1) * 0.20) )

priority        = critical  if final_score >= 0.80
                  high      if final_score >= 0.60
                  medium    if final_score >= 0.40
                  low       otherwise
```

`n_critical`, `n_high` and `n_positive` are the number of list entries found as substrings of
the lower-cased text. Tier multipliers are `enterprise` 1.3, `premium` 1.15, `standard` 1.0,
`free` 0.85.

Two consequences worth knowing:

- **The tier effect is multiplicative and damped.** The tier is not a 20 % additive term.
  The multiplier is scaled by 0.20 before it is applied, so `enterprise` multiplies the base
  score by 1.06, `premium` by 1.03 and `free` by 0.97.
- **The base score tops out at 0.80**, exactly the critical threshold. A `standard` ticket
  reaches critical only if the model's confidence is exactly 1.0, which it does not return in
  practice; a `free` ticket cannot reach critical at all (maximum 0.776).

## Known limitations

Documented, reproduced in the test suite as `xfail` cases, and kept unchanged on purpose so
the baseline is measurable. Do not use this version for real triage.

1. **Substring matching produces false positives.** `"download the product documentation"`
   is flagged for two critical keywords: `down` (inside *download*) and `prod` (inside
   *product*).
2. **Overlapping keywords double-count.** `"production"` matches both `production` and
   `prod`; `"thanks"` matches both `thank` and `thanks`.
3. **Politeness lowers priority.** With sentiment held constant (NEGATIVE, 0.9), `"The
   application is down."` is *medium* (0.4725) and `"The application is down. Thanks!"` is
   *low* (0.3825).
4. **Free and standard tiers effectively cannot be critical.** See the formula notes above.
5. **Reported score and priority can disagree at a threshold.** `final_score` is rounded to
   four decimals for the response, but the priority is derived from the unrounded value, so a
   response can show `0.8` with priority `high`.
6. **The sentiment model was trained on movie reviews** (SST-2), not support tickets.
7. **No negation handling** (`"not urgent"` counts as urgent), no multi-language support.
8. **Operational gaps:** no authentication, rate limiting, request-size limits or
   persistence. The Streamlit "Batch Classification" tab is a placeholder.
9. **Nothing is measured.** There is no labeled dataset yet, so accuracy, precision/recall
   and latency are unknown.

## Roadmap

The refactor is staged so that each step can be checked against the previous one.

- **Phase 0 (this version): honesty and robustness.** Baseline frozen as `v0-baseline`;
  input validation; characterization tests; CI; eval harness with an empty policy template.
- **Phase 1: written priority policy and a labeled eval set.** Fill in
  `docs/priority-policy.md`, then label `eval/cases.jsonl` against it and grow the set.
  Only then can the baseline's quality be stated.
- **Phase 2: LLM-based structured extraction with a deterministic policy.** A model extracts
  structured facts from the ticket (what is broken, who is affected, …); the priority is then
  decided by rules written from the policy, not by the model.
- **Phase 3: human review.** A review loop for low-confidence or high-impact cases, feeding
  corrections back into the eval set.

## Development

```bash
pip install -r requirements-dev.txt   # test and lint deps; does not install torch
ruff check .
pytest -q
```

The test suite stubs the Hugging Face pipeline (`tests/conftest.py`), so it runs offline and
never downloads the model. CI (`.github/workflows/ci.yml`) runs the same two commands.

To run the baseline over the eval cases:

```bash
python eval/run_eval.py            # loads the real model for cases without a sentiment_override
python eval/run_eval.py --json
```

`eval/cases.jsonl` currently holds only the known-defect cases, with `expected_priority`
set to `null`. Labels will be added once the priority policy is written.

## Project structure

```
ticket-prioritization-api/
├── main.py                     # FastAPI application
├── app.py                      # Streamlit web interface
├── utils.py                    # Scoring engine (frozen baseline)
├── config.py                   # Keyword lists, multipliers, weights, thresholds
├── requirements.txt            # Runtime dependencies
├── requirements-dev.txt        # Test and lint dependencies
├── tests/                      # pytest suite (HF pipeline stubbed)
├── eval/
│   ├── cases.schema.json       # Schema for one eval case
│   ├── cases.jsonl             # Eval cases (unlabeled seed set)
│   └── run_eval.py             # Confusion matrix + critical-class recall
├── docs/priority-policy.md     # Priority policy (empty template)
└── .github/workflows/ci.yml    # ruff + pytest
```

## Configuration

Keyword lists, tier multipliers, weights and thresholds live in `config.py`. Changing them
changes the baseline; if you do, re-run the characterization tests and the eval harness.

## Author

<!-- TODO: rewrite this section. -->

**Alvaro**

## License

MIT — see [LICENSE](LICENSE).
