from __future__ import annotations

from typing import Any, cast

from src.core.logging import get_logger
from src.core.protocols import PlanResponsePayload
from src.core.state import GameState, Phase, Position, Role
from src.memory.graphiti_client import get_graphiti
from src.tools.pathfinding import (
    active_cone_cells,
    assess_risk,
    count_alternative_paths,
    plan_path,
)

log = get_logger(__name__)

VISIBLE_AGE = 0


async def _avoid_zones_async(
    state: GameState, npcs_known: bool
) -> tuple[set[Position], dict[str, dict[str, Any]]]:
    avoid: set[Position] = set()
    stale: dict[str, dict[str, Any]] = {}
    avoid |= active_cone_cells(state)
    graphiti = await get_graphiti()
    snapshot = await graphiti.last_known_positions(
        state.game_id, state.turn, max_age=VISIBLE_AGE
    )
    for _npc_id, info in snapshot.items():
        pos = tuple(info["pos"])
        avoid.add(pos)
        for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
            avoid.add((pos[0] + dx, pos[1] + dy))

    avoid.discard(state.team_pos())
    return avoid, stale


def _avoid_zones(state: GameState, npcs_known: bool) -> set[Position]:
    avoid: set[Position] = set()
    avoid |= active_cone_cells(state)
    if npcs_known:
        avoid |= {tuple(n.pos) for n in state.npcs if n.is_alive}
    avoid.discard(state.team_pos())
    return avoid


def _is_phase2(state: GameState) -> bool:
    return state.phase in {
        Phase.PHASE2_TO_EXIT,
        Phase.PHASE2_TO_EXIT.value,
        Phase.PHASE2_ALARM,
        Phase.PHASE2_ALARM.value,
    }


def _resolve_goal(state: GameState) -> tuple[Position | None, str]:
    if state.map is None:
        return None, ""
    if state.phase in {Phase.PHASE1_TO_VAULT, Phase.PHASE1_TO_VAULT.value}:
        return state.map.vault, "vault"
    return None, ""


def _choose_exit(
    state: GameState,
    avoid: set[Position],
    npcs_known: bool,
) -> tuple[list[Position], int, float, int] | None:
    if state.map is None:
        return None

    start = state.team_pos()
    candidates: list[tuple[int, list[Position], float, int]] = []
    for idx, exit_cell in enumerate(state.map.exits):
        path = plan_path(start, tuple(exit_cell), state.map, avoid)  # type: ignore[arg-type]
        if path is None:
            path = plan_path(start, tuple(exit_cell), state.map, set())  # type: ignore[arg-type]
        if path is None:
            continue
        risk = float(assess_risk(path, state, npcs_known))
        alts = int(
            count_alternative_paths(start, tuple(exit_cell), state.map, avoid)  # type: ignore[arg-type]
        )
        candidates.append((idx, list(path), risk, alts))

    if not candidates:
        return None

    candidates.sort(key=lambda c: (c[2], len(c[1])))
    best_idx, best_path, best_risk, best_alts = candidates[0]
    state.chosen_exit = best_idx
    return best_path, best_idx, best_risk, best_alts


def _stale_risk_bonus(path: list[Position], stale: dict[str, dict[str, Any]]) -> float:
    if not stale:
        return 0.0
    stale_cells = {info["pos"] for info in stale.values()}
    bonus = 0.0
    for p in path:
        if tuple(p) in stale_cells:
            bonus += 0.15
            continue
        for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
            if (p[0] + dx, p[1] + dy) in stale_cells:
                bonus += 0.05
                break
    return min(0.5, bonus)


async def plan(state: GameState) -> PlanResponsePayload:
    if state.map is None:
        return PlanResponsePayload(path=[], rationale="нет карты", estimated_risk=1.0)

    npcs_known = state.npcs_visible_to_team
    avoid, stale = await _avoid_zones_async(state, npcs_known)
    start = state.team_pos()

    if _is_phase2(state):
        chosen = _choose_exit(state, avoid, npcs_known)
        if chosen is None:
            return PlanResponsePayload(
                path=[], rationale="ни один из выходов недостижим", estimated_risk=1.0
            )
        path, exit_idx, risk, alts = chosen
        risk = float(min(1.0, risk + _stale_risk_bonus(path, stale)))
        goal_label = f"exit#{exit_idx}"
        goal = path[-1]

        rationale = ""
        try:
            exits_summary = ", ".join(
                f"#{i}={tuple(e)}" for i, e in enumerate(state.map.exits)
            )
            stale_brief = ", ".join(
                f"{nid}@{info['pos']}(age={info['age']})"
                for nid, info in list(stale.items())[:3]
            ) or "—"
            from src.agents.llm import chat_json
            from prompts.composer import compose_system_prompt

            system = compose_system_prompt(Role.STRATEGIST, state)
            user = (
                f"Фаза 2: алярм запущен, police_eta={state.police_eta}. "
                f"Доступные выходы: {exits_summary}. Стартовая клетка: {start}. "
                f"Я выбрал exit#{exit_idx} ({goal}), длина пути {len(path)}, "
                f"риск {risk:.2f}, альтернатив {alts}. "
                f"Устаревшие позиции NPC (camera tap, последние 3-6 ходов): {stale_brief}. "
                f"Объясни в 1–2 предложениях, почему этот выход предпочтительнее. "
                f'Ответ строго JSON: {{"rationale": "..."}}'
            )
            data = await chat_json(Role.STRATEGIST, system, user)
            rationale = str(data.get("rationale", ""))[:300]
        except Exception as exc:
            log.warning("strategist.llm_fallback", error=str(exc))
            rationale = (
                f"выбран exit#{exit_idx} {goal}: длина {len(path)}, риск {risk:.2f}"
            )

        return PlanResponsePayload(
            path=cast(list[Position], path),
            rationale=rationale,
            estimated_risk=risk,
            alternative_count=alts,
        )

    goal, goal_label = _resolve_goal(state)
    if goal is None:
        return PlanResponsePayload(path=[], rationale="нет цели", estimated_risk=1.0)

    path = plan_path(start, goal, state.map, avoid) 
    if path is None and avoid:
        path = plan_path(start, goal, state.map, set()) 
    if path is None:
        return PlanResponsePayload(
            path=[], rationale="ни один маршрут недоступен", estimated_risk=1.0
        )

    risk = assess_risk(path, state, npcs_known)
    alts = count_alternative_paths(start, goal, state.map, avoid) 

    rationale = ""
    try:
        from src.agents.llm import chat_json
        from prompts.composer import compose_system_prompt

        system = compose_system_prompt(Role.STRATEGIST, state)
        user = (
            f"Текущая цель: `{goal_label}`. Старт: {start}. Цель: {goal}. "
            f"Длина пути: {len(path)}. Активных конусов: {len(active_cone_cells(state))}. "
            f"NPC раскрыты: {npcs_known}. Альтернатив: {alts}. "
            f"Дай rationale (≤2 предложений), почему этот путь приемлем. "
            f'Ответ: {{"rationale": "..."}}'
        )
        data = await chat_json(Role.STRATEGIST, system, user)
        rationale = str(data.get("rationale", ""))[:300]
    except Exception as exc:
        log.warning("strategist.llm_fallback", error=str(exc))
        rationale = f"маршрут к {goal_label} длиной {len(path)}, риск {risk:.2f}"

    return PlanResponsePayload(
        path=cast(list[Position], path),
        rationale=rationale,
        estimated_risk=float(risk),
        alternative_count=int(alts),
    )
