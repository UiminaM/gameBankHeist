---
scope: global
priority: 0.95
triggers: [init, phase1, phase2, encounter, end]
---

# PROTOCOLS — протокол межагентного общения

## Общие правила

1. Все межагентные сообщения — JSON, валидируются Pydantic-схемами из `src/core/protocols.py`.
2. Каждое сообщение содержит обязательные поля: `trace_id`, `turn_id`, `from_role`, `to_role`, `payload`.
3. Если сообщение не парсится — отправитель получает ошибку и **до 3 ретраев**.

## Типы сообщений

### `PlanRequest` (Orchestrator → Strategist)
```json
{
  "trace_id": "uuid",
  "turn_id": 12,
  "from_role": "orchestrator",
  "to_role": "strategist",
  "payload": {
    "goal": "server_room|vault|exit",
    "current_phase": "phase1|phase2",
    "known_npcs_visible": true,
    "constraints": {
      "max_turns": 15,
      "avoid_zones": [[3,4], [3,5]]
    }
  }
}
```

### `PlanResponse` (Strategist → Orchestrator)
```json
{
  "payload": {
    "path": [[1,1], [1,2], [2,2]],
    "rationale": "Обхожу конус камеры C2 через северный коридор.",
    "estimated_risk": 0.1,
    "alternative_count": 2
  }
}
```

### `HackRequest` (Orchestrator → Hacker)
```json
{
  "payload": {
    "target": "cameras|vault",
    "cipher_spec": { "type": "caesar", "ciphertext": "...", "alphabet": "..." },
    "attempts_left": 3
  }
}
```

### `HackResponse` (Hacker → Orchestrator)
```json
{
  "payload": {
    "answer": "PLAINTEXT",
    "reasoning": "Сдвиг 7 даёт связный текст.",
    "confidence": 0.9
  }
}
```

### `EncounterEvent` (Orchestrator → Robber)
```json
{
  "payload": {
    "npc_id": "npc_3",
    "archetype": "aggressive|scared|neutral",
    "context": "Сотрудник у входа в коридор C."
  }
}
```

### `EncounterAction` (Robber → Orchestrator)
```json
{
  "payload": {
    "action": "intimidate|attack|bypass",
    "rationale": "Испуганный — угроза с большой вероятностью пропустит."
  }
}
```

### `ReflectionEvent` (Orchestrator → All agents, по концу партии)
```json
{
  "payload": {
    "outcome": "victory|defeat",
    "stats": { "casualties": 0, "turns": 28, "hack_success_at_1": 1.0 },
    "request": "Опиши 1-3 урока для будущих партий."
  }
}
```

## Правила вывода

- Любой вывод агента, кроме явно текстового (rationale), должен быть валидным JSON.
- На самообъяснение (`rationale`) выделяется **не более 2 предложений**.
- Если агент не может выполнить действие, он возвращает ошибку:
```json
{ "error": "<short reason>" }
```
- Никогда не оборачивать JSON в markdown (```json ... ```).
