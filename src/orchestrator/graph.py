from __future__ import annotations

from typing import Any, Awaitable, Callable

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from src.agents import hacker as hacker_agent
from src.agents import robber as robber_agent
from src.agents import strategist as strategist_agent
from src.agents import world_state as world_state_agent
from src.core.logging import get_logger
from src.core.protocols import EncounterEventPayload
from src.core.state import (
    CameraState,
    GameOutcome,
    GameState,
    NPC,
    Phase,
)
from src.memory.graphiti_client import get_graphiti
from src.memory.letta_client import get_letta
from src.memory.reflection import load_lessons_for_all, write_reflections_for_all
from src.orchestrator.movement import (
    assign_npc_directions,
    step_along,
    vision_scan,
)
from src.tools.cipher_verify import verify_cipher
from src.tools.encounter import resolve_encounter

log = get_logger(__name__)

MAX_TURNS_HARDCAP = 200


async def node_init(state: GameState) -> GameState:
    state = await world_state_agent.init_world(state)
    from src.core.difficulty import get_params

    state.police_eta = get_params(state.difficulty).police_eta
    state.append_event("police_timer_started", police_eta=state.police_eta)
    return state


async def node_load_lessons(state: GameState) -> GameState:
    summaries = await load_lessons_for_all(state)
    state.long_term_strategist = summaries.get("strategist", "")
    state.long_term_hacker = summaries.get("hacker", "")
    state.long_term_robber = summaries.get("robber", "")
    state.append_event(
        "lessons_loaded",
        strategist_len=len(state.long_term_strategist),
        hacker_len=len(state.long_term_hacker),
        robber_len=len(state.long_term_robber),
    )
    return state


async def node_plan(state: GameState) -> GameState:
    plan = await strategist_agent.plan(state)
    state.current_path = plan.path
    state.append_event(
        "plan",
        path_len=len(plan.path),
        rationale=plan.rationale,
        risk=plan.estimated_risk,
        alts=plan.alternative_count,
        phase=state.phase,
    )
    if not plan.path:
        state.outcome = GameOutcome.DEFEAT
        state.phase = Phase.POST_GAME
    return state


async def node_step(state: GameState) -> GameState:
    state = step_along(state)
    if state.outcome == GameOutcome.DEFEAT.value or state.outcome == GameOutcome.DEFEAT:
        return state
    if state.turn >= MAX_TURNS_HARDCAP:
        state.outcome = GameOutcome.DEFEAT
        state.phase = Phase.POST_GAME
        return state
    await _vision_scan_write(state)
    return state


async def _vision_scan_write(state: GameState) -> None:
    if not any(str(cam.state) == CameraState.HACKED.value for cam in state.cameras):
        return
    visible, invisible = vision_scan(state)
    graphiti = await get_graphiti()
    for npc in visible:
        await graphiti.add_npc_position(state.game_id, npc, state.turn)
        state.npc_last_seen[npc.id] = {
            "pos": list(npc.pos),
            "turn": state.turn,
            "fresh": True,
        }
    for npc in invisible:
        await graphiti.expire_npc_observation(state.game_id, npc.id, state.turn)
        if npc.id in state.npc_last_seen:
            state.npc_last_seen[npc.id]["fresh"] = False


async def node_arrived_check(state: GameState) -> GameState:
    return state


async def node_gen_cipher_cameras(state: GameState) -> GameState:
    state.phase = Phase.HACK_CAMERAS
    return await world_state_agent.generate_cipher_node(state, target="cameras")


async def node_solve_cipher_cameras(state: GameState) -> GameState:
    if state.pending_cipher is None or state.pending_cipher_solution is None:
        return state

    spec = state.pending_cipher
    target = state.pending_cipher_target or "cameras"
    attempts_log = state.hack_attempts.get(target, 0)

    while spec.attempts_left > 0:
        spec.attempts_left -= 1
        attempts_log += 1
        resp = await hacker_agent.solve_cipher(state, spec)
        ok = verify_cipher(spec, state.pending_cipher_solution, resp.answer)
        state.append_event(
            "hack_attempt",
            target=target,
            success=ok,
            answer=resp.answer[:30],
            confidence=resp.confidence,
        )
        if ok:
            state.hack_attempts[target] = attempts_log
            if attempts_log == 1:
                state.hack_success_at_1[target] = True
            else:
                state.hack_success_at_1.setdefault(target, False)
            return await _on_hack_success(state)

    state.hack_attempts[target] = attempts_log
    state.hack_success_at_1.setdefault(target, False)
    state.alarm = True
    state.outcome = GameOutcome.DEFEAT
    state.phase = Phase.POST_GAME
    state.append_event("hack_failed", target=target)
    return state


async def _on_hack_success(state: GameState) -> GameState:
    target = state.pending_cipher_target
    state.pending_cipher = None
    state.pending_cipher_solution = None
    state.pending_cipher_target = None

    if target == "cameras":
        for cam in state.cameras:
            cam.state = CameraState.HACKED
        state.npcs_visible_to_team = True
        state.append_event("cameras_hacked")

        graphiti = await get_graphiti()
        visible, _invisible = vision_scan(state)
        for npc in visible:
            await graphiti.add_npc_position(state.game_id, npc, state.turn)
            state.npc_last_seen[npc.id] = {
                "pos": list(npc.pos),
                "turn": state.turn,
                "fresh": True,
            }
        state.phase = Phase.PHASE1_TO_VAULT

    elif target == "vault":
        state.loot_taken = True
        state.append_event("vault_unlocked")
        state.phase = Phase.PHASE2_ALARM
    return state


async def node_gen_cipher_vault(state: GameState) -> GameState:
    state.phase = Phase.HACK_VAULT
    return await world_state_agent.generate_cipher_node(state, target="vault")


async def node_solve_cipher_vault(state: GameState) -> GameState:
    return await node_solve_cipher_cameras(state)


async def node_phase2_alarm(state: GameState) -> GameState:
    state.alarm = True
    state.npcs_visible_to_team = True

    assign_npc_directions(state)

    graphiti = await get_graphiti()
    visible, _invisible = vision_scan(state)
    for npc in visible:
        await graphiti.add_npc_position(state.game_id, npc, state.turn)

    state.phase = Phase.PHASE2_TO_EXIT
    state.append_event(
        "alarm_started",
        police_eta=state.police_eta,
        cameras_kept_hacked=sum(1 for c in state.cameras if str(c.state) == "hacked"),
        npc_directions={n.id: n.move_direction for n in state.npcs if n.is_alive},
    )
    return state


async def node_encounter(state: GameState) -> GameState:
    if state.pending_encounter_npc_id is None:
        return state
    voice = await world_state_agent.voice_npc(state, state.pending_encounter_npc_id)
    archetype = state.pending_encounter_archetype or voice.get("archetype", "neutral")
    event = EncounterEventPayload(
        npc_id=state.pending_encounter_npc_id,
        archetype=archetype,  # type: ignore[arg-type]
        context=f"Встреча на клетке {state.team_pos()}",
        npc_utterance=voice.get("utterance", "..."),
        body_language=voice.get("body_language", ""),
    )
    action = await robber_agent.react_to_npc(state, event)
    resolution = resolve_encounter(archetype, action.action)

    state.casualties += resolution.casualties_delta
    if state.police_eta is not None:
        state.police_eta = max(0, state.police_eta - resolution.turns_cost)
    state.turn += resolution.turns_cost

    npc = next((n for n in state.npcs if n.id == state.pending_encounter_npc_id), None)
    if npc is not None and not resolution.npc_alive:
        npc.is_alive = False

    if resolution.spawn_extra_npc:
        new_npc = NPC(
            id=f"npc_spawn_{state.turn}",
            pos=_nearby_free_cell(state),
            archetype=archetype,  # type: ignore[arg-type]
        )
        state.npcs.append(new_npc)

    state.append_event(
        "encounter",
        npc_id=event.npc_id,
        archetype=archetype,
        action=action.action,
        rationale=action.rationale,
        casualties_delta=resolution.casualties_delta,
        spawn=resolution.spawn_extra_npc,
    )
    state.pending_encounter_npc_id = None
    state.pending_encounter_archetype = None
    return state


def _nearby_free_cell(state: GameState):
    if state.map is None:
        return state.team_pos()
    walls = set(state.map.walls)
    for d in [(2, 0), (-2, 0), (0, 2), (0, -2), (1, 1), (-1, -1)]:
        p = (state.team_pos()[0] + d[0], state.team_pos()[1] + d[1])
        if 0 <= p[0] < state.map.size and 0 <= p[1] < state.map.size and p not in walls:
            return p
    return state.team_pos()


async def node_post_game(state: GameState) -> GameState:
    if state.outcome == GameOutcome.IN_PROGRESS or state.outcome == GameOutcome.IN_PROGRESS.value:
        if state.loot_taken and _team_at_exit(state) and (state.police_eta or 0) > 0:
            state.outcome = GameOutcome.VICTORY
        else:
            state.outcome = GameOutcome.DEFEAT
    state.phase = Phase.END

    stats = {
        "outcome": state.outcome,
        "casualties": state.casualties,
        "turns": state.turn,
        "hack_success_at_1": state.hack_success_at_1,
        "cover_violations": state.cover_violations,
        "police_eta_left": state.police_eta,
    }
    lessons = await write_reflections_for_all(state)
    state.append_event(
        "post_game",
        **stats,
        lessons={k: v[:120] for k, v in lessons.items()},
    )
    log.info("game.finished", **stats, game_id=state.game_id)
    return state


def _team_at_exit(state: GameState) -> bool:
    if state.map is None:
        return False
    return state.team_pos() in {tuple(e) for e in state.map.exits}


def route_after_step(state: GameState) -> str:
    if state.outcome != GameOutcome.IN_PROGRESS and state.outcome != GameOutcome.IN_PROGRESS.value:
        return "post_game"
    if (state.police_eta or 0) <= 0:
        state.outcome = GameOutcome.DEFEAT
        return "post_game"
    if state.pending_encounter_npc_id is not None:
        return "encounter"

    team = state.team_pos()
    if state.map is None:
        return "post_game"

    if state.phase in {Phase.PHASE1_TO_VAULT, Phase.PHASE1_TO_VAULT.value}:
        if tuple(team) == tuple(state.map.vault):
            return "gen_cipher_vault"
        if not state.current_path or len(state.current_path) < 2:
            return "plan"
        return "step"

    if state.phase in {Phase.PHASE2_TO_EXIT, Phase.PHASE2_TO_EXIT.value}:
        if _team_at_exit(state):
            return "post_game"
        if not state.current_path or len(state.current_path) < 2:
            return "plan"
        return "step"

    return "post_game"


def route_after_encounter(state: GameState) -> str:
    if (state.police_eta or 1) <= 0:
        state.outcome = GameOutcome.DEFEAT
        return "post_game"
    return "plan"



def build_graph(checkpointer: Any | None = None) -> Any:
    g: StateGraph = StateGraph(GameState)

    g.add_node("init", _wrap(node_init))
    g.add_node("load_lessons", _wrap(node_load_lessons))
    g.add_node("plan", _wrap(node_plan))
    g.add_node("step", _wrap(node_step))
    g.add_node("gen_cipher_cameras", _wrap(node_gen_cipher_cameras))
    g.add_node("solve_cameras", _wrap(node_solve_cipher_cameras))
    g.add_node("gen_cipher_vault", _wrap(node_gen_cipher_vault))
    g.add_node("solve_vault", _wrap(node_solve_cipher_vault))
    g.add_node("phase2_alarm", _wrap(node_phase2_alarm))
    g.add_node("encounter", _wrap(node_encounter))
    g.add_node("post_game", _wrap(node_post_game))

    g.set_entry_point("init")
    g.add_edge("init", "load_lessons")
    g.add_edge("load_lessons", "gen_cipher_cameras")

    g.add_conditional_edges(
        "plan",
        lambda s: "step" if s.current_path and len(s.current_path) > 1 else "post_game",
        {"step": "step", "post_game": "post_game"},
    )

    g.add_conditional_edges(
        "step",
        route_after_step,
        {
            "step": "step",
            "plan": "plan",
            "encounter": "encounter",
            "gen_cipher_cameras": "gen_cipher_cameras",
            "gen_cipher_vault": "gen_cipher_vault",
            "post_game": "post_game",
        },
    )

    g.add_edge("gen_cipher_cameras", "solve_cameras")
    g.add_conditional_edges(
        "solve_cameras",
        lambda s: "post_game" if s.outcome != GameOutcome.IN_PROGRESS.value and s.outcome != GameOutcome.IN_PROGRESS else "plan",
        {"post_game": "post_game", "plan": "plan"},
    )

    g.add_edge("gen_cipher_vault", "solve_vault")
    g.add_conditional_edges(
        "solve_vault",
        lambda s: "post_game" if s.outcome != GameOutcome.IN_PROGRESS.value and s.outcome != GameOutcome.IN_PROGRESS else "phase2_alarm",
        {"post_game": "post_game", "phase2_alarm": "phase2_alarm"},
    )

    g.add_edge("phase2_alarm", "plan")
    g.add_conditional_edges(
        "encounter",
        route_after_encounter,
        {"plan": "plan", "post_game": "post_game"},
    )

    g.add_edge("post_game", END)

    cp = checkpointer or MemorySaver()
    return g.compile(checkpointer=cp)


def _wrap(fn: Callable[[GameState], Awaitable[GameState]]) -> Callable[[GameState], Awaitable[dict]]:

    async def inner(state: Any) -> dict:
        if isinstance(state, dict):
            state = GameState(**state)
        out = await fn(state)
        return out.model_dump(mode="python")

    return inner


async def run_game(initial: GameState, *, max_steps: int = 1000) -> GameState:
    graph = build_graph()
    config = {"configurable": {"thread_id": initial.game_id}, "recursion_limit": max_steps}
    final_dict = await graph.ainvoke(initial.model_dump(mode="python"), config=config)
    return GameState(**final_dict)
