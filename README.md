# yougile-cli

Управляйте задачами, досками и проектами YouGile прямо из терминала — с эргономикой GitHub CLI.

[![CI](https://github.com/1vank1n/yougile-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/1vank1n/yougile-cli/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)

## Что это

`yougile-cli` — консольный клиент для [REST API YouGile v2](https://yougile.com/api-v2),
построенный по образцу `gh`. Та же форма команды `<сущность> <действие> [цель] [флаги]`,
те же глаголы (`list`, `view`, `create`, `edit`, `delete`, `close`, `move`), тот же
подход к авторизации (`auth login`, `hosts.yml`), к выводу (`-o`, `--json`, `--jq`, `-L`)
и к произвольным запросам (`yougile api`). Если вы умеете пользоваться `gh` — вы уже
умеете пользоваться `yougile`.

- **114 команд** поверх всего публичного API: проекты, доски, колонки, задачи,
  сотрудники, отделы, стикеры, чаты, вебхуки, компания, файлы, CRM.
- **Ссылка из интерфейса работает как есть.** `yougile task view
  'https://ru.yougile.com/team/a1b2c3d4e5f6/#ILS-343'` и просто `yougile task view ILS-343`
  — код задачи и любая ссылка разрешаются в ID автоматически.
- **Вложения видно и можно забрать.** `task view` показывает секцию `ВЛОЖЕНИЯ`,
  `task attachments --download` скачивает всё разом, `file download` — по одной ссылке
  и всегда оригинал, а не превью 480×480.
- **Имена вместо идентификаторов.** `--board "Разработка"`, `--column "В работе"`,
  `--assignee @me`, `task view ILS-343` — CLI сам превращает их в ID.
- **Машиночитаемый вывод.** `table`, `json`, `yaml`, `csv`, `tsv`, `ids` плюс
  `--json ПОЛЯ` и `--jq`, чтобы класть результат в пайп.
- **Безопасно по умолчанию.** Ключи лежат в `hosts.yml` с правами `0600`,
  разрушающие команды спрашивают подтверждение, есть `--yes` для скриптов.
- **Учитывает лимиты YouGile.** Собственный ограничитель на 50 запросов в минуту,
  автоповторы на `429`/`5xx` с учётом `Retry-After`, автоматическая пагинация.

### Чем отличается от `gh`

Ничем, кроме предметной области, — и это сделано намеренно. Формы команд, имена
глаголов и флагов, коды возврата (`0`, `1`, `2`, `4`, `130`), поведение `--json`
без значения, алиасы с подстановкой `$1`/`$@`, `api` как «сырой» доступ к
эндпоинтам — всё скопировано с GitHub CLI, чтобы мышечная память переносилась
один в один. Разница только в том, что у YouGile нет репозиториев: контекст
задаётся не текущим каталогом, а флагами `--project` / `--board` / `--column`.

## Установка

```bash
uv tool install git+https://github.com/1vank1n/yougile-cli
```

Альтернативы:

```bash
pipx install git+https://github.com/1vank1n/yougile-cli
pip install git+https://github.com/1vank1n/yougile-cli
```

После установки в `PATH` появляются два имени — полное `yougile` и короткое `yg`.
Они полностью взаимозаменяемы:

```bash
yougile task list
yg task list
```

Автодополнение:

```bash
yougile completion install -s zsh   # дописать в файл настроек оболочки
yougile completion -s zsh           # или просто напечатать скрипт в stdout
```

## Быстрый старт

```bash
yougile auth login      # интерактивный вход, ключ ляжет в hosts.yml
yougile auth status     # проверить, под кем и в какой компании мы работаем
yougile project list    # проекты компании
yougile status          # мои незакрытые задачи, сгруппированные по доскам
```

Справка есть на каждом уровне: `yougile --help`, `yougile task --help`,
`yougile task list --help`.

## Авторизация

### Интерактивно

```bash
yougile auth login
```

Мастер спросит:

1. **Хост** — `yougile.com` по умолчанию либо адрес своего сервера.
2. **Способ входа** — логин и пароль или готовый API-ключ.
3. **Компанию** — если у аккаунта их несколько, покажет нумерованный список.

Логин и пароль наружу не сохраняются: CLI обменивает их на API-ключ
(`POST /api-v2/auth/keys`) и запоминает только ключ. Существующий рабочий ключ
переиспользуется — лимит YouGile в 30 ключей на аккаунт легко исчерпать случайно;
`--new-key` заставляет выпустить новый.

### Неинтерактивно (CI)

```bash
echo "$YOUGILE_KEY" | yougile auth login --with-token
```

Ключ читается из stdin, проверяется через `GET /api-v2/users/me` и сохраняется.
Вопросов не задаётся ни одного.

Либо совсем без файлов конфигурации — через переменную окружения:

```bash
export YOUGILE_TOKEN="ваш-api-ключ"
yougile task list
```

### Несколько аккаунтов

```bash
yougile auth status --show-token          # состояние всех учётных записей
yougile auth token                        # только ключ, для подстановки в скрипты
yougile auth switch --user ivan@example.com
yougile auth refresh                      # перевыпустить ключ активной записи
yougile auth logout --user ivan@example.com
yougile auth keys list                    # реестр API-ключей аккаунта
```

## Конфигурация

### Где что лежит

| Файл | Что хранит | Режим |
| --- | --- | --- |
| `hosts.yml` | учётные записи, API-ключи, активная компания | `0600` |
| `config.yml` | настройки и алиасы | `0644` |

Каталог — `platformdirs.user_config_dir("yougile")`:
`~/.config/yougile` на Linux, `~/Library/Application Support/yougile` на macOS,
`%APPDATA%\yougile` на Windows. Переопределяется `YOUGILE_CONFIG_DIR`.

`hosts.yml` пишется атомарно и всегда с правами `0600` — ключ не должен быть
доступен другим пользователям машины.

`hosts.yml`:

```yaml
yougile.com:
  active_user: ivan@example.com
  users:
    ivan@example.com:
      api_key: "0123456789abcdef…"
      user_id: "5f1c…"
      real_name: "Иван Лукьянец"
      company_id: "ecb2f0f6-…"
      company_name: "Моя компания"
```

`config.yml`:

```yaml
version: "1"
output: table          # формат вывода по умолчанию
prompt: enabled        # disabled отключает интерактивные вопросы
aliases:
  mine: task list --assignee @me
```

Управление настройками:

```bash
yougile config list
yougile config get output
yougile config set output json
yougile config clear-cache
```

### Приоритет источников

Строго сверху вниз: **флаг → переменная окружения → файл → значение по умолчанию.**

| Что | Флаг | Переменная окружения | Файл | По умолчанию |
| --- | --- | --- | --- | --- |
| API-ключ | `--api-key` | `YOUGILE_TOKEN`, затем `YOUGILE_API_KEY` | `hosts.yml` | — |
| Хост | `--hostname` | `YOUGILE_HOST` | единственный хост в `hosts.yml` | `yougile.com` |
| Формат вывода | `-o`, `--output` | — | `output` в `config.yml` | `table` |
| Каталог конфигурации | — | `YOUGILE_CONFIG_DIR` | — | `user_config_dir("yougile")` |
| Цвет | `--no-color` | `NO_COLOR`, `CLICOLOR_FORCE` | — | по признаку терминала |
| Интерактивные вопросы | `--yes` на командах | — | `prompt` в `config.yml` | `enabled` |
| Редактор для `--editor` | — | `YOUGILE_EDITOR`, `VISUAL`, `EDITOR` | — | `vi` |
| Таймаут HTTP | `--timeout` | — | — | `30` с |

Полный список переменных окружения:

| Переменная | Что делает |
| --- | --- |
| `YOUGILE_TOKEN` | API-ключ; имеет приоритет над `YOUGILE_API_KEY` и `hosts.yml` |
| `YOUGILE_API_KEY` | то же самое, запасное имя |
| `YOUGILE_HOST` | хост YouGile, например `yougile.com` |
| `YOUGILE_CONFIG_DIR` | каталог с `hosts.yml` и `config.yml` |
| `YOUGILE_EDITOR` | редактор для флага `--editor` (перед `VISUAL` и `EDITOR`) |
| `NO_COLOR` | любое значение отключает цвет |
| `CLICOLOR_FORCE` | значение, отличное от `0`, включает цвет даже в пайпе |

### Коды возврата

Совпадают с `gh`:

| Код | Когда |
| --- | --- |
| `0` | успех |
| `1` | ошибка выполнения, в том числе **любой** ответ сервера с ошибкой: `400`, `404`, `409`, `422`, `429`, `5xx` |
| `2` | ошибка использования: разбор аргументов и наша собственная валидация **до** отправки запроса |
| `4` | нужна авторизация: `401` и `403` от сервера |
| `130` | прервано по Ctrl+C |

Двойка — это всегда «команда вызвана неверно». Если запрос ушёл и сервер отказал
(например «нельзя удалить последнюю доску проекта»), код будет `1`, а не `2`.

## Формат вывода

Глобальный флаг `-o, --output` выбирает формат: `table` (по умолчанию),
`json`, `yaml`, `csv`, `tsv`, `ids`. Глобальные флаги ставятся **до** имени сущности:

```bash
yougile -o json project list
yougile -o ids board list --project "Разработка"   # только идентификаторы
yougile -o csv task list --limit 0 > tasks.csv
yougile --full-ids task list                       # не сокращать ID до 8 символов
```

На командах, которые печатают данные, набор флагов почти одинаковый:

| Флаг | Что делает |
| --- | --- |
| `--json ПОЛЯ` | JSON только с перечисленными через запятую полями |
| `--json` без значения | напечатать список доступных полей |
| `-q`, `--jq ВЫРАЖЕНИЕ` | прогнать JSON через внешний бинарь `jq` |
| `-L`, `--limit N` | сколько записей вернуть; `0` — выгрузить всё (по умолчанию 30; у `department tree` — `0`, то есть всё дерево); только у команд, которые запрашивают список у API |
| `--full-ids` | не сокращать идентификаторы до 8 символов |

`--full-ids` есть у части команд ещё и как собственный флаг; глобальные `-o/--output`
и `--full-ids` перед именем сущности работают везде. Исключение — `file download`:
там `-o/--output` означает путь сохранения, а не формат вывода.

```bash
yougile task list --json                       # какие поля вообще есть
yougile task list --json id,title,completed
yougile task list --json id,title --jq '.[] | select(.title | test("оплата"))'
```

Для `--jq` нужен установленный бинарь [`jq`](https://jqlang.github.io/jq/);
без него CLI подскажет поставить его или обойтись `--json`.

В режиме `table` заголовки печатаются капсом без рамок, а идентификаторы
сокращаются до 8 символов. Сокращение решается по значению, а не по имени поля:
режется любой UUID, поэтому `createdBy` и элементы `assigned` выглядят так же,
как `id` и `*Id`. Снимается это глобальным `--full-ids`.
Когда stdout не терминал, цвет и оформление отключаются автоматически — вывод
можно смело класть в пайп.

Пустой список не выглядит поломкой: в режиме `table` в **stderr** уходит тусклая
строка `Ничего не найдено.`, stdout остаётся пустым, код возврата — `0`.
В `json`, `yaml`, `csv`, `tsv` и `ids` ничего не меняется: в stdout уходит `[]`.

## Команды

| Группа | Команды |
| --- | --- |
| [`auth`](docs/commands.md#auth-авторизация) | `login`, `logout`, `status`, `token`, `switch`, `refresh`, `keys list\|create\|delete` |
| [`project`](docs/commands.md#project-проекты) | `list`, `view`, `create`, `edit`, `delete`, `role list\|view\|create\|edit\|delete` |
| [`board`](docs/commands.md#board-доски) | `list`, `view`, `create`, `edit`, `delete`, `tree` |
| [`column`](docs/commands.md#column-колонки) | `list`, `view`, `create`, `edit`, `delete`, `move` |
| [`task`](docs/commands.md#task-задачи) | `list`, `view`, `attachments`, `create`, `edit`, `close`, `reopen`, `archive`, `unarchive`, `delete`, `move`, `assign`, `unassign`, `comment`, `subscribers list\|add\|remove\|set` |
| [`user`](docs/commands.md#user-сотрудники) | `list`, `view`, `invite`, `edit`, `delete` |
| [`department`](docs/commands.md#department-отделы) | `list`, `view`, `create`, `edit`, `delete`, `tree` |
| [`sticker`](docs/commands.md#sticker-стикеры) | `string list\|view\|create\|edit\|delete\|icons`, `string state list\|add\|edit\|delete`, `sprint list\|view\|create\|edit\|delete`, `sprint state list\|add\|edit\|delete` |
| [`chat`](docs/commands.md#chat-чаты-и-сообщения) | `list`, `view`, `create`, `edit`, `delete`, `send`, `messages`, `typing`, `message view\|edit\|delete` |
| [`webhook`](docs/commands.md#webhook-подписки-на-события) | `list`, `view`, `create`, `edit`, `delete`, `events` |
| [`company`](docs/commands.md#company-компания) | `view`, `edit` |
| [`file`](docs/commands.md#file-файлы) | `upload`, `download` |
| [`crm`](docs/commands.md#crm-crm) | `contact create`, `contact view` |
| [`config`](docs/commands.md#config-настройки) | `get`, `set`, `list`, `clear-cache` |
| [`alias`](docs/commands.md#alias-алиасы) | `list`, `set`, `delete` |
| [`completion`](docs/commands.md#completion-автодополнение) | `completion -s ОБОЛОЧКА`, `install` |
| [верхний уровень](docs/commands.md#верхний-уровень) | `api`, `browse`, `status`, `version` |

Полный справочник — все 114 команд со всеми аргументами, флагами и примерами —
в [docs/commands.md](docs/commands.md).

## Рецепты

**Прислали ссылку вида `https://ru.yougile.com/team/…/#ILS-343` — посмотреть задачу
и скачать картинки**

Главный сценарий: человеку кинули ссылку из интерфейса, надо разобраться, что там,
и забрать вложения. Ничего вырезать руками не нужно — ссылку можно вставить как есть.

```bash
LINK='https://ru.yougile.com/team/a1b2c3d4e5f6/#ILS-343'

yougile task view "$LINK"                      # описание читаемым текстом + секция ВЛОЖЕНИЯ
yougile task attachments "$LINK"               # что именно приложено: источник, имя, тип, ссылка
yougile task attachments "$LINK" --download --dir ./ILS-343
```

Что происходит:

1. Из фрагмента `#ILS-343` берётся **код задачи** (поле `idTaskProject`), а не идентификатор.
   Код разрешается в ID полным обходом `/api-v2/task-list`; карта `КОД → id` кладётся
   в кэш `<каталог конфигурации>/cache/tasks-<хост>.json` (права `0600`, срок жизни
   сутки), поэтому второй вызов отвечает мгновенно. Сбросить: `yougile config clear-cache`.
2. `task view` в табличном режиме разворачивает HTML описания в текст: абзацы —
   переносами строк, `<li>` — маркерами, сущности раскодированы. Исходный HTML —
   под флагом `--raw-description`.
3. `task attachments` собирает файлы и из описания (`<img src>`, `<a href>`), и из
   сообщений чата, включая служебную форму `/root/#file:<url-encoded путь>`.
   Ограничить источник: `--source описание` или `--source чат`.
   В список вложений попадают только ссылки на хост авторизации и на парный облачный
   хост YouGile (`yougile.com` и `ru.yougile.com` — одно и то же облако); ссылка на
   посторонний хост не попадает в список и не скачивается.
4. `--download` качает всё найденное потоком, в каталог из `--dir`. Существующие
   файлы не перезаписываются без `--force`.
   Заголовок `Authorization: Bearer` уходит только на хост авторизации и на парный
   облачный хост YouGile и снимается при любом переходе на чужой origin, включая
   редирект, — так же, как это делает `gh api`.

Дальше всё то же самое работает по голому коду — ссылка не нужна:

```bash
yougile task view ILS-343 --comments
yougile task comment ILS-343 'Картинки посмотрел, чиню'
yougile browse ILS-343 --no-browser
```

**Скачать одно вложение по ссылке**

```bash
yougile file download 'https://ru.yougile.com/user-data/9f0c…/IMG_20260828_173932.jpg' -o ~/Downloads
```

Параметр `previews[]` из ссылки вырезается — качается оригинал, а не превью
480×480. Нужно именно превью — добавьте `--preview`. Если `-o` указывает на
существующий каталог, файл кладётся внутрь под своим именем; иначе `-o` — это имя
файла. Печатается путь и размер.

**Мои открытые задачи**

```bash
yougile task list --assignee @me --state open
```

**Создать задачу в колонке, указав её по имени**

```bash
yougile task create "Починить оплату" --board "Разработка" --column "В работе" --assignee @me --deadline "2026-09-15 18:00"
```

**Дерево доски: колонки и задачи в них**

```bash
yougile board tree "Разработка" --limit 0
```

**Выгрузить задачи доски в CSV**

```bash
yougile -o csv task list --board "Разработка" --state all --limit 0 > tasks.csv
```

**Массово переназначить задачи уволившегося сотрудника**

```bash
yougile task list --assignee petr@example.com --state open --limit 0 --json id --jq '.[].id' | xargs -n1 -I{} yougile task edit {} --assignee ivan@example.com
```

**Найти задачу по названию и получить ссылку на неё**

```bash
yougile task list --search "оплата" --state all
yougile browse ILS-343 --no-browser
```

**Закрыть задачу и написать в её чат**

```bash
yougile task close ILS-343 && yougile task comment ILS-343 "Выкатил на прод"
```

**Подписать сервис на изменения задач**

```bash
yougile webhook create https://example.com/hooks/yougile --event 'task-.*' --filter 'location=Разработка'
```

**Произвольный запрос к API с постраничным обходом**

```bash
yougile api 'task-list?columnId=5f1c0e1a' --paginate --jq '.[] | "\(.id) \(.title)"'
```

**Свой короткий алиас**

```bash
yougile alias set mine 'task list --assignee @me --state open'
yougile mine
```

**Отчёт «кто сколько закрыл» через `jq`**

```bash
yougile task list --state closed --limit 0 --json assigned --jq 'map(.assigned[]?) | group_by(.) | map({user: .[0], closed: length})'
```

**Кто в каком проекте состоит**

```bash
yougile user list --project "Разработка" --json realName,email
```

## Особенности API YouGile

Это не капризы CLI, а поведение самого API — их полезно знать:

- **Почти нет метода `DELETE`.** Удаление объекта — это `PUT` с телом
  `{"deleted": true}`. Команды `delete` делают именно это, а `--undelete`
  снимает пометку. Настоящий `DELETE` есть ровно у трёх ресурсов:
  API-ключей, сотрудников и ролей проекта.
- **`GET /api-v2/tasks` объявлен устаревшим.** Списки задач читаются через
  `/api-v2/task-list`.
- **Задачи фильтруются по колонке, а не по доске.** Поэтому `--board` и `--project`
  в `task list` — это сахар: CLI сам получает колонки и обходит их.
- **50 запросов в минуту на компанию.** Клиент держит собственный token bucket
  и повторяет запросы при `429`, уважая `Retry-After`.
- **30 API-ключей на аккаунт.** `auth login` по умолчанию переиспользует
  существующий рабочий ключ, а не плодит новые.
- **Чат задачи — это обычный чат.** `yougile chat send ILS-343 "текст"` и
  `yougile task comment ILS-343 "текст"` делают одно и то же.
- **Код задачи нельзя запросить напрямую.** Поле `idTaskProject` (`ILS-343`) не
  является фильтром ни у одного эндпоинта, поэтому CLI разрешает код полным обходом
  `/api-v2/task-list` и кэширует карту `КОД → id` на сутки.
- **Ссылки на файлы отдают превью.** У вложения в описании и в чате к URL приписан
  `?previews[]=…`; без него отдаётся оригинал. `file download` и
  `task attachments --download` срезают этот параметр сами.
- Списки отвечают `{"paging": {count, limit, offset, next}, "content": [...]}`
  с `limit` не больше 1000; `-L 0` обходит страницы за вас.

## Разработка

```bash
git clone https://github.com/1vank1n/yougile-cli
cd yougile-cli
uv sync --extra dev

uv run pytest              # тесты (сеть не трогается: httpx мокается через respx)
                           # и реальный конфиг тоже: YOUGILE_CONFIG_DIR обязателен
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src
```

Раскладка проекта:

```
yougile-cli/
├── src/yougile_cli/
│   ├── cli.py            # корневое Typer-приложение, глобальные флаги, main()
│   ├── client.py         # HTTP-клиент: авторизация, пагинация, ретраи, rate limit
│   ├── config.py         # hosts.yml / config.yml, кэш, приоритет источников
│   ├── context.py        # AppContext: ленивый клиент, вывод, настройки
│   ├── errors.py         # исключения и коды возврата
│   ├── output.py         # table/json/yaml/csv/tsv/ids, --json, --jq
│   ├── resolve.py        # имена, ссылки и коды задач → идентификаторы
│   ├── attachments.py    # вложения задачи: описание, чат, скачивание
│   ├── htmltext.py       # HTML описания и сообщений → читаемый текст
│   ├── editor.py         # запуск $EDITOR для --editor
│   ├── i18n.py           # русификация служебных строк typer/click
│   └── commands/         # по модулю на сущность API
├── tests/                # pytest + respx
├── docs/commands.md      # полный справочник команд
└── pyproject.toml
```

Правила простые: Python 3.11+, строка не длиннее 100 символов, полные аннотации
типов, тексты для пользователя по-русски, идентификаторы и комментарии по-английски.
Подробности — в [CONTRIBUTING.md](CONTRIBUTING.md).

## Лицензия

MIT © Ivan Lukyanets. Полный текст — в файле [LICENSE](LICENSE).
