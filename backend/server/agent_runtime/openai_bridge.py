"""Route local Agent sessions to the LiteLLM Anthropic Messages adapter."""

from __future__ import annotations

import logging
import os
import secrets
import socket
import threading
from urllib.parse import urlparse

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from openai import OpenAIError

from lib.config.url_utils import ensure_openai_base_url

logger = logging.getLogger(__name__)

_app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
_credentials: dict[str, tuple[str, str]] = {}
_lock = threading.Lock()
_port: int | None = None


def register(base_url: str, api_key: str) -> tuple[str, str]:
    """Return a local endpoint and opaque key bound to this session's credentials."""
    global _port
    with _lock:
        if _port is None:
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            listener.listen(128)
            _port = listener.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(_app, log_level="error", access_log=False))
            threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True).start()
        token = next((key for key, value in _credentials.items() if value == (base_url, api_key)), None)
        if token is None:
            token = secrets.token_urlsafe(32)
            _credentials[token] = (base_url, api_key)
        return f"http://127.0.0.1:{_port}", token


_CHAT_COMPLETIONS = "/chat/completions"
_RESPONSES = "/responses"
_MESSAGE_FIELDS = (
    "container",
    "context_management",
    "metadata",
    "output_config",
    "stop_sequences",
    "system",
    "temperature",
    "thinking",
    "tool_choice",
    "tools",
    "top_k",
    "top_p",
)
_ERROR_TYPES = {
    400: "invalid_request_error",
    401: "authentication_error",
    403: "permission_error",
    404: "not_found_error",
    413: "request_too_large",
    429: "rate_limit_error",
    529: "overloaded_error",
}


def provider_request_url(base_url: str) -> str:
    url = base_url.strip().rstrip("/")
    if urlparse(url).path.endswith((_RESPONSES, _CHAT_COMPLETIONS)):
        return url
    return f"{ensure_openai_base_url(url)}{_CHAT_COMPLETIONS}"


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(
        {"type": "error", "error": {"type": _ERROR_TYPES.get(status, "api_error"), "message": message}},
        status_code=status,
    )


@_app.post("/v1/messages")
async def messages(request: Request, body: dict):
    token = request.headers.get("x-api-key", "") or request.headers.get("authorization", "").removeprefix("Bearer ")
    credential = _credentials.get(token)
    if not credential:
        return _error(401, "Invalid bridge key")
    base_url, api_key = credential
    url = provider_request_url(base_url)
    use_responses = url.endswith(_RESPONSES)
    suffix, provider = (_RESPONSES, "openai") if use_responses else (_CHAT_COMPLETIONS, "custom_openai")

    # Keep the library's catalog and tokenizer lookups local to this installation.
    os.environ.setdefault("LITELLM_OFFLINE_MODE", "true")
    import litellm
    from litellm.anthropic_interface import messages as lite_messages

    litellm.telemetry = False
    litellm.suppress_debug_info = True
    options = {key: body[key] for key in _MESSAGE_FIELDS if key in body}
    if use_responses:
        options["store"] = False
    try:
        result = await lite_messages.acreate(
            model=f"{provider}/{body['model']}",
            messages=body["messages"],
            max_tokens=body.get("max_tokens", 4096),
            stream=body.get("stream", False),
            api_base=url.removesuffix(suffix),
            api_key=api_key,
            timeout=300,
            num_retries=0,
            drop_params=True,
            **options,
        )
    except (OpenAIError, KeyError, TypeError, ValueError) as exc:
        status = getattr(exc, "status_code", None)
        if isinstance(status, int) and 400 <= status <= 599:
            return _error(status, f"OpenAI-compatible request returned HTTP {status}")
        logger.warning("LiteLLM Agent adapter failed (%s)", type(exc).__name__)
        return _error(502, "LiteLLM Agent adapter failed")

    if body.get("stream"):
        return StreamingResponse(result, media_type="text/event-stream")
    return result
