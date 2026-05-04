---
role: world_state
scope: ciphers
priority: 0.85
triggers: [phase1]
---

# Skill: генерация шифров

## Шифры по целям и сложности

### Камеры (всегда sudoku)
- easy: судоку 2×2 (`type=sudoku2`), цифры 1..2.
- medium: судоку 4×4 (`type=sudoku4`), цифры 1..4.
- hard: судоку 6×6 (`type=sudoku6`), цифры 1..6.
- Ответ: матрица `N×N` в виде списка списков или строк с числами.

### Хранилище (всегда logic puzzle)
- easy: `type=logic_easy`, 3 переменные (ABC), 2 базовых ограничения.
- medium: `type=logic_medium`, 4 переменных (ABCD), 3 ограничения.
- hard: `type=logic_hard`, 5 переменных (ABCDE), 4 ограничений.
- Пример формата: «A < B; A + C = 9; D = 2*B - 1; все цифры различны».
- Ответ: строка из `N` цифр подряд по порядку переменных.

## Формат ответа

```json
{
  "type": "sudoku2|sudoku4|sudoku6|logic_easy|logic_medium|logic_hard",
  "difficulty": "easy|medium|hard",
  "spec": { ... type-specific ... },
  "expected_answer_format": "string|matrix|digits"
}
```

Поле `solution` хранится отдельно, Hacker'у не показывается.

## Антифрод

- Не подмешивать решение в `spec`.
- Один шифр — одно валидное решение.
