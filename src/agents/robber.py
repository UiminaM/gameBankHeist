from __future__ import annotations

import json

from src.agents.llm import chat_json
from src.core.logging import get_logger
from src.core.protocols import EncounterActionPayload, EncounterEventPayload
from src.core.state import GameState, NPCArchetype, Role
from prompts.composer import compose_system_prompt

log = get_logger(__name__)


async def react_to_npc(
    state: GameState, event: EncounterEventPayload
) -> EncounterActionPayload:
    user_payload = (
        "Выбери действие на встрече с NPC. Только JSON: "
        '{"action": "intimidate|attack|bypass", "rationale": "<≤2 пред.>"}.\n'
        f"event = {json.dumps(event.model_dump(), ensure_ascii=False)}\n"
        f"police_eta = {state.police_eta}, casualties_so_far = {state.casualties}"
    )

    try:
        system = compose_system_prompt(Role.ROBBER, state)
        data = await chat_json(Role.ROBBER, system, user_payload)
        action = data.get("action", "bypass")
        if action not in {"intimidate", "attack", "bypass"}:
            action = "bypass"
        return EncounterActionPayload(action=action, rationale=str(data.get("rationale", ""))[:300])
    except Exception as exc:
        log.warning("robber.llm_fallback", error=str(exc))
        return _deterministic_action(state, event)


def _deterministic_action(
    state: GameState, event: EncounterEventPayload
) -> EncounterActionPayload:
    arch = event.archetype if isinstance(event.archetype, str) else event.archetype.value
    eta = state.police_eta or 999
    if arch == NPCArchetype.AGGRESSIVE.value:
        if eta <= 3:
            return EncounterActionPayload(action="attack", rationale="Агрессивный, нет времени.")
        return EncounterActionPayload(
            action="intimidate", rationale="Попробуем угрозу до атаки."
        )
    if arch == NPCArchetype.SCARED.value:
        return EncounterActionPayload(
            action="intimidate", rationale="Испуганный, угроза эффективна."
        )
    return EncounterActionPayload(action="bypass" if eta > 5 else "intimidate", rationale="Нейтральный, обходим.")
