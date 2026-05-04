# Bank Heist — мультиагентная игра

Мультиагентная система. Команда из четырёх LLM-агентов (World State Agent, Strategist, Hacker, Robber) совместно моделирует ограбление банка на сгенерированной 2D-карте. Игрок задаёт уровень сложности и наблюдает партию в Pygame UI.

---

## Архитектура

| Оркестрация | **LangGraph** (StateGraph + supervisor pattern) |
| LLM-сервинг | **Ollama** |
| Модель | Qwen3:4B  |
| Память L0 | LangGraph state + Pydantic + `SqliteSaver`/`PostgresSaver` |
| Память L1 (внутри партии) | **Graphiti** + Neo4j (bi-temporal граф знаний) |
| Память L2 (между партиями) | **Letta** (MemGPT, self-edit blocks) |
| UI | Pygame (на хосте) + FastAPI Gateway (WS) |
| Observability | Langfuse + Prometheus + Grafana + Loki |
| Изоляция | Docker Compose |

---

## Структура репозитория

```
bank-heist/
├── soul/                # SOUL.md, WORLD.md, PROTOCOLS.md
├── skills/              # markdown-скиллы по ролям
├── prompts/             # системные промпты + composer
├── src/
│   ├── core/            # GameState, MapSpec, A2A-протоколы
│   ├── tools/           # тулзы LangGraph
│   ├── memory/          # Graphiti и Letta клиенты
│   ├── agents/          # узлы LangGraph по ролям
│   ├── orchestrator/    # StateGraph builder + supervisor
│   ├── api/             # FastAPI gateway + WS
│   ├── ui/              # Pygame клиент
│   ├── observability/   # OTel, Prometheus, structlog
├── infra/               # Prometheus, Grafana, Loki configs

```



