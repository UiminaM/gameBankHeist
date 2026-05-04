from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.responses import Response

from src.core.config import get_settings
from src.core.logging import configure_logging, get_logger
from src.core.state import Difficulty, GameState
from src.observability.otel import init_otel
from src.orchestrator.graph import build_graph

log = get_logger(__name__)


GAME_OUTCOMES = Counter(
    "game_outcomes_total", "Game outcomes", ["outcome", "difficulty"]
)
TURN_DURATION = Histogram(
    "turn_duration_seconds", "Wall-clock duration of one turn", buckets=(0.5, 1, 2, 4, 8, 15, 30)
)
ACTIVE_GAMES = Gauge("active_games", "Number of active games")
INVALID_JSON = Counter(
    "llm_invalid_json_total", "LLM invalid JSON responses", ["role", "model"]
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    init_otel("bank-heist-gateway")
    log.info("gateway.startup")
    app.state.graph = build_graph()
    app.state.live: dict[str, asyncio.Queue] = {}
    yield
    log.info("gateway.shutdown")


app = FastAPI(title="Bank Heist Gateway", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/settings")
async def settings_view() -> dict[str, Any]:
    s = get_settings()
    return {
        "models": {
            "world_state": s.model_world_state,
            "strategist": s.model_strategist,
            "hacker": s.model_hacker,
            "robber": s.model_robber,
        },
        "use_graphiti": s.use_graphiti,
        "use_letta": s.use_letta,
    }


@app.post("/game")
async def start_game(payload: dict[str, Any]) -> dict[str, Any]:
    difficulty = Difficulty(payload.get("difficulty", "medium"))
    seed = int(payload.get("seed", 42))
    initial = GameState(difficulty=difficulty, seed=seed)
    final = await _run_and_publish(initial, queue=None)
    return {"game_id": final.game_id, "outcome": final.outcome, "casualties": final.casualties, "turns": final.turn}


@app.websocket("/ws")
async def ws_play(ws: WebSocket) -> None:
    await ws.accept()
    queue: asyncio.Queue = asyncio.Queue(maxsize=200)
    try:
        first = await ws.receive_text()
        payload = json.loads(first)
        difficulty = Difficulty(payload.get("difficulty", "medium"))
        seed = int(payload.get("seed", 42))
        initial = GameState(difficulty=difficulty, seed=seed)
        app.state.live[initial.game_id] = queue
        ACTIVE_GAMES.inc()

        ws_task = asyncio.create_task(_drain_queue_to_ws(queue, ws))
        try:
            final = await _run_and_publish(initial, queue=queue)
            await queue.put({"type": "final", "state": final.model_dump(mode="json")})
        finally:
            await queue.put(None)
            await ws_task
    except WebSocketDisconnect:
        log.info("ws.disconnect")
    except Exception as exc:
        log.exception("ws.error", error=str(exc))
    finally:
        ACTIVE_GAMES.dec()


async def _drain_queue_to_ws(queue: asyncio.Queue, ws: WebSocket) -> None:
    while True:
        item = await queue.get()
        if item is None:
            return
        try:
            await ws.send_text(json.dumps(item, ensure_ascii=False, default=str))
        except Exception:
            return


async def _run_and_publish(initial: GameState, queue: asyncio.Queue | None) -> GameState:
    graph = app.state.graph
    config = {"configurable": {"thread_id": initial.game_id}, "recursion_limit": 1000}

    last_event_idx = 0
    state_dict: dict[str, Any] = initial.model_dump(mode="python")

    async for chunk in graph.astream(state_dict, config=config):
        for _node, payload in chunk.items():
            if payload is None:
                continue
            state_dict = {**state_dict, **payload}
            events = state_dict.get("events", [])
            if queue is not None and len(events) > last_event_idx:
                for ev in events[last_event_idx:]:
                    await queue.put({"type": "event", "event": ev, "state": _state_snapshot(state_dict)})
                last_event_idx = len(events)

    final = GameState(**state_dict)
    GAME_OUTCOMES.labels(outcome=str(final.outcome), difficulty=str(final.difficulty)).inc()
    return final


def _state_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "game_id",
        "phase",
        "turn",
        "difficulty",
        "agents",
        "cameras",
        "npcs",
        "npcs_visible_to_team",
        "police_eta",
        "casualties",
        "alarm",
        "loot_taken",
        "outcome",
        "current_path",
        "map",
    )
    snap = {k: state.get(k) for k in keys}
    snap["npcs"] = _visible_npcs_for_ui(snap)
    snap["npcs_visible_to_team"] = bool(snap.get("npcs_visible_to_team"))
    return snap


def _visible_npcs_for_ui(snap: dict[str, Any]) -> list[dict[str, Any]]:
    map_data = snap.get("map") or {}
    npcs = snap.get("npcs") or []
    cameras = snap.get("cameras") or []
    size = int(map_data.get("size") or 0)
    walls = {tuple(w) for w in (map_data.get("walls") or [])}
    if size <= 0 or not npcs:
        return npcs
    if not any(str(c.get("state")) == "hacked" for c in cameras):
        return []

    cones: set[tuple[int, int]] = set()
    for cam in cameras:
        if str(cam.get("state")) != "hacked":
            continue
        pos = cam.get("pos") or [0, 0]
        cx, cy = int(pos[0]), int(pos[1])
        length = int(cam.get("length") or 0)
        dx, dy = {"N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0)}.get(
            str(cam.get("direction", "N")),
            (0, -1),
        )
        for i in range(1, length + 1):
            x, y = cx + dx * i, cy + dy * i
            if not (0 <= x < size and 0 <= y < size):
                break
            if (x, y) in walls:
                break
            cones.add((x, y))

    return [
        n
        for n in npcs
        if n.get("is_alive", True) and tuple(n.get("pos", ())) in cones
    ]
