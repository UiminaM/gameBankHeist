from dataclasses import dataclass

from src.core.state import Difficulty


@dataclass(frozen=True)
class DifficultyParams:
    size: int
    cameras: int
    npcs: int
    cone_length: int
    police_eta: int
    cipher_camera_type: str
    cipher_vault_type: str
    cipher_camera_attempts: int
    cipher_vault_attempts: int
    npc_distribution: dict[str, int] 


DIFFICULTY_TABLE: dict[Difficulty, DifficultyParams] = {
    Difficulty.EASY: DifficultyParams(
        size=6,
        cameras=4,
        npcs=5,
        cone_length=3,
        police_eta=20,
        cipher_camera_type="sudoku2",
        cipher_vault_type="logic_easy",
        cipher_camera_attempts=3,
        cipher_vault_attempts=3,
        npc_distribution={"aggressive": 2, "scared": 2, "neutral": 1},
    ),
    Difficulty.MEDIUM: DifficultyParams(
        size=8,
        cameras=6,
        npcs=8,
        cone_length=4,
        police_eta=15,
        cipher_camera_type="sudoku4",
        cipher_vault_type="logic_medium",
        cipher_camera_attempts=2,
        cipher_vault_attempts=2,
        npc_distribution={"aggressive": 3, "scared": 3, "neutral": 2},
    ),
    Difficulty.HARD: DifficultyParams(
        size=10,
        cameras=8,
        npcs=12,
        cone_length=5,
        police_eta=10,
        cipher_camera_type="sudoku6",
        cipher_vault_type="logic_hard",
        cipher_camera_attempts=1,
        cipher_vault_attempts=1,
        npc_distribution={"aggressive": 5, "scared": 4, "neutral": 3},
    ),
}


def get_params(difficulty: Difficulty | str) -> DifficultyParams:
    if isinstance(difficulty, str):
        difficulty = Difficulty(difficulty)
    return DIFFICULTY_TABLE[difficulty]
