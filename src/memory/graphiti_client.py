from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.core.config import get_settings
from src.core.logging import get_logger
from src.core.state import NPC, Position

log = get_logger(__name__)


@dataclass
class _Edge:
    subject: str 
    predicate: str 
    obj: str 
    valid_from: int
    valid_to: int | None = None
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    fact: str = ""


class _InMemoryFallback:

    def __init__(self) -> None:
        self.edges: list[_Edge] = []

    async def add_npc_position(
        self, game_id: str, npc: NPC, turn: int
    ) -> None:
        for e in self.edges:
            if (
                e.subject == f"{game_id}:{npc.id}"
                and e.predicate == "located_at"
                and e.valid_to is None
            ):
                e.valid_to = turn
        self.edges.append(
            _Edge(
                subject=f"{game_id}:{npc.id}",
                predicate="located_at",
                obj=f"{npc.pos[0]},{npc.pos[1]}",
                valid_from=turn,
                fact=(
                    f"NPC {npc.id} ({npc.archetype}) at "
                    f"({npc.pos[0]}, {npc.pos[1]}) on turn {turn}"
                ),
            )
        )

    async def expire_npc_observation(self, game_id: str, npc_id: str, turn: int) -> None:
        for e in self.edges:
            if (
                e.subject == f"{game_id}:{npc_id}"
                and e.predicate == "located_at"
                and e.valid_to is None
            ):
                e.valid_to = turn

    async def expire_all(self, game_id: str, turn: int) -> None:
        for e in self.edges:
            if (
                e.subject.startswith(f"{game_id}:")
                and e.predicate == "located_at"
                and e.valid_to is None
            ):
                e.valid_to = turn

    async def last_known_position(
        self, game_id: str, npc_id: str
    ) -> Position | None:
        candidates = [
            e
            for e in self.edges
            if e.subject == f"{game_id}:{npc_id}" and e.predicate == "located_at"
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda e: e.valid_from, reverse=True)
        x, y = candidates[0].obj.split(",")
        return (int(x), int(y))

    async def last_known_positions(
        self, game_id: str, current_turn: int, max_age: int
    ) -> dict[str, dict[str, Any]]:
        latest: dict[str, _Edge] = {}
        for e in self.edges:
            if not e.subject.startswith(f"{game_id}:"):
                continue
            if e.predicate != "located_at":
                continue
            npc_id = e.subject.split(":", 1)[1]
            prev = latest.get(npc_id)
            if prev is None or e.valid_from > prev.valid_from:
                latest[npc_id] = e

        out: dict[str, dict[str, Any]] = {}
        for npc_id, e in latest.items():
            last_seen_turn = e.valid_to if e.valid_to is not None else e.valid_from
            age = max(0, current_turn - last_seen_turn)
            if age > max_age:
                continue
            x, y = e.obj.split(",")
            out[npc_id] = {
                "pos": (int(x), int(y)),
                "last_seen_turn": last_seen_turn,
                "age": age,
                "fresh": age <= 2,
            }
        return out

    async def search(self, game_id: str, query: str, limit: int = 5) -> list[str]:
        prefix = f"{game_id}:"
        return [e.fact for e in self.edges if e.subject.startswith(prefix)][-limit:]

    async def close(self) -> None:
        return None


class GraphitiMemory:

    def __init__(self) -> None:
        self.settings = get_settings()
        self._backend: Any = None
        self._fallback = _InMemoryFallback()

    async def init(self) -> None:
        if not self.settings.use_graphiti:
            log.info("graphiti.disabled_by_config")
            return
        try:
            from graphiti_core import Graphiti  

            self._backend = Graphiti(
                self.settings.neo4j_uri,
                self.settings.neo4j_user,
                self.settings.neo4j_password,
            )
            await self._backend.build_indices_and_constraints()
            log.info("graphiti.connected")
        except Exception as exc:  
            log.warning("graphiti.fallback", error=str(exc))
            self._backend = None

    async def add_npc_position(self, game_id: str, npc: NPC, turn: int) -> None:
        await self._fallback.add_npc_position(game_id, npc, turn)
        if self._backend is None:
            return
        try:
            episode = (
                f"NPC {npc.id} ({npc.archetype}) обнаружен в клетке "
                f"({npc.pos[0]}, {npc.pos[1]}) на ходу {turn}."
            )
            await self._backend.add_episode(
                name=f"{game_id}:npc_seen:{npc.id}:{turn}",
                episode_body=episode,
                source_description="camera_tap",
                reference_time=datetime.now(timezone.utc),
            )
        except Exception as exc:  
            log.warning("graphiti.add_failed", error=str(exc))

    async def expire_npc_observation(
        self, game_id: str, npc_id: str, turn: int
    ) -> None:
        await self._fallback.expire_npc_observation(game_id, npc_id, turn)

    async def expire_npc_positions(self, game_id: str, turn: int) -> None:
        await self._fallback.expire_all(game_id, turn)

    async def last_known_position(
        self, game_id: str, npc_id: str
    ) -> Position | None:
        return await self._fallback.last_known_position(game_id, npc_id)

    async def last_known_positions(
        self, game_id: str, current_turn: int, max_age: int = 6
    ) -> dict[str, dict[str, Any]]:
        return await self._fallback.last_known_positions(
            game_id, current_turn, max_age
        )

    async def search(self, game_id: str, query: str, limit: int = 5) -> list[str]:
        if self._backend is None:
            return await self._fallback.search(game_id, query, limit)
        try:
            results = await self._backend.search(query=query, num_results=limit)
            return [r.fact for r in results]
        except Exception as exc:  
            log.warning("graphiti.search_failed", error=str(exc))
            return await self._fallback.search(game_id, query, limit)

    async def close(self) -> None:
        if self._backend is not None:
            try:
                await self._backend.close()
            except Exception:  
                pass


_singleton: GraphitiMemory | None = None
_lock = asyncio.Lock()


async def get_graphiti() -> GraphitiMemory:
    global _singleton
    async with _lock:
        if _singleton is None:
            mem = GraphitiMemory()
            await mem.init()
            _singleton = mem
        return _singleton
