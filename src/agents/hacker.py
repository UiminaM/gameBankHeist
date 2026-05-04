from __future__ import annotations

import json

from src.agents.llm import chat_json
from src.core.config import get_settings
from src.core.logging import get_logger
from src.core.protocols import HackResponsePayload
from src.core.state import CipherSpec, GameState, Role
from prompts.composer import compose_system_prompt

log = get_logger(__name__)


def _answer_from_llm_dict(data: dict) -> str:
    raw = data.get("answer")
    if raw is None:
        for alt in ("Answer", "solution", "plaintext", "decoded"):
            raw = data.get(alt)
            if raw is not None:
                break
    if raw is None:
        return ""
    if isinstance(raw, (dict, list)):
        return json.dumps(raw, ensure_ascii=False).strip()
    return str(raw).strip()


async def solve_cipher(state: GameState, spec: CipherSpec) -> HackResponsePayload:
    user_payload = (
        "Реши шифр. Верни строго JSON: "
        '{"answer": "<value>", "reasoning": "<≤2 предложения>", "confidence": 0..1}.\n'
        f"cipher_spec = {json.dumps(spec.model_dump(), ensure_ascii=False)}"
    )

    settings = get_settings()
    try:
        system = compose_system_prompt(Role.HACKER, state)
        data = await chat_json(Role.HACKER, system, user_payload)
        reasoning_raw = data.get("reasoning") or data.get("Reasoning") or ""
        conf_raw = data.get("confidence", data.get("Confidence", 0.5))
        try:
            confidence = float(conf_raw)
        except (TypeError, ValueError):
            confidence = 0.5
        answer = _answer_from_llm_dict(data)
        payload = HackResponsePayload(
            answer=answer,
            reasoning=str(reasoning_raw)[:300],
            confidence=confidence,
        )
        