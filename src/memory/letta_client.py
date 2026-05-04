from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

from src.core.config import get_settings
from src.core.logging import get_logger
from src.core.state import Role

log = get_logger(__name__)

FALLBACK_DIR = Path("data/letta_fallback")

FALLBACK_MAX_BLOCKS = 50


class LettaMemory:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: httpx.AsyncClient | None = None
        self._available = False

    async def init(self) -> None:
        if not self.settings.use_letta:
            log.info("letta.disabled_by_config")
            return
        FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
        self._client = httpx.AsyncClient(
            base_url=self.settings.letta_base_url,
            timeout=15.0,
            headers={"Authorization": f"Bearer {self.settings.letta_token}"} if self.settings.letta_token else {},
        )
        try:
            r = await self._client.get("/v1/health")
            self._available = r.status_code == 200
            log.info("letta.connected" if self._available else "letta.unavailable", status=r.status_code)
        except Exception as exc:
            log.warning("letta.fallback", error=str(exc))
            self._available = False

    async def get_blocks(self, role: Role | str) -> list[str]:
        role_str = role if isinstance(role, str) else role.value
        if self._available and self._client is not None:
            try:
                r = await self._client.get(f"/v1/memory/blocks?label={role_str}")
                if r.status_code == 200:
                    return [b.get("value", "") for b in r.json().get("blocks", [])]
            except Exception as exc:
                log.warning("letta.get_failed", error=str(exc))
        return self._read_fallback(role_str)

    async def append_block(self, role: Role | str, value: str) -> None:
        role_str = role if isinstance(role, str) else role.value
        if self._available and self._client is not None:
            try:
                r = await self._client.post(
                    "/v1/memory/blocks",
                    json={"label": role_str, "value": value},
                )
                if r.status_code in (200, 201):
                    return
            except Exception as exc:
                log.warning("letta.append_failed", error=str(exc))
        self._append_fallback(role_str, value)

    async def reflect(
        self, role: Role | str, prompt: str, context: dict[str, Any]
    ) -> str:
        return prompt

    def _path(self, role: str) -> Path:
        return FALLBACK_DIR / f"{role}.jsonl"

    def _read_fallback(self, role: str) -> list[str]:
        p = self._path(role)
        if not p.exists():
            return []
        return [json.loads(line)["value"] for line in p.read_text().splitlines() if line.strip()]

    def _append_fallback(self, role: str, value: str) -> None:
        p = self._path(role)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            f.write(json.dumps({"value": value}, ensure_ascii=False) + "\n")
        try:
            lines = p.read_text().splitlines()
            if len(lines) > FALLBACK_MAX_BLOCKS:
                p.write_text("\n".join(lines[-FALLBACK_MAX_BLOCKS:]) + "\n")
        except Exception as exc:  
            log.warning("letta.rotation_failed", error=str(exc))

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()


_singleton: LettaMemory | None = None
_lock = asyncio.Lock()


async def get_letta() -> LettaMemory:
    global _singleton
    async with _lock:
        if _singleton is None:
            mem = LettaMemory()
            await mem.init()
            _singleton = mem
        return _singleton
