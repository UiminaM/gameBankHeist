from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import frontmatter
from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.core.state import GameState, Phase, Role


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOUL_DIR = PROJECT_ROOT / "soul"
SKILLS_DIR = PROJECT_ROOT / "skills"
SYSTEM_TPL_DIR = PROJECT_ROOT / "prompts" / "system"


@dataclass
class SkillBlock:
    role: str
    scope: str
    priority: float
    triggers: list[str]
    body: str
    path: str


def _load_md(p: Path) -> SkillBlock:
    post = frontmatter.load(p)
    meta = post.metadata
    return SkillBlock(
        role=meta.get("role", "global"),
        scope=meta.get("scope", "general"),
        priority=float(meta.get("priority", 0.5)),
        triggers=list(meta.get("triggers", [])),
        body=post.content.strip(),
        path=str(p.relative_to(PROJECT_ROOT)),
    )


def _load_dir(p: Path) -> list[SkillBlock]:
    if not p.exists():
        return []
    return [_load_md(f) for f in sorted(p.glob("**/*.md"))]


def _phase_to_trigger(phase: Phase | str) -> str:
    p = phase if isinstance(phase, str) else phase.value
    if p in {"init"}:
        return "init"
    if p.startswith("phase1") or p == "hack_cameras":
        return "phase1"
    if p.startswith("phase2") or p in {"hack_vault"}:
        return "phase2"
    if p in {"post_game", "end"}:
        return "end"
    return "phase1"


class PromptComposer:
    def __init__(self) -> None:
        self.soul_blocks = _load_dir(SOUL_DIR)
        self.skill_blocks = _load_dir(SKILLS_DIR)
        self.env = Environment(
            loader=FileSystemLoader(str(SYSTEM_TPL_DIR)),
            autoescape=select_autoescape(disabled_extensions=("j2",)),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def _filter_skills(
        self, role: Role | str, trigger: str
    ) -> list[SkillBlock]:
        role_str = role if isinstance(role, str) else role.value
        return [
            b
            for b in self.skill_blocks
            if b.role == role_str and (not b.triggers or trigger in b.triggers)
        ]

    def compose(
        self,
        role: Role | str,
        state: GameState,
        long_term_blocks: Iterable[str] | None = None,
    ) -> str:
        role_str = role if isinstance(role, str) else role.value
        trigger = _phase_to_trigger(state.phase)
        skills = self._filter_skills(role_str, trigger)
        skills.sort(key=lambda b: -b.priority)

        soul_text = "\n\n---\n\n".join(b.body for b in self.soul_blocks)
        skills_text = "\n\n---\n\n".join(f"## {b.scope}\n{b.body}" for b in skills)

        if long_term_blocks is None:
            attr = f"long_term_{role_str}"
            from_state = getattr(state, attr, "") if state is not None else ""
            blocks = [from_state] if from_state else []
        else:
            blocks = [b for b in long_term_blocks if b]
        ltm_text = "\n".join(f"- {x}" for x in blocks[-5:]) or "—"

        try:
            tpl = self.env.get_template(f"{role_str}.j2")
        except Exception:
            tpl = self.env.get_template("default.j2")

        return tpl.render(
            role=role_str,
            soul=soul_text,
            skills=skills_text,
            long_term=ltm_text,
            game_summary=self._game_summary(state),
        )

    @staticmethod
    def _game_summary(state: GameState) -> str:
        team = state.team_pos() if state.agents else "—"
        return (
            f"phase={state.phase} turn={state.turn} difficulty={state.difficulty} "
            f"team_pos={team} police_eta={state.police_eta} "
            f"casualties={state.casualties} alarm={state.alarm} "
            f"loot_taken={state.loot_taken} npcs_visible={state.npcs_visible_to_team}"
        )


_composer: PromptComposer | None = None


def compose_system_prompt(
    role: Role | str,
    state: GameState,
    long_term_blocks: Iterable[str] | None = None,
) -> str:
    global _composer
    if _composer is None:
        _composer = PromptComposer()
    return _composer.compose(role, state, long_term_blocks)
