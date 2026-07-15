"""
The one Anthropic client the agents share.

Previously each agent built its own `httpx.Client(verify=False)`, which turns off
TLS certificate verification for every Claude call — acceptable as a local
workaround for a corporate proxy that re-signs TLS with an internal CA, but not
something that should ever reach a deployed environment.

So verification is ON by default here and must be disabled explicitly:

    ANTHROPIC_SSL_VERIFY=0     # local dev behind a TLS-intercepting proxy

The better local fix is to leave verification on and point httpx at the
corporate CA bundle instead:

    SSL_CERT_FILE=/path/to/corporate-ca.pem

Timeouts matter as much as TLS: without one, a hung Claude call would hold a
visitor at the gate indefinitely. Callers treat a timeout as "couldn't decide"
and fall back to a human (see pipeline._safe_agent).
"""

import os
import sys

import anthropic
import httpx

from backend.config import LLM_MAX_RETRIES, LLM_TIMEOUT_SECONDS

_FALSEY = {"0", "false", "no", "off"}

# Secure by default: only an explicit falsey value disables verification.
VERIFY_SSL = os.getenv("ANTHROPIC_SSL_VERIFY", "1").strip().lower() not in _FALSEY

if not VERIFY_SSL:
    print(
        "[llm] WARNING: TLS verification is DISABLED for Anthropic calls "
        "(ANTHROPIC_SSL_VERIFY=0). Local development only — never deploy this.",
        file=sys.stderr,
    )

_http_client = httpx.Client(verify=VERIFY_SSL, timeout=LLM_TIMEOUT_SECONDS)

client = anthropic.Anthropic(
    http_client=_http_client,
    timeout=LLM_TIMEOUT_SECONDS,
    max_retries=LLM_MAX_RETRIES,
)
