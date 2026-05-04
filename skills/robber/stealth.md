---
role: robber
scope: encounters
priority: 0.85
triggers: [phase2, encounter]
---

# Skill: обход

## Когда выбирать

- NPC **scared** или **neutral**, но запас по времени мал и нельзя тратить ходы на угрозу.

## Эффект

| NPC | Результат |
|---|---|
| scared | сбегает с шумом → +1 NPC спавнится в радиусе 3 (−1 ход) |
| neutral | то же |
| aggressive | агрессор атакует → +1 жертва (−2 хода) |


## Формат

```json
{
  "action": "bypass",
  "rationale": "Нейтральный NPC, времени мало, обхожу слева."
}
```
