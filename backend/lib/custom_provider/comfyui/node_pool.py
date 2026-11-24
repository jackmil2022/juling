"""Poll and reserve ComfyUI nodes before dispatching local generation tasks."""

import asyncio
import logging
from collections import Counter
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import monotonic
from typing import Any

import httpx

from lib.backends.artifact_download_guard import (
    ArtifactDestinationRejectedError,
    artifact_http_client,
)

from .comfyui_client import ComfyuiClient, normalize_comfyui_base_url
from .failures import ComfyuiError

logger = logging.getLogger(__name__)
_PROBE_TIMEOUT_SECONDS = 3.0
_SAMPLE_MAX_AGE_SECONDS = 5.0
_next_node: dict[str, int] = {}


def comfyui_node_urls(base_url: str, extras: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(normalize_comfyui_base_url(url) for url in (base_url, *extras) if url.strip()))


async def choose_comfyui_node(
    provider_id: str,
    urls: tuple[str, ...],
    api_key: str,
    definition: Mapping[str, Any],
) -> str:
    # Advance the cursor before the first await so concurrent jobs get distinct starting nodes.
    start = _next_node.get(provider_id, 0) % len(urls)
    _next_node[provider_id] = (start + 1) % len(urls)
    async with artifact_http_client(timeout=_PROBE_TIMEOUT_SECONDS) as http:
        for url in urls[start:] + urls[:start]:
            client = ComfyuiClient(base_url=url, api_key=api_key, definition=definition)
            try:
                await asyncio.wait_for(client.server_version(http), timeout=_PROBE_TIMEOUT_SECONDS)
            except (
                httpx.HTTPError,
                ArtifactDestinationRejectedError,
                TimeoutError,
                ValueError,
            ) as exc:
                logger.warning("ComfyUI node probe failed: %s (%s)", url, type(exc).__name__)
            else:
                return url
    raise ComfyuiError("comfyui_nodes_unreachable")


@dataclass
class ComfyuiReservation:
    provider_id: str
    url: str | None
    pool: "ComfyuiDispatchPool"

    def release(self) -> None:
        if self.url is not None:
            self.pool.release(self.url)
            self.url = None


comfyui_dispatch_node: ContextVar[ComfyuiReservation | None] = ContextVar("comfyui_dispatch_node", default=None)
comfyui_live_pool: ContextVar[
    tuple["ComfyuiDispatchPool", Callable[[str], "ComfyuiPoolConfig | None"]] | None
] = ContextVar("comfyui_live_pool", default=None)


async def generation_node(
    provider_id: str, urls: tuple[str, ...], api_key: str, definition: Mapping[str, Any]
) -> str | None:
    dispatch = comfyui_dispatch_node.get()
    if dispatch is not None and dispatch.url is not None:
        if dispatch.provider_id != provider_id or dispatch.url not in urls:
            raise ComfyuiError("comfyui_nodes_unreachable")
        return dispatch.url
    if len(urls) > 1:
        return await choose_comfyui_node(provider_id, urls, api_key, definition)
    return None


_standalone_pools: dict[asyncio.AbstractEventLoop, tuple["ComfyuiDispatchPool", int]] = {}


@asynccontextmanager
async def standalone_comfyui_pool() -> AsyncIterator["ComfyuiDispatchPool"]:
    loop = asyncio.get_running_loop()
    existing = _standalone_pools.get(loop)
    pool, count = existing if existing is not None else (ComfyuiDispatchPool(), 0)
    _standalone_pools[loop] = pool, count + 1
    try:
        yield pool
    finally:
        _, count = _standalone_pools[loop]
        if count == 1:
            del _standalone_pools[loop]
            await pool.close()
        else:
            _standalone_pools[loop] = pool, count - 1


@dataclass(frozen=True)
class ComfyuiPoolConfig:
    urls: tuple[str, ...]
    api_key: str = field(repr=False)
    auth_options: tuple[Mapping[str, Any], ...] = field(repr=False)


@dataclass
class _PoolProbe:
    config: ComfyuiPoolConfig
    started: float
    task: asyncio.Task[list[tuple[str, int]]]


class ComfyuiDispatchPool:
    """Poll queues off the worker loop and reserve an idle URL until its task ends."""

    def __init__(self) -> None:
        self._probes: dict[str, _PoolProbe] = {}
        self._reserved: Counter[str] = Counter()
        self._revisions: dict[str, int] = {}
        self._next_url: dict[str, int] = {}

    def _idle(self, provider_id: str, config: ComfyuiPoolConfig) -> list[str]:
        probe = self._probes.get(provider_id)
        if not probe or probe.config != config or not probe.task.done() or probe.task.cancelled():
            return []
        if (error := probe.task.exception()) is not None:
            self._probes.pop(provider_id)
            logger.warning("ComfyUI queue poll failed for %s (%s)", provider_id, type(error).__name__)
            return []
        if monotonic() - probe.started > _SAMPLE_MAX_AGE_SECONDS:
            return []
        return [
            url
            for url, revision in probe.task.result()
            if url not in self._reserved and revision == self._revisions.get(url, 0)
        ]

    def ready(self, provider_id: str, config: ComfyuiPoolConfig) -> bool:
        if self._idle(provider_id, config):
            return True
        probe = self._probes.get(provider_id)
        if probe and (not probe.task.done() or monotonic() - probe.started < 1):
            return False
        urls = [(url, self._revisions.get(url, 0)) for url in config.urls if url not in self._reserved]
        if urls:
            self._probes[provider_id] = _PoolProbe(config, monotonic(), asyncio.create_task(self._probe(config, urls)))
        return False

    def reserve(self, provider_id: str, config: ComfyuiPoolConfig) -> str | None:
        ready = self._idle(provider_id, config)
        if not ready:
            return None
        start = self._next_url.get(provider_id, 0) % len(config.urls)
        url = next(url for url in config.urls[start:] + config.urls[:start] if url in ready)
        self._next_url[provider_id] = config.urls.index(url) + 1
        self.hold(url)
        return url

    def hold(self, url: str) -> None:
        self._reserved[url] += 1
        self._revisions[url] = self._revisions.get(url, 0) + 1

    def release(self, url: str) -> None:
        if self._reserved[url] > 1:
            self._reserved[url] -= 1
        else:
            self._reserved.pop(url, None)

    async def close(self) -> None:
        tasks = [probe.task for probe in self._probes.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._probes.clear()

    @staticmethod
    async def _probe(config: ComfyuiPoolConfig, urls: list[tuple[str, int]]) -> list[tuple[str, int]]:
        async with artifact_http_client(timeout=_PROBE_TIMEOUT_SECONDS) as http:

            async def is_idle(url: str) -> bool:
                try:
                    async with asyncio.timeout(_PROBE_TIMEOUT_SECONDS):
                        for auth in config.auth_options:
                            client = ComfyuiClient(
                                base_url=url,
                                api_key=config.api_key,
                                definition={"auth": auth},
                            )
                            try:
                                snapshot = await client.queue_snapshot(http)
                            except httpx.HTTPStatusError as exc:
                                if exc.response.status_code in (401, 403):
                                    continue
                                raise
                            return snapshot == ([], [])
                except (
                    httpx.HTTPError,
                    httpx.InvalidURL,
                    ArtifactDestinationRejectedError,
                    TimeoutError,
                    ValueError,
                    RuntimeError,
                ) as exc:
                    logger.debug("ComfyUI queue probe failed (%s)", type(exc).__name__)
                return False

            idle = await asyncio.gather(*(is_idle(url) for url, _ in urls))
            return [node for node, available in zip(urls, idle, strict=True) if available]
