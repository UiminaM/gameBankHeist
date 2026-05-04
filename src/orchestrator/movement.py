from __future__ import annotations

import random

from src.core.state import (
    CameraState,
    Direction,
    GameOutcome,
    GameState,
    NPC,
    Phase,
    Position,
)
from src.tools.pathfinding import active_cone_cells, vision_cone_cells


_DIR_DELTAS: dict[str, tuple[int, int]] = {
    Direction.N.value: (0, -1),
    Direction.S.value: (0, 1),
    Direction.E.value: (1, 0),
    Direction.W.value: (-1, 0),
}
_DIR_OPPOSITE: dict[str, str] = {
    Direction.N.value: Direction.S.value,
    Direction.S.value: Direction.N.value,
    Direction.E.value: Direction.W.value,
    Direction.W.value: Direction.E.value,
}


_PHASE2_VALUES = {
    Phase.PHASE2_TO_EXIT.value,
    Phase.PHASE2_TO_EXIT,
    Phase.PHASE2_ALARM.value,
    Phase.PHASE2_ALARM,
}


def _move_team(state: GameState, next_cell: Position) -> None:
    for a in state.agents:
        a.pos = next_cell
    state.turn += 1


def step_along(state: GameState) -> GameState:
    if not state.current_path or len(state.current_path) < 2:
        return state

    current = state.team_pos()
    if state.current_path[0] != current:
        try:
            idx = state.current_path.index(current)
            state.current_path = state.current_path[idx:]
        except ValueError:
            return state
    if len(state.current_path) < 2:
        return state

    next_cell = state.current_path[1]

    cones = active_cone_cells(state)
    if next_cell in cones:
        state.cover_violations += 1
        if state.phase in {
            Phase.PHASE1_TO_VAULT.value,
            Phase.PHASE1_TO_VAULT,
        }:
            state.alarm = True
            state.outcome = GameOutcome.DEFEAT
            state.append_event("alarm_phase1", cell=list(next_cell))
            state.phase = Phase.POST_GAME
            return state
        else:
            state.police_eta = max(0, (state.police_eta or 0) - 5)
            state.append_event("cover_violation_phase2", cell=list(next_cell))

    npc_here = next((n for n in state.npcs if tuple(n.pos) == next_cell and n.is_alive), None)
    _move_team(state, next_cell)
    state.current_path = state.current_path[1:]

    if state.police_eta is not None:
        state.police_eta = max(0, state.police_eta - 1)

    if npc_here is not None and state.phase in _PHASE2_VALUES:
        _set_pending_encounter(state, npc_here)

    state.append_event("step", to=list(next_cell), turn=state.turn)

    if state.phase in _PHASE2_VALUES:
        move_npcs_phase2(state)

    return state


def reactivate_cameras(state: GameState) -> None:
    for cam in state.cameras:
        cam.state = CameraState.ACTIVE


def vision_scan(state: GameState) -> tuple[list[NPC], list[NPC]]:
    visible: list[NPC] = []
    invisible: list[NPC] = []
    cones = vision_cone_cells(state)
    for npc in state.npcs:
        if not npc.is_alive:
            continue
        if tuple(npc.pos) in cones:
            visible.append(npc)
        else:
            invisible.append(npc)
    return visible, invisible


def assign_npc_directions(state: GameState, *, seed: int | None = None) -> None:
    rng = random.Random(seed if seed is not None else state.seed * 977 + state.turn)
    options = [Direction.N.value, Direction.S.value, Direction.E.value, Direction.W.value]
    for npc in state.npcs:
        if not npc.is_alive:
            continue
        if npc.move_direction is None:
            npc.move_direction = rng.choice(options)


def move_npcs_phase2(state: GameState) -> None:
    if state.map is None:
        return

    walls = {tuple(w) for w in state.map.walls}
    blocked: set[tuple[int, int]] = set(walls) | {tuple(state.map.vault)}
    occupied: set[tuple[int, int]] = {
        tuple(n.pos) for n in state.npcs if n.is_alive
    }
    team_pos = tuple(state.team_pos())

    for npc in state.npcs:
        if not npc.is_alive:
            continue
        direction = npc.move_direction
        if direction is None:
            continue

        dx, dy = _DIR_DELTAS[direction]
        cx, cy = npc.pos
        target = (cx + dx, cy + dy)

        in_bounds = 0 <= target[0] < state.map.size and 0 <= target[1] < state.map.size
        is_blocked = (
            not in_bounds
            or target in blocked
            or (target in occupied and target != tuple(npc.pos))
        )

        if is_blocked:
            npc.move_direction = _DIR_OPPOSITE[direction]
            continue

        occupied.discard(tuple(npc.pos))
        npc.pos = target
        occupied.add(target)

        if target == team_pos and state.pending_encounter_npc_id is None:
            _set_pending_encounter(state, npc)


def _set_pending_encounter(state: GameState, npc: NPC) -> None:
    state.pending_encounter_npc_id = npc.id
    state.pending_encounter_archetype = (
        npc.archetype if isinstance(npc.archetype, str) else npc.archetype.value
    )
