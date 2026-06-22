"""Colmena runner for colmena-bench. CLI: `python -m runner`.

Drives the native `colmena` module (package `colmena-ai`) through its OpenAI
adapter, pointed at the LiteLLM proxy via OPENAI_BASE_URL. Requires the
Colmena base_url patch (merged to develop 2026-06-11) so the factory honours
the env var. See docs/base_url_compatibility.md.
"""
