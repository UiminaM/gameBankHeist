---
role: strategist
scope: coordination
priority: 0.7
triggers: [phase1, phase2]
---

# Skill: координация передач между агентами

## Когда передавать ход

| Ситуация | Кому |
|---|---|
| Камеры взломаны | World State (раскрытие NPC) → Strategist (план к хранилищу) |
| Группа достигла vault | Hacker (взлом хранилища) |
| Vault взломан | World State (старт Фазы 2) → Strategist (план выхода) |
| Шаг группы попадает на клетку с NPC | World State (отыгрыш NPC) → Robber (взаимодействие) |

## Формат передачи

Через `messages` в LangGraph state. Каждое сообщение содержит:
```json
{ "trace_id": "...", "turn_id": N, "from_role": "strategist", "to_role": "hacker", "payload": {...} }
```
