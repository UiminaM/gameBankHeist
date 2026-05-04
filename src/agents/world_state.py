from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from src.agents.llm import chat_json
from src.core.difficulty import get_params
from src.core.logging import get_logger
from src.core.state import (
    AgentState,
    Camera,
    GameState,
    MapSpec,
    NPC,
    NPCArchetype,
    Phase,
    Role,
    WorldSpec,
)
from src.world.cipher_gen import generate_cipher
from src.world.map_gen import generate_world 
from src.world.map_gen import validate_world
from prompts.composer import compose_system_prompt

log = get_logger(__name__)


LLM_MAP_MAX_ATTEMPTS = 3


def _coerce_position(value: Any) -> tuple[int, int]:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return (int(value[0]), int(value[1]))
    raise ValueError(f"некорректная позиция: {value!r}")


def _coerce_world_payload(payload: dict[str, Any]) -> WorldSpec:
    raw = dict(payload)
    raw["walls"] = [_coerce_position(p) for p in raw.get("walls", [])]
    raw["entry"] = _coerce_position(raw["entry"])
    raw["vault"] = _coerce_position(raw["vault"])
    raw["exits"] = [_coerce_position(p) for p in raw.get("exits", [])]

    cams = []
    for c in raw.get("cameras", []):
        c = dict(c)
        c["pos"] = _coerce_position(c["pos"])
        cams.append(c)
    raw["cameras"] = cams

    npcs = []
    for n in raw.get("npcs", []):
        n = dict(n)
        n["pos"] = _coerce_position(n["pos"])
        npcs.append(n)
    raw["npcs"] = npcs

    return WorldSpec(**raw)


async def _llm_generate_world(state: GameState) -> WorldSpec | None:
    params = get_params(state.difficulty)
    system = compose_system_prompt(Role.WORLD_STATE, state)
    half = params.size // 2
    user = (
        f"Сгенерируй карту банка для игрового симулятора.\n"
        f"Сложность: {state.difficulty}. Seed: {state.seed}.\n"
        f"Параметры: size={params.size}, cameras={params.cameras}, "
        f"npcs={params.npcs}, cone_length={params.cone_length}.\n"
        f"Распределение архетипов NPC: {params.npc_distribution}.\n\n"
        f"Требования к карте:\n"
        f"- ровно ОДНА клетка `entry` на периметре,\n"
        f"- ровно ДВА `exits` на периметре, отличные от entry,\n"
        f"- одна клетка `vault` во внутренней области,\n"
        f"- от `entry` до `vault` существует ≥2 различных пути,\n"
        f"- от `vault` достижим каждый из `exits`,\n"
        f"- камеры с направлением N/S/E/W и length={params.cone_length},\n"
        f"- NPC не на стенах/спец-клетках/камерах,\n"
        f"- стены и камеры РАВНОМЕРНО распределены по карте: мысленно "
        f"раздели поле на 2×2 квадранта (граница на x={half} и y={half}); "
        f"ни в одном квадранте не должно быть больше ~50% всех стен и не "
        f"более ⌈cameras/4⌉+1 камер. НЕ группируй стены в одной строке/столбце "
        f"и в одном углу карты.\n\n"
        f"Ответ строго JSON по схеме WorldSpec:\n"
        '{"size": <int>, "walls": [[x,y], ...], '
        '"entry": [x,y], "vault": [x,y], "exits": [[x,y],[x,y]], '
        '"cameras": [{"id": "c1", "pos": [x,y], "direction": "N", "length": L}], '
        '"npcs": [{"id": "npc1", "pos": [x,y], "archetype": "neutral"}]}'
    )

    for attempt in range(1, LLM_MAP_MAX_ATTEMPTS + 1):
        try:
            data = await chat_json(Role.WORLD_STATE, system, user)
            world = _coerce_world_payload(data)
            validate_world(world)
            log.info("world.llm_ok", attempt=attempt)
            return world
        except (ValidationError, ValueError, RuntimeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            log.warning("world.llm_invalid", attempt=attempt, error=str(exc)[:200])
            continue
        except Exception as exc:
            log.warning("world.llm_unavailable", attempt=attempt, error=str(exc)[:200])
            return None
    return None


async def init_world(state: GameState) -> GameState:
    log.info("world.init", game_id=state.game_id, difficulty=state.difficulty, seed=state.seed)

    world: WorldSpec | None = await _llm_generate_world(state)
    source = "llm"
    if world is None:
        log.error("world.init_failed", game_id=state.game_id, difficulty=state.difficulty, seed=state.seed)

    state.map = MapSpec(
        size=world.size,
        walls=world.walls,
        entry=world.entry,
        vault=world.vault,
        exits=world.exits,
    )
    state.cameras = world.cameras
    state.npcs = world.npcs
    state.npcs_visible_to_team = False

    params = get_params(state.difficulty)
    state.police_eta = None  # активируется в Фазе 2
    state.alarm = False

    state.agents = [
        AgentState(role=Role.STRATEGIST, pos=world.entry),
        AgentState(role=Role.HACKER, pos=world.entry),
        AgentState(role=Role.ROBBER, pos=world.entry),
    ]
    state.phase = Phase.HACK_CAMERAS
    state.append_event(
        "world_init",
        size=world.size,
        cameras=len(world.cameras),
        npcs=len(world.npcs),
        source=source,
        params=params.__dict__,
    )
    return state


async def generate_cipher_node(state: GameState, target: str) -> GameState:
    params = get_params(state.difficulty)
    cipher_type = (
        params.cipher_camera_type if target == "cameras" else params.cipher_vault_type
    )
    pair = generate_cipher(cipher_type)
    pair.spec.attempts_left = (
        params.cipher_camera_attempts if target == "cameras" else params.cipher_vault_attempts
    )

    state.pending_cipher = pair.spec
    state.pending_cipher_solution = pair.solution
    state.pending_cipher_target = target 
    state.append_event(
        "cipher_generated", target=target, type=pair.spec.type, attempts=pair.spec.attempts_left
    )
    log.info("world.cipher_generated", target=target, type=pair.spec.type)
    return state


async def voice_npc(state: GameState, npc_id: str) -> dict[str, Any]:
    npc = next((n for n in state.npcs if n.id == npc_id), None)
    if npc is None:
        return {"npc_id": npc_id, "archetype": "neutral", "utterance": "...", "body_language": ""}

    arch = npc.archetype if isinstance(npc.archetype, str) else npc.archetype.value

    user_payload = (
        f"Сгенерируй реплику NPC `{npc_id}` с архетипом `{arch}`. "
        f"Текущая клетка: {npc.pos}. Контекст: грабители подошли вплотную. "
        f"Ответ строго JSON: "
        '{"npc_id": "...", "archetype": "...", "utterance": "...", "body_language": "..."}'
    )

    try:
        system = compose_system_prompt(Role.WORLD_STATE, state)
        data = await chat_json(Role.WORLD_STATE, system, user_payload)
        if "utterance" in data and "archetype" in data:
            data.setdefault("npc_id", npc_id)
            data.setdefault("body_language", "")
            return data
    except Exception as exc:
        log.warning("world.voice_fallback", error=str(exc))