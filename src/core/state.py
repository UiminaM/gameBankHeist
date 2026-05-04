from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Difficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class Phase(str, Enum):
    INIT = "init"
    HACK_CAMERAS = "hack_cameras"
    PHASE1_TO_VAULT = "phase1_to_vault"
    HACK_VAULT = "hack_vault"
    PHASE2_ALARM = "phase2_alarm"
    PHASE2_TO_EXIT = "phase2_to_exit"
    POST_GAME = "post_game"
    END = "end"


class GameOutcome(str, Enum):
    IN_PROGRESS = "in_progress"
    VICTORY = "victory"
    DEFEAT = "defeat"


class Role(str, Enum):
    ORCHESTRATOR = "orchestrator"
    WORLD_STATE = "world_state"
    STRATEGIST = "strategist"
    HACKER = "hacker"
    ROBBER = "robber"


class CameraState(str, Enum):
    ACTIVE = "active"
    HACKED = "hacked"
    REBOOTING = "rebooting"


class NPCArchetype(str, Enum):
    AGGRESSIVE = "aggressive"
    SCARED = "scared"
    NEUTRAL = "neutral"


class Direction(str, Enum):
    N = "N"
    S = "S"
    E = "E"
    W = "W"


Position = tuple[int, int]


class Camera(BaseModel):
    model_config = ConfigDict(use_enum_values=True)
    id: str
    pos: Position
    direction: Direction
    length: int = Field(ge=1, le=10)
    state: CameraState = CameraState.ACTIVE


class NPC(BaseModel):
    model_config = ConfigDict(use_enum_values=True)
    id: str
    pos: Position
    archetype: NPCArchetype
    is_alive: bool = True
    last_seen_turn: int | None = None 
    move_direction: Direction | None = None 


class AgentState(BaseModel):
    model_config = ConfigDict(use_enum_values=True)
    role: Role
    pos: Position
    is_alive: bool = True


class CipherSpec(BaseModel):

    type: Literal[
        "caesar",
        "sudoku2",
        "sudoku4",
        "sudoku6",
        "logic_puzzle",
        "logic_easy",
        "logic_medium",
        "logic_hard",
        "digit_code",
        "cascade",
    ]
    difficulty: Difficulty
    spec: dict[str, Any]
    expected_answer_format: Literal["string", "matrix", "digits"]
    attempts_left: int = 3


class MapSpec(BaseModel):

    size: int = Field(ge=6, le=25)
    walls: list[Position] = Field(default_factory=list)
    entry: Position
    vault: Position
    exits: list[Position] = Field(min_length=2, max_length=2)


class WorldSpec(BaseModel):

    size: int
    walls: list[Position] = Field(default_factory=list)
    cameras: list[Camera]
    npcs: list[NPC]
    entry: Position
    vault: Position
    exits: list[Position] = Field(min_length=2, max_length=2)


class GameState(BaseModel):

    model_config = ConfigDict(use_enum_values=True, arbitrary_types_allowed=True)

    game_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    seed: int = 42

    difficulty: Difficulty = Difficulty.MEDIUM
    map: MapSpec | None = None
    cameras: list[Camera] = Field(default_factory=list)

    phase: Phase = Phase.INIT
    turn: int = 0
    npcs: list[NPC] = Field(default_factory=list)
    npcs_visible_to_team: bool = False
    agents: list[AgentState] = Field(default_factory=list)
    police_eta: int | None = None
    casualties: int = 0
    cover_violations: int = 0
    hack_attempts: dict[str, int] = Field(default_factory=dict)
    hack_success_at_1: dict[str, bool] = Field(default_factory=dict)
    loot_taken: bool = False
    alarm: bool = False
    outcome: GameOutcome = GameOutcome.IN_PROGRESS

    current_path: list[Position] = Field(default_factory=list)
    current_goal: str | None = None
    chosen_exit: int | None = None 

    pending_cipher: CipherSpec | None = None
    pending_cipher_solution: str | None = None 
    pending_cipher_target: Literal["cameras", "vault"] | None = None

    pending_encounter_npc_id: str | None = None
    pending_encounter_archetype: NPCArchetype | None = None

    long_term_strategist: str = ""
    long_term_hacker: str = ""
    long_term_robber: str = ""

    npc_last_seen: dict[str, dict[str, Any]] = Field(default_factory=dict)

    messages: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)

    def team_pos(self) -> Position:
        if not self.agents:
            return (0, 0)
        return self.agents[0].pos

    def alive_agents(self) -> list[AgentState]:
        return [a for a in self.agents if a.is_alive]

    def append_event(self, kind: str, **payload: Any) -> None:
        self.events.append({"turn": self.turn, "kind": kind, **payload})
