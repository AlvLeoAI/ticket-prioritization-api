"""Verifier parameters.

These are **placeholders, not policy**. They exist so the verifier has a concrete default and
tests have something to exercise. The real values belong to whoever owns
`docs/priority-policy.md`, and changing them here does not make them policy.
"""

# A grant bundle whose exports were captured more than this many simulation-clock seconds
# apart is reported as `inconsistent_bundle`: its purchases were not observed at one moment,
# so counting across them is unsafe. Placeholder value; see module docstring.
MAX_BUNDLE_SKEW_SECONDS = 300
