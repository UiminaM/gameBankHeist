---
role: robber
scope: encounters
priority: 0.7
triggers: [phase2, encounter]
---

# Skill: нейтрализация (attack)

## Когда выбирать

- NPC **aggressive** и нет другого выхода.
- Времени почти не осталось (police_eta − turn ≤ 3) и любой задержки не пережить.

## Эффект

| NPC | Результат |
|---|---|
| любой | +1 жертва, −2 хода |

## Этическое ограничение

В рамках SOUL.md жизнь NPC ценна. `attack` — это всегда последний ресурс. Если ты выбираешь его, в `rationale` обязательно укажи, почему `intimidate`/`bypass` не подходят.

## Формат

```json
{
  "action": "attack",
  "rationale": "Агрессивный NPC, до полиции 2 хода, intimidate не сработал."
}
```
