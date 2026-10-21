"""Thin client for a local Ollama server (HTTP API). No fabricated fallbacks: failures raise."""
import json
import logging
import re

import httpx

from app import config
from app.errors import BadGateway, ServiceUnavailable

logger = logging.getLogger("synuser.ollama")

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _clean(text: str) -> str:
    return _THINK_RE.sub("", text or "").strip()


def _extract_json(text: str):
    """Parse a JSON object from model output (tolerates code fences / leading prose)."""
    text = _clean(text)
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


def status() -> dict:
    """Connectivity + model availability (used by /health/ollama). Never raises."""
    base = {"base_url": config.OLLAMA_BASE_URL, "model": config.OLLAMA_MODEL}
    try:
        r = httpx.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=5)
        r.raise_for_status()
        names = [m.get("name", "") for m in r.json().get("models", [])]
    except Exception as exc:
        return {**base, "reachable": False, "model_installed": False, "installed_models": [],
                "detail": f"Cannot reach Ollama ({type(exc).__name__})."}
    wanted = config.OLLAMA_MODEL
    installed = wanted in names or (":" not in wanted and any(n.split(":")[0] == wanted for n in names))
    return {**base, "reachable": True, "model_installed": installed, "installed_models": names,
            "detail": "ok" if installed else f"Model '{wanted}' is not installed. Run: ollama pull {wanted}"}


def ensure_ready() -> None:
    st = status()
    if not st["reachable"]:
        raise ServiceUnavailable(
            "The local AI service is unavailable. Start Ollama and verify that the configured "
            f"model ({config.OLLAMA_MODEL}) is installed.", code="ollama_unavailable")
    if not st["model_installed"]:
        raise ServiceUnavailable(
            f"The model '{config.OLLAMA_MODEL}' is not installed in Ollama. "
            f"Run: ollama pull {config.OLLAMA_MODEL}", code="ollama_model_missing")


def _chat(messages: list[dict], *, json_mode: bool, temperature: float, max_tokens: int) -> str:
    payload = {
        "model": config.OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    if json_mode:
        payload["format"] = "json"
    try:
        r = httpx.post(f"{config.OLLAMA_BASE_URL}/api/chat", json=payload,
                       timeout=config.OLLAMA_TIMEOUT_SECONDS)
    except httpx.TimeoutException as exc:
        raise ServiceUnavailable(
            f"The local AI model timed out after {int(config.OLLAMA_TIMEOUT_SECONDS)}s.",
            code="ollama_timeout") from exc
    except httpx.HTTPError as exc:
        raise ServiceUnavailable(
            "The local AI service is unavailable. Start Ollama and verify that the configured "
            "model is installed.", code="ollama_unavailable") from exc
    if r.status_code == 404:
        raise ServiceUnavailable(
            f"The model '{config.OLLAMA_MODEL}' is not installed in Ollama. "
            f"Run: ollama pull {config.OLLAMA_MODEL}", code="ollama_model_missing")
    if r.status_code >= 400:
        raise ServiceUnavailable(
            f"The local AI service returned an error (HTTP {r.status_code}). Check the Ollama log and that the "
            f"model '{config.OLLAMA_MODEL}' can run on this machine.", code="ollama_error")
    try:
        return _clean(r.json().get("message", {}).get("content", ""))
    except ValueError as exc:
        raise BadGateway("Ollama returned an unreadable response.") from exc


def generate_text(system: str | None, prompt: str, *, history: list[dict] | None = None,
                  temperature: float = 0.5, max_tokens: int = 400) -> str:
    """Plain-text completion. Retries only when the output is empty. Raises on failure."""
    messages = ([{"role": "system", "content": system}] if system else []) + (history or []) \
        + [{"role": "user", "content": prompt}]
    for attempt in range(config.OLLAMA_MAX_ATTEMPTS):
        text = _chat(messages, json_mode=False, temperature=temperature, max_tokens=max_tokens)
        if text:
            return text
        logger.warning("Empty model output (attempt %s)", attempt + 1)
    raise BadGateway("The model returned an empty answer.")


def generate_json(prompt: str, *, system: str | None = None, temperature: float = 0.4,
                  max_tokens: int = 900) -> dict:
    """JSON-mode completion; retries (bounded) on invalid/non-object JSON."""
    messages = ([{"role": "system", "content": system}] if system else []) + \
        [{"role": "user", "content": prompt}]
    last = "no output"
    for attempt in range(config.OLLAMA_MAX_ATTEMPTS):
        text = _chat(messages, json_mode=True, temperature=temperature, max_tokens=max_tokens)
        try:
            data = _extract_json(text)
            if isinstance(data, dict):
                return data
            last = "JSON was not an object"
        except (json.JSONDecodeError, ValueError):
            last = "invalid or truncated JSON"
        logger.warning("Model JSON problem (attempt %s): %s", attempt + 1, last)
    raise BadGateway(f"The model did not return usable JSON ({last}).")
