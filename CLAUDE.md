<!-- autopilot:start -->
# yougile-cli

Консольный клиент REST API YouGile v2 в эргономике GitHub CLI. Две точки входа: `yougile` и `yg`.

## Команды

| Команда | Что делает |
|---------|------------|
| `uv sync --extra dev` | Установить зависимости |
| `uv run yougile --help` | Запустить локально |
| `uv run pytest -q` | Прогнать тесты |
| `uv run ruff check src tests` | Линтер |
| `uv run mypy src` | Проверка типов |
| `uv build` | Собрать wheel и sdist |

## Устройство

- `src/yougile_cli/` — пакет: `cli.py` (точка входа и глобальные флаги), `client.py`
  (HTTP, ретраи, пагинация), `output.py` (все форматы вывода), `resolve.py`
  (разрешение имён и ссылок в ID), `errors.py` (коды возврата), `config.py`
  (`config.yml`, `hosts.yml`), `commands/` — по модулю на сущность API.
- `tests/` — pytest + respx, сеть не используется.
- `docs/commands.md` — полный справочник команд; `README.md` — обзор.

## Как здесь работает Autopilot

Сборка ведётся навыком `/autopilot`. Требования, спецификация и таски — в `.autopilot/`.
Прогресс — `.autopilot/dashboard.html`. Правило: требование из `manifest.md`
может снять только пользователь.

Если работа продолжается — скажи «продолжи автопилот»: состояние поднимется
из `.autopilot/state.js`, переспрашивать ничего не нужно.
<!-- autopilot:end -->
