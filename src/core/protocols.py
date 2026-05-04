from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.core.state import Difficulty, NPCArchetype, Phase, Position, Role


class A2AMessage(BaseModel):

    model_config = ConfigDict(use_enum_values=True)
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    turn_id: int
    from_role: Role
    to_role: Role
    payload: dict[str, Any]


class PlanRequestPayload(BaseModel):
    goal: Literal["vault", "exit"]
    current_phase: Phase
    known_npcs_visible: bool
    constraints: dict[str, Any] = Field(default_factory=dict)


class PlanRequest(A2AMessage):
    payload: PlanRequestPayload 


class PlanResponsePayload(BaseModel):
    path: list[Position]
    rationale: str
    estimated_risk: float = Field(ge=0.0, le=1.0)
    alternative_count: int = 0


class PlanResponse(A2AMessage):
    payload: PlanResponsePayload 


class HackRequestPayload(BaseModel):
    target: Literal["cameras", "vault"]
    cipher_spec: dict[str, Any]
    attempts_left: int


class HackRequest(A2AMessage):
    payload: HackRequestPayload 


class HackResponsePayload(BaseModel):
    answer: str
    reasoning: str
    confidence: float = Field(ge=0.0, le=1.0)


class HackResponse(A2AMessage):
    payload: HackResponsePayload 


class EncounterEventPayload(BaseModel):
    npc_id: str
    archetype: NPCArchetype
    context: str
    npc_utterance: str
    body_language: str = ""


class EncounterEvent(A2AMessage):
    payload: EncounterEventPayload 


class EncounterActionPayload(BaseModel):
    action: Literal["intimidate", "attack", "bypass"]
    rationale: str


class EncounterAction(A2AMessage):
    payload: EncounterActionPayload 


class ReflectionEventPayload(BaseModel):
    outcome: Literal["victory", "defeat"]
    stats: dict[str, Any]
    request: str = "Опиши 1-3 урока для будущих партий."


class ReflectionEvent(A2AMessage):
    payload: ReflectionEventPayload 


class StartGamePayload(BaseModel):
    difficulty: Difficulty
    seed: int = 42
