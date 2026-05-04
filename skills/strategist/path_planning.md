---
role: strategist
scope: planning
priority: 0.95
triggers: [phase1, phase2]
---

# Skill: планирование маршрута

## Доступные тулзы

- `plan_path(start, goal, avoid_zones)` — `A*` обхода. Возвращает кратчайший путь, исключающий `avoid_zones`.
- `query_graphiti(question, valid_at)` — проверить темпоральный граф знаний (например, последняя известная позиция NPC).

## Алгоритм

1. Определить `goal` из задачи (entry → vault → exit).
2. Определить `avoid_zones`: клетки `WALL` и `NPC`.
3. Вызвать `plan_path` для **каждого** возможного `start`/`goal` (если их несколько). Сравнить.
4. Прогнать `assess_risk` для каждого кандидата.
5. Выбрать минимальный риск; при равенстве — кратчайший.

## Формат `PlanResponse`

```json
{
  "path": [[x,y], ...],
  "rationale": "<1-2 предложения>",
  "estimated_risk": 0.0..1.0,
  "alternative_count": <int>
}
```
