---
role: robber
scope: encounters
priority: 0.9
triggers: [phase2, encounter]
---

# Skill: запугивание (intimidate)

## Когда выбирать

- NPC выглядит **scared** или **neutral**.
- Есть запас времени (police_eta − turn ≥ 5).

## Эффект

| NPC | Результат |
|---|---|
| scared | пропускает (−1 ход) |
| neutral | пропускает (−1 ход) |
| aggressive | сопротивляется → +1 жертва (−2 хода) |

## Формат ответа

```json
{
  "action": "intimidate",
  "rationale": "Испуганный NPC, запас по времени есть."
}
```
