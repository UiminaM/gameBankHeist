from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.core.state import NPCArchetype


Action = Literal["intimidate", "attack", "bypass"]


@dataclass
class EncounterResolution:
    casualties_delta: int
    turns_cost: int
    npc_alive: bool
    spawn_extra_npc: bool


_MATRIX: dict[tuple[str, str], EncounterResolution] = {

    ("scared", "intimidate"): EncounterResolution(0, 1, True, False),
    ("scared", "attack"): EncounterResolution(1, 2, False, False),
    ("scared", "bypass"): EncounterResolution(0, 1, True, True),
    ("aggressive", "intimidate"): EncounterResolution(1, 2, False, False),
    ("aggressive", "attack"): EncounterResolution(1, 2, False, False),
    ("aggressive", "bypass"): EncounterResolution(1, 2, False, False),
    ("neutral", "intimidate"): EncounterResolution(0, 1, True, False),
    ("neutral", "attack"): EncounterResolution(1, 2, False, False),
    ("neutral", "bypass"): EncounterResolution(0, 1, True, True),
}


def resolve_encounter(archetype: NPCArchetype | str, action: Action) -> EncounterResolution:
    arch = archetype if isinstance(archetype, str) else archetype.value
    return _MATRIX[(arch, action)]
