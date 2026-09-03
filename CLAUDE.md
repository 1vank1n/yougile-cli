<!-- autopilot:start -->
# yougile-cli

Консольный клиент REST API YouGile v2 в эргономике GitHub CLI: `<сущность> <действие> [цель] [флаги]`.
Две равнозначные точки входа — `yougile` и `yg`. Интерфейс полностью русский. Python ≥ 3.11, менеджер `uv`.

## Команды

| Команда | Что делает |
|---------|------------|
| `uv sync --extra dev` | поставить зависимости с dev-группой |
| `uv run yougile --help` | запустить из исходников (`uv run yg --help` — то же самое) |
| `uv run pytest -q` | весь набор тестов |
| `uv run pytest tests/test_output.py -q` | один файл |
| `uv run ruff check src tests` | линтер |
| `uv run ruff format --check src tests` | форматирование (CI проверяет отдельно) |
| `uv run mypy src` | типы |
| `uv build --python .venv/bin/python` | wheel и sdist в `dist/` (про флаг — «Подводные камни») |

Зелёным перед коммитом должны быть все четыре: `ruff check`, `ruff format --check`, `mypy src`, `pytest -q`.

## Структура

```
src/yougile_cli/       пакет: слои CLI, HTTP, вывода, конфигурации, разрешения имён
src/yougile_cli/commands/   по модулю на группу сущностей API, каждый отдаёт свой Typer-app
tests/                 pytest + respx; сеть не используется никогда
docs/commands.md       полный справочник команд, ~3100 строк
.github/workflows/     ci.yml (тесты 3.11–3.13 × linux/macos, mypy, build), release.yml (тег v* → релиз)
.github/actions/build-and-verify/   composite action: сборка, проверка состава, дымовой запуск колеса
.autopilot/            материалы сборки: бриф, спецификация, таски, состояние
```

## Ключевые файлы

- `src/yougile_cli/cli.py` — корневое Typer-приложение, глобальные флаги, монтирование групп, `main()`.
- `src/yougile_cli/client.py` — `YouGileClient`: запросы, ретраи, ограничитель, `paginate`/`collect`/`stream`/`upload_file`.
- `src/yougile_cli/output.py` — все форматы вывода, `render`, `--json`/`--jq`, очистка управляющих символов.
- `src/yougile_cli/config.py` — `hosts.yml` и `config.yml`, `resolve_auth`, алиасы, настройки, атомарная запись.
- `src/yougile_cli/resolve.py` — имя/ссылка/код задачи → ID, кэш кодов задач.
- `src/yougile_cli/errors.py` — иерархия исключений и коды возврата.
- `src/yougile_cli/context.py` — `AppContext` в `ctx.obj`, ленивый клиент, `emit`.
- `src/yougile_cli/fields.py` — статическая схема полей ресурсов для `--json` без значения.
- `src/yougile_cli/commands/tasks.py` — самый большой модуль команд; `commands/misc.py` — `config`, `alias`, `status`, `browse`, `version`, `file`, `crm`, `company`.

## Архитектура

Поток одного вызова: `main()` → `expand_argv` → Typer → корневой callback → команда → клиент → `render`.

- `expand_argv` = `_expand_aliases` → `normalize_json_flag` (голый `--json` получает пустое значение) → `hoist_root_flags` (корневой флаг можно писать после подкоманды, если сама подкоманда его не объявляет). Порядок значим.
- Корневой callback собирает `_RunContext` (наследник `AppContext`) и кладёт в `ctx.obj`: разрешённая аутентификация, `OutputOptions`, `Settings`, два `Console`, таймаут.
- Команда берёт контекст через `context.get_ctx`, клиент — через `get_client`/`ctx_client`. Клиент строится лениво: `auth`, `config`, `alias`, `version`, `completion` и любой `--help` обязаны работать без ключа; отсутствие ключа в момент построения даёт `AuthError` (код 4).
- `client.py`: базовый URL — корень хоста, `/api-v2` уже в каждом пути; `Bearer` на всём, кроме `POST /api-v2/auth/*`; токен-бакет 50 запросов в минуту; ретраи на 429/5xx с учётом `Retry-After`; списочные ручки отвечают `{"paging": …, "content": […]}`, `limit` не больше 1000.
- `resolve.py`: принимает UUID, ссылку из интерфейса, код задачи и имя. Кода задачи нет ни в одном фильтре API, поэтому карта `КОД → id` строится обходом `/api-v2/task-list` и кэшируется на 24 часа в `<config_dir>/cache/tasks-<host>-<account>.json` (аккаунт — дайджест ключа: коды уникальны в пределах компании).
- Вывод: команда зовёт `ctx.emit(...)` → `output.render`, порядок применения фиксирован — сначала выбор полей `--json`, потом `--jq`, потом формат (`table`, `json`, `yaml`, `csv`, `tsv`, `ids`).
- Ошибки: всё пользовательское наследует `YouGileError` с необязательным `hint`; ловится в `_RootGroup.invoke` и в `main()`, код даёт `exit_code_for`.
- Приоритет источников настроек, строго: флаг → переменная окружения → `hosts.yml`/`config.yml` → значение по умолчанию.
- `i18n.install_russian_ui()` вызывается на импорте `cli.py` и патчит русские строки в вендоренный typer'ом click; каждый патч best-effort и не должен ронять CLI.

## Соглашения кода

- Весь текст, который видит пользователь, — русский; докстринги и комментарии — английские.
- Комментарий объясняет «зачем», а не «что»; пересказа кода нет.
- `from __future__ import annotations` в каждом модуле, полные аннотации, публичные имена в `__all__`.
- `line-length = 100`; ruff `select = ["E","F","I","UP","B","C4","SIM"]`, `B008` выключен ради `typer.Option()` в дефолтах.
- Коды возврата как у `gh`: `0`, `1`, `2`, `4`, `130`. `2` — только собственная валидация до отправки запроса.
- Один модуль команд на группу сущностей; всё, что монтирует `cli.py`, реэкспортируется через `commands/__init__.py` — единственная точка импорта.
- Разрушающие команды спрашивают подтверждение, `--yes` его снимает; `-L/--limit 0` — «всё».
- Новые зависимости не добавляются походя: список в `pyproject.toml` короткий и обоснованный.

## Окружение

CLI читает окружение процесса и **не** загружает `.env` сам. Шаблон — `.env.example`.

- `YOUGILE_TOKEN` — персональный токен; приоритетнее `YOUGILE_API_KEY`.
- `YOUGILE_API_KEY` — API-ключ YouGile.
- `YOUGILE_HOST` — хост, если не облако.
- `YOUGILE_CONFIG_DIR` — каталог конфигурации вместо `~/.config/yougile`.
- `YOUGILE_EDITOR` — редактор для `--editor`, иначе `VISUAL`, затем `EDITOR`, затем `vi`.
- `NO_COLOR` / `CLICOLOR_FORCE` — стандартные, выключают и принудительно включают цвет.

`tests/test_docs.py` следит, чтобы `.env.example` и `README.md` не разъезжались с этим списком.

## Тесты

pytest + respx, `addopts = "-q"`, `testpaths = ["tests"]`. Сети нет ни в одном тесте.

Швов ровно два, новых не заводим: весь CLI через фикстуры `tests/conftest.py` и прямой импорт чистых функций.

Фикстуры: `run(args, input=…, token=…, env=…)` гоняет настоящее приложение через `CliRunner` (принимает и строку, и список), `api` — `respx.MockRouter` на `https://yougile.com`, `client` — готовый `YouGileClient` без бэкоффа, `paged(items)` собирает списочный ответ, `logged_in` кладёт валидный `hosts.yml`, `isolated_config`/`guard_config_dir`/`no_sleep`/`reset_color_override` — автоматические.

Один файл: `uv run pytest tests/test_output.py -q`. Один тест: `uv run pytest tests/test_output.py::имя -q`.

## Подводные камни

- `uv build` без флага падает на этой машине: глобальный `~/.python-version` содержит `2.7.18`. Рабочий вариант — `uv build --python .venv/bin/python`. Это среда, а не репозиторий; в CI такого нет.
- Версия живёт только в `src/yougile_cli/__init__.py`, в `[project]` стоит `dynamic = ["version"]`. Статического `version` быть не должно — закреплено `tests/test_packaging.py`.
- Список `[tool.hatch.build.targets.sdist].include` закреплён тестом и читается живьём composite action'ом. Правишь список — правь тест.
- Composite action отдаёт `version` из **установленного колеса**, и `release.yml` сверяет с ним тег. Менять способ получения версии нельзя, не тронув релиз.
- `typer>=0.26,<0.28` — жёстко: русификация патчит вендоренный `typer._click`, на других версиях она молча деградирует в английский.
- `--json` разбирается ровно в одном месте — `output.apply_json_fields`. Короткое замыкание на голом `--json` обязано стоять **до** `app_ctx.client()`, иначе перечень полей потребует входа; в `users.py` пять команд поэтому получают клиент после `_apply_output`.
- Очистка управляющих символов (`output.sanitize_terminal_text`) живёт только на слое печати. `json` и `yaml` не очищаются — они экранируют сами. `htmltext.html_to_text` формат-нейтрален, очистку туда не возвращать.
- Под pytest `config.config_dir()` требует `YOUGILE_CONFIG_DIR` и без него бросает `ConfigError`; `guard_config_dir` дополнительно валит тест, если каталог вне временного. Прогон однажды уже переписал реальный `config.yml`.
- Тесты вызывают CLI как `cli.expand_argv(argv)`, а не сырой argv: алиасы, `--json` и подъём флагов живут именно там.
- Ключ `pager` удалён из настроек; старые `config.yml` с ним читаются без ошибки (pydantic игнорирует лишние ключи), но `config set pager` отвергается.
- `AmbiguousNameError` даёт код 1, а не 2: неоднозначное имя — ошибка выполнения, не ошибка вызова.
- Вложения качаются только с хоста, под которым выполнен вход (`attachments.is_own_host`): описание задачи — чужой ввод, иначе ссылкой в описании можно увести CLI на любой сервер.

## Как здесь работает Autopilot

Сборка ведётся навыком `/autopilot`. Требования, спецификация и таски — в `.autopilot/`.
Прогресс — `.autopilot/dashboard.html`. Правило: требование из `manifest.md`
может снять только пользователь.

Если работа продолжается — скажи «продолжи автопилот»: состояние поднимется
из `.autopilot/state.js`, переспрашивать ничего не нужно.
<!-- autopilot:end -->
