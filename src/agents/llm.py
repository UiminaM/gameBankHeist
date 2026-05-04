from __future__ import annotations

import hashlib
import json
from typing import Any

from langchain_ollama import ChatOllama
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.core.config import get_settings
from src.core.logging import get_logger
from src.core.state import Role

log = get_logger(__name__)


_MODEL_FOR_ROLE_KEY = {
    Role.WORLD_STATE.value: "model_world_state",
    Role.STRATEGIST.value: "model_strategist",
    Role.HACKER.value: "model_hacker",
    Role.ROBBER.value: "model_robber",
}


def model_for_role(role: Role | str) -> str:
    s = get_settings()
    if s.bankheist_llm_model:
        return s.bankheist_llm_model.strip()
    role_str = role if isinstance(role, str) else role.value
    return getattr(s, _MODEL_FOR_ROLE_KEY[role_str])


_INMEMORY_CACHE: dict[str, str] = {}
_CACHE_MAX = 4096


def _cache_key(model: str, system: str, user: str, json_mode: bool, temp: float) -> str:
    raw = f"{model}|{temp}|{int(json_mode)}|SYS::{system}\nUSER::{user}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def chat(
    role: Role | str,
    system: str,
    user: str,
    *,
    json_mode: bool = True,
    temperature: float | None = None,
    use_cache: bool = True,
) -> str:
    s = get_settings()
    model = model_for_role(role)
    temp = s.llm_temperature if temperature is None else temperature

    cache_key: str | None = None
    if use_cache and temp == 0.0:
        cache_key = _cache_key(model, system, user, json_mode, temp)
        cached = _INMEMORY_CACHE.get(cache_key)
        if cached is not None:
            log.debug("llm.cache_hit", role=str(role), model=model)
            return cached

    chat_model = ChatOllama(
        base_url=s.ollama_base_url,
        model=model,
        temperature=temp,
        format="json" if json_mode else None,
        num_predict=1024,
        timeout=s.llm_timeout_seconds,
    )

    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(s.llm_max_retries),
        wait=wait_exponential(multiplier=0.5, max=4),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    ):
        with attempt:
            log.debug("llm.call", role=str(role), model=model, attempt=attempt.retry_state.attempt_number)
            response = await chat_model.ainvoke(
                [{"role": "system", "content": system}, {"role": "user", "content": user}]
            )
            content = response.content if isinstance(response.content, str) else str(response.content)

    if cache_key is not None:
        if len(_INMEMORY_CACHE) >= _CACHE_MAX:
            for k in list(_INMEMORY_CACHE.keys())[: _CACHE_MAX // 10]:
                _INMEMORY_CACHE.pop(k, None)
        _INMEMORY_CACHE[cache_key] = content
    return content


async def chat_json(
    role: Role | str, system: str, user: str, **kwargs: Any
) -> dict[str, Any]:
    raw = await chat(role, system, user, json_mode=True, **kwargs)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("llm.json_parse_failed", role=role, raw=raw[:200])
        raise ValueError(f"Invalid JSON from {role}: {exc}") from exc
