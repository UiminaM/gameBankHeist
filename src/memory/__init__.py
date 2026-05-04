"""Memory subsystem.

L0  — LangGraph state (см. src/core/state.py)
L1  — Graphiti (bi-temporal граф позиций NPC, camera tap во 2 фазе)
L2  — Letta (per-role self-edit memory blocks)
L4  — markdown SOUL/skills/protocols (см. soul/, skills/)

Redis убран в ADR-0002 v2: реальной выгоды не давал, заменён на
process-local LLM cache внутри src/agents/llm.py.
"""

from src.memory.graphiti_client import GraphitiMemory
from src.memory.letta_client import LettaMemory

__all__ = ["GraphitiMemory", "LettaMemory"]
