"""Evidence contract and deterministic verifier for ticket claims.

Nothing in this package reads ticket text, calls a model, or decides a priority. It takes a
structured claim plus evidence exported from Agentic-Payments-Lab and returns a verification
result that a later, application-owned policy may use.
"""
