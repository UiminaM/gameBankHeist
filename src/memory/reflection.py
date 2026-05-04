
from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any

from src.core.logging import get_logger
from src.core.state import GameOutcome, GameState, Role
from src.memory.letta_client import get_letta

log = get_logger(__name__)

MAX_LESSON_LEN = 320
SUMMARY_SOURCE_LIMIT = 50  


def _strategist_context(state: GameState) -> dict[str, Any]:
    plan_events = [e for e in state.events if e.get("kind") == "plan"]
    cover_events = [
        e for e in state.events
        if e.get("kind") in {"cover_violation_phase2", "alarm_phase1"}
    ]
    return {
        "outcome": str(state.outcome),
        "difficulty": str(state.difficulty),
        "turns": state.turn,
        "police_eta_left": state.police_eta,
        "chosen_exit": state.chosen_exit,
        "cover_violations": state.cover_violations,
        "casualties": state.casualties,
        "plan_count": len(plan_events),
        "avg_risk": round(
            sum(float(e.get("risk", 0)) for e in plan_events) / max(len(plan_events), 1),
            2,
        ),
        "max_risk": round(max((float(e.get("risk", 0)) for e in plan_events), default=0.0), 2),
        "cover_failures": len(cover_events),
    }


def _hacker_context(state: GameState) -> dict[str, Any]:
    hack_events = [e for e in state.events if e.get("kind") == "hack_attempt"]
    cipher_events = [e for e in state.events if e.get("kind") == "cipher_generated"]
    by_type: dict[str, dict[str, int]] = {}
    for ev in cipher_events:
        ct = ev.get("type", "?")
        by_type.setdefault(ct, {"target": ev.get("target", "?"), "attempts": 0, "ok": 0})
    for ev in hack_events:
        ct = next(
            (c.get("type") for c in cipher_events if c.get("target") == ev.get("target")),
            "?",
        )
        if ct in by_type:
            by_type[ct]["attempts"] += 1
            if ev.get("success"):
                by_type[ct]["ok"] += 1
    avg_conf = round(
        sum(float(e.get("confidence", 0)) for e in hack_events) / max(len(hack_events), 1),
        2,
    )
    return {
        "outcome": str(state.outcome),
        "difficulty": str(state.difficulty),
        "hack_attempts": dict(state.hack_attempts),
        "hack_success_at_1": dict(state.hack_success_at_1),
        "by_cipher_type": by_type,
        "avg_confidence": avg_conf,
    }


def _robber_context(state: GameState) -> dict[str, Any]:
    enc_events = [e for e in state.events if e.get("kind") == "encounter"]
    by_arch_action: dict[tuple[str, str], int] = {}
    casualties_by_arch: Counter[str] = Counter()
    for ev in enc_events:
        arch = str(ev.get("archetype", "?"))
        action = str(ev.get("action", "?"))
        by_arch_action[(arch, action)] = by_arch_action.get((arch, action), 0) + 1
        casualties_by_arch[arch] += int(ev.get("casualties_delta", 0))
    matrix = {f"{a}/{b}": n for (a, b), n in by_arch_action.items()}
    return {
        "outcome": str(state.outcome),
        "difficulty": str(state.difficulty),
        "encounters": len(enc_events),
        "casualties_total": state.casualties,
        "casualties_by_archetype": dict(casualties_by_arch),
        "by_archetype_action": matrix,
    }


def _fallback_strategist(state: GameState, ctx: dict[str, Any]) -> str:
    if ctx["cover_failures"] > 0:
        lesson = "Заходить в активный конус нельзя; в фазе 2 цена ошибки = -5 police_eta. Держать буфер ≥1 клетки."
    elif ctx["outcome"] == GameOutcome.VICTORY.value:
        lesson = "Выбор выхода с меньшим риском оправдал себя при текущих сидах; сохранять политику min(risk, length)."
    else:
        lesson = "Поражение без cover_violations — узкое место в other-этапе (вероятно, шифр); пути ок."
    head = (
        f"Партия {state.game_id[:8]} ({ctx['difficulty']}) → {ctx['outcome']}, "
        f"ходов {ctx['turns']}, exit#{ctx['chosen_exit']}, avg_risk={ctx['avg_risk']}."
    )
    return f"{head} Урок: {lesson}"[:MAX_LESSON_LEN]


def _fallback_hacker(state: GameState, ctx: dict[str, Any]) -> str:
    s1 = ctx["hack_success_at_1"]
    failed_types = [t for t, st in ctx["by_cipher_type"].items() if st["attempts"] > 0 and st["ok"] == 0]
    if failed_types:
        lesson = f"Не справился с типами: {', '.join(failed_types)}. На старте уделить им больше reasoning."
    elif s1 and all(s1.values()):
        lesson = "Все шифры решены с 1-й попытки — текущая стратегия валидна, держать её."
    else:
        lesson = "Промахи на 1-й попытке — повышать сверку и дублировать арифметику."
    head = (
        f"Партия {state.game_id[:8]} ({ctx['difficulty']}): "
        f"шифры={list(ctx['by_cipher_type'].keys())}, hack@1={s1}, conf={ctx['avg_confidence']}."
    )
    return f"{head} Урок: {lesson}"[:MAX_LESSON_LEN]


def _fallback_robber(state: GameState, ctx: dict[str, Any]) -> str:
    if not ctx["encounters"]:
        lesson = "Встреч не было — фаза 2 прошла на скрытности; политику обхода держим."
    elif ctx["casualties_total"] > 0:
        worst = max(ctx["casualties_by_archetype"].items(), key=lambda kv: kv[1], default=("?", 0))
        lesson = f"Жертв: {ctx['casualties_total']}, хуже всего с архетипом '{worst[0]}'. Пробовать intimidate раньше attack."
    else:
        lesson = "Без жертв — intimidate/bypass работают; не переходить к attack без острой нужды."
    head = (
        f"Партия {state.game_id[:8]} ({ctx['difficulty']}): "
        f"встреч={ctx['encounters']}, матрица={ctx['by_archetype_action']}."
    )
    return f"{head} Урок: {lesson}"[:MAX_LESSON_LEN]


async def _reflect_via_llm(role: Role, state: GameState, ctx: dict[str, Any], topic: str) -> str | None:
    try:
        from src.agents.llm import chat_json
        from prompts.composer import compose_system_prompt

        system = compose_system_prompt(role, state)
        user = (
            f"Ты — {role.value} после партии. На основе ТОЛЬКО своих данных "
            f"({topic}) сформулируй ОДИН компактный урок (≤2 предложений) "
            f"для будущих партий. Не повторяй очевидное.\n"
            f"Контекст роли:\n{ctx}\n\n"
            f"Ответ строго JSON: {{\"lesson\": \"...\"}}"
        )
        data = await chat_json(role, system, user)
        text = str(data.get("lesson", "")).strip()
        return text[:MAX_LESSON_LEN] if text else None
    except Exception as exc:
        log.warning("reflection.llm_fallback", role=role.value, error=str(exc)[:200])
        return None


async def reflect_strategist(state: GameState) -> str:
    ctx = _strategist_context(state)
    head = (
        f"Партия {state.game_id[:8]} ({ctx['difficulty']}) → {ctx['outcome']}, "
        f"ходов {ctx['turns']}, exit#{ctx['chosen_exit']}."
    )
    llm_lesson = await _reflect_via_llm(
        Role.STRATEGIST, state, ctx, "пути, риск, выбор выхода, cover_violations"
    )
    body = llm_lesson or _fallback_strategist(state, ctx).split("Урок:", 1)[-1].strip()
    return f"{head} Урок: {body}"[:MAX_LESSON_LEN]


async def reflect_hacker(state: GameState) -> str:
    ctx = _hacker_context(state)
    head = (
        f"Партия {state.game_id[:8]} ({ctx['difficulty']}): "
        f"типы={list(ctx['by_cipher_type'].keys())}, hack@1={ctx['hack_success_at_1']}."
    )
    llm_lesson = await _reflect_via_llm(
        Role.HACKER, state, ctx, "типы шифров, hack@1, среднюю confidence"
    )
    body = llm_lesson or _fallback_hacker(state, ctx).split("Урок:", 1)[-1].strip()
    return f"{head} Урок: {body}"[:MAX_LESSON_LEN]


async def reflect_robber(state: GameState) -> str:
    ctx = _robber_context(state)
    head = (
        f"Партия {state.game_id[:8]} ({ctx['difficulty']}): "
        f"встреч={ctx['encounters']}, casualties={ctx['casualties_total']}."
    )
    llm_lesson = await _reflect_via_llm(
        Role.ROBBER, state, ctx, "архетипы NPC, выбор intimidate/attack/bypass, casualties"
    )
    body = llm_lesson or _fallback_robber(state, ctx).split("Урок:", 1)[-1].strip()
    return f"{head} Урок: {body}"[:MAX_LESSON_LEN]


async def summarize_lessons(role: Role, state: GameState) -> str:
    letta = await get_letta()
    blocks = await letta.get_blocks(role)
    if not blocks:
        return ""
    recent = blocks[-SUMMARY_SOURCE_LIMIT:]

    fallback_text = " | ".join(b for b in recent[-5:] if b)

    try:
        from src.agents.llm import chat_json
        from prompts.composer import compose_system_prompt

        system = compose_system_prompt(role, state, long_term_blocks=[])  # без рекурсии
        user = (
            f"Ты — {role.value}. Ниже {len(recent)} уроков из прошлых партий "
            f"в формате 'партия_id (difficulty): итог. Урок: ...'. Сожми их "
            f"в ОДИН связный блок ≤ {MAX_LESSON_LEN} символов: 2-4 устойчивых "
            f"вывода, релевантных только твоей роли. Без преамбул и нумерации.\n\n"
            f"Уроки:\n" + "\n".join(f"- {b}" for b in recent) + "\n\n"
            f'Ответ строго JSON: {{"summary": "..."}}'
        )
        data = await chat_json(role, system, user)
        text = str(data.get("summary", "")).strip()
        if text:
            return text[:MAX_LESSON_LEN]
    except Exception as exc:
        log.warning("reflection.summary_fallback", role=role.value, error=str(exc)[:200])

    return fallback_text[:MAX_LESSON_LEN]


async def load_lessons_for_all(state: GameState) -> dict[str, str]:
    roles = (Role.STRATEGIST, Role.HACKER, Role.ROBBER)
    summaries = await asyncio.gather(
        *(summarize_lessons(r, state) for r in roles),
        return_exceptions=False,
    )
    return {r.value: (s or "") for r, s in zip(roles, summaries)}


async def write_reflections_for_all(state: GameState) -> dict[str, str]:
    letta = await get_letta()
    roles = (Role.STRATEGIST, Role.HACKER, Role.ROBBER)
    lessons = await asyncio.gather(
        reflect_strategist(state),
        reflect_hacker(state),
        reflect_robber(state),
        return_exceptions=False,
    )
    for role, lesson in zip(roles, lessons):
        if lesson:
            await letta.append_block(role, lesson)
    return {r.value: l for r, l in zip(roles, lessons)}
