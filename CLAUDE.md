# ticket-prioritization-api

Support-ticket triage service under a staged refactor. The original scoring (DistilBERT
sentiment + keyword substring matching + customer-tier multiplier) is frozen as the
`v0-baseline` tag so every later phase can be measured against it. API version 0.3.0.

GitHub: `AlvLeoAI/ticket-prioritization-api` (Portfolio account `AlvLeoAI`).

## Layout

| Path | What it is |
|---|---|
| `main.py` | FastAPI app; builds the HF pipeline at import time; `/classify-ticket`, `/health`, `/` |
| `utils.py`, `config.py` | Baseline scoring engine and its keywords/weights/thresholds (**frozen**) |
| `app.py` | Streamlit demo UI (batch tab is a placeholder) |
| `triage/` | Phase 1a: evidence contract + deterministic verifier (not wired into the API) |
| `eval/` | `cases.jsonl` (unlabeled seed set), `cases.schema.json`, `run_eval.py` |
| `docs/priority-policy.md` | Priority policy, **empty template** (Phase 1 product decision) |
| `docs/evidence-contract.md` | Envelopes, outcomes, reason codes, pinned upstream source |
| `tests/` | pytest suite; HF pipeline stubbed in `conftest.py`; evidence fixtures in `fixtures/evidence/` |

## Commands

```bash
pip install -r requirements-dev.txt      # test + lint deps (no torch/transformers)
ruff check .                             # lint (E, F, I; line-length 100)
pytest -q                                # offline suite; known defects are xfail
python eval/run_eval.py [--json]         # baseline over eval cases (loads real model)
python tests/fixtures/evidence/generate.py   # regenerate evidence fixtures
pip install -r requirements.txt          # full runtime (~250MB model on first API start)
python main.py                           # API on :8000
streamlit run app.py                     # UI on :8501
```

CI (`.github/workflows/ci.yml`, Python 3.11) runs exactly `ruff check .` and `pytest -q`.

## Phases

- **Phase 0 (done):** honesty and robustness. Input validation, characterization tests, CI,
  eval harness.
- **Phase 1a (done):** `triage/` verifier. Structured claim + Agentic-Payments-Lab export →
  `confirmed` / `contradicted` / `unverifiable` with a reason code.
- **Phase 1 (next):** write `docs/priority-policy.md`, then label `eval/cases.jsonl` against it.
- **Phase 2:** LLM extracts structured facts from tickets; deterministic rules from the policy
  decide priority.
- **Phase 3:** human review loop feeding corrections back into the eval set.

## Rules

- **Do not change baseline scoring** (`utils.py`, `config.py`). The characterization tests
  pin it and the known defects are deliberately kept as `xfail`. New behaviour goes in new
  code and is compared against `v0-baseline`.
- **Ticket text is never evidence.** The verifier is a pure function over `(claim, evidence)`:
  no text, no model, no clock, no decisions. It assigns no priority.
- **Policy is not code.** `triage/config.py` values are placeholders; priorities, SLAs and
  labels come from `docs/priority-policy.md`, which the user owns. Don't invent policy.
- **Evidence shape is pinned** to an Agentic-Payments-Lab commit in `triage/source.py`. If
  upstream changes: bump the SHA, update `triage/payments_lab.py`, regenerate fixtures, and
  commit script and JSON together (a test checks they match).
- Tests must stay offline: never let the suite import the real `transformers`.
- README makes no accuracy/latency claims because none are measured. Keep it that way until
  the eval set is labeled.
- Target Python is 3.9 (`ruff target-version`), so avoid 3.10+ syntax like `X | Y` unions
  at runtime.
