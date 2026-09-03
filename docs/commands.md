# Справочник команд yougile-cli

Полный список команд, аргументов и флагов. Справочник получен обходом
`yougile … --help` по всему дереву команд, поэтому совпадает с поведением
установленной версии.

Конечных команд: **114** (плюс `yougile completion`, которая работает и как
группа, и как самостоятельная команда).

Форма команды всегда одна:

```
yougile <сущность> <действие> [ЦЕЛЬ] [ФЛАГИ]
```

Короткое имя `yg` — полный синоним `yougile`.

## Глобальные флаги

Ставятся **перед** именем сущности: `yougile -o json task list`.

| Флаг | Значение | По умолчанию | Описание |
| --- | --- | --- | --- |
| `--hostname` | `ХОСТ` | `yougile.com` | Хост YouGile |
| `--api-key` | `КЛЮЧ` | — | API-ключ; важнее переменных окружения и `hosts.yml`. Небезопасно: ключ виден в списке процессов — лучше `YOUGILE_TOKEN` или `yougile auth login --with-token` |
| `-o`, `--output` | `table\|json\|yaml\|csv\|tsv\|ids` | `table` | Формат вывода |
| `--full-ids` | — | — | Показывать идентификаторы целиком |
| `--no-color` | — | — | Отключить цвет и оформление вывода |
| `--quiet` | — | — | Не печатать таблицы и служебные сообщения |
| `--timeout` | `СЕК` | `30.0` | Таймаут HTTP-запроса в секундах |
| `-V`, `--version` | — | — | Показать версию и выйти |
| `-h`, `--help` | — | — | Показать справку и выйти |

## Коды возврата

| Код | Значение |
| --- | --- |
| `0` | успех |
| `1` | ошибка выполнения, в том числе **любой** ответ сервера с ошибкой: `400`, `404`, `409`, `422`, `429`, `5xx` |
| `2` | ошибка использования: разбор аргументов и наша собственная валидация **до** отправки запроса |
| `4` | нужна авторизация: `401` и `403` от сервера |
| `130` | прервано через Ctrl+C |

Двойка означает «вы неверно вызвали команду». Если запрос ушёл и сервер ответил
отказом — это `1` (или `4` для отказа по правам), а не `2`.

## Общие флаги вывода

Почти у каждой команды, которая печатает данные, есть один и тот же набор:

| Флаг | Описание |
| --- | --- |
| `--json ПОЛЯ` | JSON только с перечисленными через запятую полями; `--json` без значения печатает список доступных полей |
| `-q`, `--jq ВЫРАЖЕНИЕ` | прогнать JSON через внешний бинарь `jq` |
| `-L`, `--limit ЧИСЛО` | сколько записей вывести; `0` — все страницы |
| `--full-ids` | не сокращать идентификаторы до 8 символов |
| `-y`, `--yes` | не спрашивать подтверждение у разрушающих команд |

Сокращение идентификаторов в табличном режиме решается по значению, а не по
имени поля: режется любое значение-UUID, поэтому `createdBy` и элементы
`assigned` выглядят так же, как `id` и `*Id`. Снимается глобальным `--full-ids`.

### Пустой список

Если список пуст, в режиме `table` в **stderr** печатается тусклая строка
`Ничего не найдено.`, stdout остаётся пустым, код возврата — `0`. В режимах
`json`, `yaml`, `csv`, `tsv` и `ids` поведение не меняется: в stdout уходит `[]`
или пустой вывод.

## Как указывать цель команды

Везде, где ждут задачу (`ЗАДАЧА`), принимается любая из форм:

| Форма | Пример |
| --- | --- |
| код задачи | `ILS-343` |
| ссылка из интерфейса | `https://ru.yougile.com/team/a1b2c3d4e5f6/#ILS-343` |
| ссылка на доску с якорем | `https://ru.yougile.com/board/<uuid>#ILS-343` |
| ссылка на API | `https://ru.yougile.com/api-v2/tasks/<uuid>` |
| голый UUID | `5f1c0e1a-…` |
| заголовок | `'Починить оплату'` |

Код задачи (`idTaskProject`) разрешается через полный обход `/api-v2/task-list`;
карта `КОД → id` кэшируется в `<каталог конфигурации>/cache/tasks-<хост>.json`
с правами `0600` и сроком жизни 24 часа. Кэш чистится командой
`yougile config clear-cache`.

Доски, колонки, проекты, отделы, стикеры, чаты и сотрудников можно так же
указывать названием, e-mail или ссылкой; `@me` подставляет текущего сотрудника.

## Содержание

- [Верхний уровень](#верхний-уровень)
  - [`yougile api`](#yougile-api)
  - [`yougile browse`](#yougile-browse)
  - [`yougile status`](#yougile-status)
  - [`yougile version`](#yougile-version)
- [auth: авторизация](#auth-авторизация)
  - [`yougile auth login`](#yougile-auth-login)
  - [`yougile auth logout`](#yougile-auth-logout)
  - [`yougile auth status`](#yougile-auth-status)
  - [`yougile auth token`](#yougile-auth-token)
  - [`yougile auth switch`](#yougile-auth-switch)
  - [`yougile auth refresh`](#yougile-auth-refresh)
  - [`yougile auth keys list`](#yougile-auth-keys-list)
  - [`yougile auth keys create`](#yougile-auth-keys-create)
  - [`yougile auth keys delete`](#yougile-auth-keys-delete)
- [project: проекты](#project-проекты)
  - [`yougile project list`](#yougile-project-list)
  - [`yougile project view`](#yougile-project-view)
  - [`yougile project create`](#yougile-project-create)
  - [`yougile project edit`](#yougile-project-edit)
  - [`yougile project delete`](#yougile-project-delete)
  - [`yougile project role list`](#yougile-project-role-list)
  - [`yougile project role view`](#yougile-project-role-view)
  - [`yougile project role create`](#yougile-project-role-create)
  - [`yougile project role edit`](#yougile-project-role-edit)
  - [`yougile project role delete`](#yougile-project-role-delete)
- [board: доски](#board-доски)
  - [`yougile board list`](#yougile-board-list)
  - [`yougile board view`](#yougile-board-view)
  - [`yougile board create`](#yougile-board-create)
  - [`yougile board edit`](#yougile-board-edit)
  - [`yougile board delete`](#yougile-board-delete)
  - [`yougile board tree`](#yougile-board-tree)
- [column: колонки](#column-колонки)
  - [`yougile column list`](#yougile-column-list)
  - [`yougile column view`](#yougile-column-view)
  - [`yougile column create`](#yougile-column-create)
  - [`yougile column edit`](#yougile-column-edit)
  - [`yougile column delete`](#yougile-column-delete)
  - [`yougile column move`](#yougile-column-move)
- [task: задачи](#task-задачи)
  - [`yougile task list`](#yougile-task-list)
  - [`yougile task view`](#yougile-task-view)
  - [`yougile task attachments`](#yougile-task-attachments)
  - [`yougile task create`](#yougile-task-create)
  - [`yougile task edit`](#yougile-task-edit)
  - [`yougile task close`](#yougile-task-close)
  - [`yougile task reopen`](#yougile-task-reopen)
  - [`yougile task archive`](#yougile-task-archive)
  - [`yougile task unarchive`](#yougile-task-unarchive)
  - [`yougile task delete`](#yougile-task-delete)
  - [`yougile task move`](#yougile-task-move)
  - [`yougile task assign`](#yougile-task-assign)
  - [`yougile task unassign`](#yougile-task-unassign)
  - [`yougile task comment`](#yougile-task-comment)
  - [`yougile task subscribers list`](#yougile-task-subscribers-list)
  - [`yougile task subscribers add`](#yougile-task-subscribers-add)
  - [`yougile task subscribers remove`](#yougile-task-subscribers-remove)
  - [`yougile task subscribers set`](#yougile-task-subscribers-set)
- [user: сотрудники](#user-сотрудники)
  - [`yougile user list`](#yougile-user-list)
  - [`yougile user view`](#yougile-user-view)
  - [`yougile user invite`](#yougile-user-invite)
  - [`yougile user edit`](#yougile-user-edit)
  - [`yougile user delete`](#yougile-user-delete)
- [department: отделы](#department-отделы)
  - [`yougile department list`](#yougile-department-list)
  - [`yougile department view`](#yougile-department-view)
  - [`yougile department create`](#yougile-department-create)
  - [`yougile department edit`](#yougile-department-edit)
  - [`yougile department delete`](#yougile-department-delete)
  - [`yougile department tree`](#yougile-department-tree)
- [sticker: стикеры](#sticker-стикеры)
  - [`yougile sticker string icons`](#yougile-sticker-string-icons)
  - [`yougile sticker string list`](#yougile-sticker-string-list)
  - [`yougile sticker string view`](#yougile-sticker-string-view)
  - [`yougile sticker string create`](#yougile-sticker-string-create)
  - [`yougile sticker string edit`](#yougile-sticker-string-edit)
  - [`yougile sticker string delete`](#yougile-sticker-string-delete)
  - [`yougile sticker string state list`](#yougile-sticker-string-state-list)
  - [`yougile sticker string state add`](#yougile-sticker-string-state-add)
  - [`yougile sticker string state edit`](#yougile-sticker-string-state-edit)
  - [`yougile sticker string state delete`](#yougile-sticker-string-state-delete)
  - [`yougile sticker sprint list`](#yougile-sticker-sprint-list)
  - [`yougile sticker sprint view`](#yougile-sticker-sprint-view)
  - [`yougile sticker sprint create`](#yougile-sticker-sprint-create)
  - [`yougile sticker sprint edit`](#yougile-sticker-sprint-edit)
  - [`yougile sticker sprint delete`](#yougile-sticker-sprint-delete)
  - [`yougile sticker sprint state list`](#yougile-sticker-sprint-state-list)
  - [`yougile sticker sprint state add`](#yougile-sticker-sprint-state-add)
  - [`yougile sticker sprint state edit`](#yougile-sticker-sprint-state-edit)
  - [`yougile sticker sprint state delete`](#yougile-sticker-sprint-state-delete)
- [chat: чаты и сообщения](#chat-чаты-и-сообщения)
  - [`yougile chat list`](#yougile-chat-list)
  - [`yougile chat view`](#yougile-chat-view)
  - [`yougile chat create`](#yougile-chat-create)
  - [`yougile chat edit`](#yougile-chat-edit)
  - [`yougile chat delete`](#yougile-chat-delete)
  - [`yougile chat send`](#yougile-chat-send)
  - [`yougile chat messages`](#yougile-chat-messages)
  - [`yougile chat typing`](#yougile-chat-typing)
  - [`yougile chat message view`](#yougile-chat-message-view)
  - [`yougile chat message edit`](#yougile-chat-message-edit)
  - [`yougile chat message delete`](#yougile-chat-message-delete)
- [webhook: подписки на события](#webhook-подписки-на-события)
  - [`yougile webhook list`](#yougile-webhook-list)
  - [`yougile webhook view`](#yougile-webhook-view)
  - [`yougile webhook create`](#yougile-webhook-create)
  - [`yougile webhook edit`](#yougile-webhook-edit)
  - [`yougile webhook delete`](#yougile-webhook-delete)
  - [`yougile webhook events`](#yougile-webhook-events)
- [company: компания](#company-компания)
  - [`yougile company view`](#yougile-company-view)
  - [`yougile company edit`](#yougile-company-edit)
- [file: файлы](#file-файлы)
  - [`yougile file upload`](#yougile-file-upload)
  - [`yougile file download`](#yougile-file-download)
- [crm: CRM](#crm-crm)
  - [`yougile crm contact create`](#yougile-crm-contact-create)
  - [`yougile crm contact view`](#yougile-crm-contact-view)
- [config: настройки](#config-настройки)
  - [`yougile config get`](#yougile-config-get)
  - [`yougile config set`](#yougile-config-set)
  - [`yougile config list`](#yougile-config-list)
  - [`yougile config clear-cache`](#yougile-config-clear-cache)
- [alias: алиасы](#alias-алиасы)
  - [`yougile alias list`](#yougile-alias-list)
  - [`yougile alias set`](#yougile-alias-set)
  - [`yougile alias delete`](#yougile-alias-delete)
- [completion: автодополнение](#completion-автодополнение)
  - [`yougile completion`](#yougile-completion)
  - [`yougile completion install`](#yougile-completion-install)

## Верхний уровень

Команды, которые не привязаны к одной сущности.

### `yougile api`

Произвольный запрос к API YouGile

```
yougile api [ОПЦИИ] {ЭНДПОИНТ}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ЭНДПОИНТ` | да | — | Путь API: task-list, /task-list или /api-v2/task-list |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `-X`, `--method` | `МЕТОД` | — | — | HTTP-метод; по умолчанию GET, с телом — POST |
| `-f`, `--raw-field` | `ПОЛЕ=ЗНАЧЕНИЕ` | — | — | Строковое поле (можно повторять) |
| `-F`, `--field` | `ПОЛЕ=ЗНАЧЕНИЕ` | — | — | Типизированное поле: true/false/null/число/JSON/@файл. Можно повторять. |
| `--input` | `ФАЙЛ` | — | — | Тело запроса из файла; «-» — из stdin |
| `-H`, `--header` | `ЗАГОЛОВОК` | — | — | Заголовок в виде "Имя: значение" (можно повторять) |
| `--paginate` | — | — | — | Пройти все страницы по paging.offset и склеить content |
| `-q`, `--jq` | `ВЫРАЖЕНИЕ` | — | — | Отфильтровать JSON выражением jq |
| `-i`, `--include` | — | — | — | Напечатать строку статуса и заголовки ответа |
| `--silent` | — | — | — | Не печатать тело ответа |
| `--verbose` | — | — | — | Вывести отправляемый запрос в stderr |

Пример:

```bash
yougile api 'task-list?columnId=5f1c0e1a' --paginate --jq '.[] | .title'
```

### `yougile browse`

Открыть задачу, доску или проект в браузере

```
yougile browse [ОПЦИИ] [ЦЕЛЬ]
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ЦЕЛЬ` | нет | — | Задача, доска, проект или ссылка; без цели — корень хоста |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--task`, `-t` | — | — | — | Считать цель задачей |
| `--board`, `-b` | — | — | — | Считать цель доской |
| `--project`, `-p` | — | — | — | Считать цель проектом |
| `--no-browser`, `-n` | — | — | — | Напечатать ссылку, не открывая браузер |

Пример:

```bash
yougile browse ILS-343 --no-browser
```

### `yougile status`

Мои незакрытые задачи, сгруппированные по доскам

```
yougile status [ОПЦИИ]
```

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--limit`, `-L` | `ЧИСЛО` | `30` | — | Сколько элементов показать; 0 — все |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с этими полями (через запятую) |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON |

Пример:

```bash
yougile status --limit 10
```

### `yougile version`

Показать версию CLI и окружения

```
yougile version [ОПЦИИ]
```

Пример:

```bash
yougile version
```

## auth: авторизация

Вход, учётные записи и реестр API-ключей.

### `yougile auth login`

Войти в аккаунт YouGile и сохранить API-ключ

```
yougile auth login [ОПЦИИ]
```

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--hostname` | `ХОСТ` | — | — | Хост YouGile |
| `--with-token` | — | — | — | Прочитать готовый API-ключ из stdin |
| `--company`, `-c` | `КОМПАНИЯ` | — | — | ID или название компании |
| `--user`, `-u` | `ПОЧТА` | — | — | Email для входа |
| `--new-key` | — | — | — | Всегда создавать новый ключ, не переиспользуя существующий |

Пример:

```bash
yougile auth login --user ivan@example.com --company 'Моя компания'
```

### `yougile auth logout`

Удалить сохранённую учётную запись

```
yougile auth logout [ОПЦИИ]
```

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--hostname` | `ХОСТ` | — | — | Хост YouGile |
| `--user`, `-u` | `ПОЧТА` | — | — | Учётная запись (email) |
| `--yes`, `-y` | — | — | — | Не спрашивать подтверждение |

Пример:

```bash
yougile auth logout --user ivan@example.com --yes
```

### `yougile auth status`

Показать состояние аутентификации

```
yougile auth status [ОПЦИИ]
```

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--hostname` | `ХОСТ` | — | — | Хост YouGile |
| `--show-token`, `-t` | — | — | — | Показать ключ целиком |
| `--active` | — | — | — | Только активная учётная запись |

Пример:

```bash
yougile auth status --active
```

### `yougile auth token`

Напечатать API-ключ учётной записи

```
yougile auth token [ОПЦИИ]
```

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--hostname` | `ХОСТ` | — | — | Хост YouGile |
| `--user`, `-u` | `ПОЧТА` | — | — | Учётная запись (email) |

Пример:

```bash
yougile auth token --user ivan@example.com
```

### `yougile auth switch`

Переключиться на другую сохранённую учётную запись

```
yougile auth switch [ОПЦИИ]
```

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--hostname` | `ХОСТ` | — | — | Хост YouGile |
| `--user`, `-u` | `ПОЧТА` | — | — | Учётная запись (email) |

Пример:

```bash
yougile auth switch --user ivan@example.com
```

### `yougile auth refresh`

Перевыпустить API-ключ активной учётной записи

```
yougile auth refresh [ОПЦИИ]
```

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--hostname` | `ХОСТ` | — | — | Хост YouGile |

Пример:

```bash
yougile auth refresh
```

### `yougile auth keys list`

Показать API-ключи аккаунта

```
yougile auth keys list [ОПЦИИ]
```

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--hostname` | `ХОСТ` | — | — | Хост YouGile |
| `--user`, `-u` | `ПОЧТА` | — | — | Email для входа |
| `--company`, `-c` | `КОМПАНИЯ` | — | — | ID или название компании |
| `--include-deleted` | — | — | — | Показывать также удалённые ключи |
| `--show-token`, `-t` | — | — | — | Показать ключи целиком |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с указанными полями |
| `-q`, `--jq` | `ВЫРАЖЕНИЕ` | — | — | Прогнать JSON через jq |
| `-L`, `--limit` | `ЧИСЛО` | `30` | — | Сколько записей вывести; 0 — все |
| `--full-ids` | — | — | — | Не сокращать идентификаторы |

Пример:

```bash
yougile auth keys list --user ivan@example.com --company 'Моя компания'
```

### `yougile auth keys create`

Создать новый API-ключ

```
yougile auth keys create [ОПЦИИ]
```

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--hostname` | `ХОСТ` | — | — | Хост YouGile |
| `--user`, `-u` | `ПОЧТА` | — | — | Email для входа |
| `--company`, `-c` | `КОМПАНИЯ` | — | — | ID или название компании |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с указанными полями |
| `-q`, `--jq` | `ВЫРАЖЕНИЕ` | — | — | Прогнать JSON через jq |

Пример:

```bash
yougile auth keys create --user ivan@example.com --company 'Моя компания'
```

### `yougile auth keys delete`

Удалить API-ключ

```
yougile auth keys delete [ОПЦИИ] {КЛЮЧ}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `КЛЮЧ` | да | — | Значение ключа |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--hostname` | `ХОСТ` | — | — | Хост YouGile |
| `--yes`, `-y` | — | — | — | Не спрашивать подтверждение |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с указанными полями |
| `-q`, `--jq` | `ВЫРАЖЕНИЕ` | — | — | Прогнать JSON через jq |

Пример:

```bash
yougile auth keys delete 0123456789abcdef --yes
```

## project: проекты

Проекты компании и роли внутри проекта.

### `yougile project list`

Список проектов.

```
yougile project list [ОПЦИИ]
```

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--search`, `-S` | `ТЕКСТ` | — | — | Фильтр по названию проекта |
| `--include-deleted` | — | — | — | Показывать в том числе удалённые проекты |
| `--limit`, `-L` | `ЧИСЛО` | `30` | — | Сколько записей вернуть; 0 — все |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON-вывода |
| `--full-ids` | — | — | — | Показывать идентификаторы целиком |

Пример:

```bash
yougile project list --search Разработка --limit 0
```

### `yougile project view`

Показать проект.

```
yougile project view [ОПЦИИ] {ПРОЕКТ}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ПРОЕКТ` | да | — | ID, ссылка или название проекта |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON-вывода |
| `--full-ids` | — | — | — | Показывать идентификаторы целиком |

Пример:

```bash
yougile project view Разработка
```

### `yougile project create`

Создать проект.

```
yougile project create [ОПЦИИ] [НАЗВАНИЕ]
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `НАЗВАНИЕ` | нет | — | Название (можно передать и флагом --title) |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--title`, `-t` | `НАЗВАНИЕ` | — | — | Название; синоним позиционного аргумента НАЗВАНИЕ |
| `--user`, `-u` | `СОТРУДНИК=РОЛЬ` | — | — | Участник в формате id=роль (можно повторять); вместо ID можно указать email |
| `--department`, `-d` | `ОТДЕЛ=РОЛЬ` | — | — | Отдел в формате id=роль (можно повторять); вместо ID можно указать название |
| `--idempotency-key` | `КЛЮЧ` | — | — | Ключ идемпотентности: повторный запрос с тем же ключом не создаст дубликат |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON-вывода |

Пример:

```bash
yougile project create 'Ремонт офиса' --user ivan@example.com=admin
```

### `yougile project edit`

Изменить проект.

```
yougile project edit [ОПЦИИ] {ПРОЕКТ}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ПРОЕКТ` | да | — | ID, ссылка или название проекта |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--title`, `-t` | `НАЗВАНИЕ` | — | — | Новое название проекта |
| `--user`, `-u` | `СОТРУДНИК=РОЛЬ` | — | — | Участник в формате id=роль (можно повторять); вместо ID можно указать email |
| `--department`, `-d` | `ОТДЕЛ=РОЛЬ` | — | — | Отдел в формате id=роль (можно повторять); вместо ID можно указать название |
| `--undelete` | — | — | — | Восстановить удалённый проект |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON-вывода |

Пример:

```bash
yougile project edit 'Ремонт офиса' --title 'Ремонт офиса 2026'
```

### `yougile project delete`

Удалить проект (пометить удалённым).

```
yougile project delete [ОПЦИИ] {ПРОЕКТ}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ПРОЕКТ` | да | — | ID, ссылка или название проекта |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--yes`, `-y` | — | — | — | Не спрашивать подтверждение |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON-вывода |

Пример:

```bash
yougile project delete 'Ремонт офиса' --yes
```

### `yougile project role list`

Список ролей проекта.

```
yougile project role list [ОПЦИИ] {ПРОЕКТ}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ПРОЕКТ` | да | — | ID, ссылка или название проекта |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--search`, `-S` | `ТЕКСТ` | — | — | Фильтр по названию роли |
| `--limit`, `-L` | `ЧИСЛО` | `30` | — | Сколько записей вернуть; 0 — все |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON-вывода |
| `--full-ids` | — | — | — | Показывать идентификаторы целиком |

Пример:

```bash
yougile project role list Разработка
```

### `yougile project role view`

Показать роль вместе с деревом прав.

```
yougile project role view [ОПЦИИ] {ПРОЕКТ} {РОЛЬ}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ПРОЕКТ` | да | — | ID, ссылка или название проекта |
| `РОЛЬ` | да | — | ID или название роли |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON-вывода |
| `--full-ids` | — | — | — | Показывать идентификаторы целиком |

Пример:

```bash
yougile project role view Разработка Тестировщик
```

### `yougile project role create`

Создать роль проекта.

```
yougile project role create [ОПЦИИ] {ПРОЕКТ} [НАЗВАНИЕ]
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ПРОЕКТ` | да | — | ID, ссылка или название проекта |
| `НАЗВАНИЕ` | нет | — | Название роли (синоним --name) |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--name`, `-n` | `НАЗВАНИЕ` | — | — | Название роли; синоним НАЗВАНИЕ |
| `--permissions-file`, `-p` | `ФАЙЛ` | — | да | JSON-файл с деревом прав доступа; «-» — читать из stdin |
| `--description` | `ТЕКСТ` | — | — | Описание роли |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON-вывода |

Пример:

```bash
yougile project role create Разработка Тестировщик --permissions-file perms.json
```

### `yougile project role edit`

Изменить роль проекта.

```
yougile project role edit [ОПЦИИ] {ПРОЕКТ} {РОЛЬ}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ПРОЕКТ` | да | — | ID, ссылка или название проекта |
| `РОЛЬ` | да | — | ID или название роли |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--name`, `-n` | `НАЗВАНИЕ` | — | — | Новое название роли |
| `--description` | `ТЕКСТ` | — | — | Новое описание роли |
| `--permissions-file`, `-p` | `ФАЙЛ` | — | — | JSON-файл с деревом прав доступа; «-» — читать из stdin |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON-вывода |

Пример:

```bash
yougile project role edit Разработка Тестировщик --name QA
```

### `yougile project role delete`

Удалить роль проекта.

```
yougile project role delete [ОПЦИИ] {ПРОЕКТ} {РОЛЬ}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ПРОЕКТ` | да | — | ID, ссылка или название проекта |
| `РОЛЬ` | да | — | ID или название роли |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--yes`, `-y` | — | — | — | Не спрашивать подтверждение |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON-вывода |

Пример:

```bash
yougile project role delete Разработка QA --yes
```

## board: доски

Доски проектов: список, дерево, создание, изменение.

### `yougile board list`

Список досок.

```
yougile board list [ОПЦИИ]
```

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--project`, `-p` | `ПРОЕКТ` | — | — | Проект: ID, имя или ссылка |
| `--search`, `-S` | `ТЕКСТ` | — | — | Искать по имени доски |
| `--limit`, `-L` | `ЧИСЛО` | `30` | — | Сколько элементов показать; 0 — все |
| `--include-deleted` | — | — | — | Показывать удалённые |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с этими полями (через запятую) |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON |

Пример:

```bash
yougile board list --project Разработка
```

### `yougile board view`

Показать доску.

```
yougile board view [ОПЦИИ] {ДОСКА}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ДОСКА` | да | — | Доска: ID, имя или ссылка |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--project`, `-p` | `ПРОЕКТ` | — | — | Проект: ID, имя или ссылка |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с этими полями (через запятую) |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON |

Пример:

```bash
yougile board view 'Спринт 12' --project Разработка
```

### `yougile board create`

Создать доску.

```
yougile board create [ОПЦИИ] [НАЗВАНИЕ]
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `НАЗВАНИЕ` | нет | — | Название новой доски (можно передать и флагом --title) |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--project`, `-p` | `ПРОЕКТ` | — | да | Проект: ID, имя или ссылка |
| `--title`, `-t` | `НАЗВАНИЕ` | — | — | Название доски; синоним позиционного аргумента НАЗВАНИЕ |
| `--timer` / `--no-timer` | — | не задан | — | Стикер «таймер» на карточках доски |
| `--deadline` / `--no-deadline` | — | не задан | — | Стикер «дедлайн» на карточках доски |
| `--stopwatch` / `--no-stopwatch` | — | не задан | — | Стикер «секундомер» на карточках доски |
| `--time-tracking` / `--no-time-tracking` | — | не задан | — | Стикер «таймтрекинг» на карточках доски |
| `--assignee` / `--no-assignee` | — | не задан | — | Стикер «исполнитель» на карточках доски |
| `--repeat` / `--no-repeat` | — | не задан | — | Стикер «повтор» на карточках доски |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с этими полями (через запятую) |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON |

Пример:

```bash
yougile board create 'Спринт 13' --project Разработка --deadline --assignee
```

### `yougile board edit`

Изменить доску.

```
yougile board edit [ОПЦИИ] {ДОСКА}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ДОСКА` | да | — | Доска: ID, имя или ссылка |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--title`, `-t` | `НАЗВАНИЕ` | — | — | Новое название доски |
| `--project`, `-p` | `ПРОЕКТ` | — | — | Перенести доску в другой проект |
| `--timer` / `--no-timer` | — | не задан | — | Стикер «таймер» на карточках доски |
| `--deadline` / `--no-deadline` | — | не задан | — | Стикер «дедлайн» на карточках доски |
| `--stopwatch` / `--no-stopwatch` | — | не задан | — | Стикер «секундомер» на карточках доски |
| `--time-tracking` / `--no-time-tracking` | — | не задан | — | Стикер «таймтрекинг» на карточках доски |
| `--assignee` / `--no-assignee` | — | не задан | — | Стикер «исполнитель» на карточках доски |
| `--repeat` / `--no-repeat` | — | не задан | — | Стикер «повтор» на карточках доски |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с этими полями (через запятую) |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON |

Пример:

```bash
yougile board edit 'Спринт 13' --title 'Спринт 13 (закрыт)' --no-timer
```

### `yougile board delete`

Удалить доску.

```
yougile board delete [ОПЦИИ] {ДОСКА}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ДОСКА` | да | — | Доска: ID, имя или ссылка |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--project`, `-p` | `ПРОЕКТ` | — | — | Проект: ID, имя или ссылка |
| `--yes`, `-y` | — | — | — | Не спрашивать подтверждение |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с этими полями (через запятую) |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON |

Пример:

```bash
yougile board delete 'Спринт 13' --project Разработка --yes
```

### `yougile board tree`

Дерево доски: колонки и задачи в них.

```
yougile board tree [ОПЦИИ] {ДОСКА}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ДОСКА` | да | — | Доска: ID, имя или ссылка |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--project`, `-p` | `ПРОЕКТ` | — | — | Проект: ID, имя или ссылка |
| `--limit`, `-L` | `ЧИСЛО` | `30` | — | Сколько задач показать в колонке; 0 — все |
| `--include-deleted` | — | — | — | Показывать удалённые |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с этими полями (через запятую) |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON |

Пример:

```bash
yougile board tree 'Спринт 12' --limit 0
```

## column: колонки

Колонки досок.

### `yougile column list`

Показать колонки, при необходимости только одной доски.

```
yougile column list [ОПЦИИ]
```

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--board`, `-b` | `ДОСКА` | — | — | Доска для поиска колонки по имени: ID, имя или ссылка |
| `--search`, `-S` | `ТЕКСТ` | — | — | Фильтр по имени колонки |
| `--include-deleted` | — | — | — | Показывать удалённые колонки |
| `--limit`, `-L` | `ЧИСЛО` | `30` | — | Сколько колонок показать; 0 — все |
| `--json` | `ПОЛЯ` | — | — | JSON только с этими полями через запятую; --json "" печатает список полей |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Прогнать JSON через фильтр jq |

Пример:

```bash
yougile column list --board 'Спринт 12'
```

### `yougile column view`

Показать одну колонку.

```
yougile column view [ОПЦИИ] {КОЛОНКА}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `КОЛОНКА` | да | — | Колонка: ID, имя или ссылка |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--board`, `-b` | `ДОСКА` | — | — | Доска для поиска колонки по имени: ID, имя или ссылка |
| `--json` | `ПОЛЯ` | — | — | JSON только с этими полями через запятую; --json "" печатает список полей |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Прогнать JSON через фильтр jq |

Пример:

```bash
yougile column view 'В работе' --board 'Спринт 12'
```

### `yougile column create`

Создать колонку на доске.

```
yougile column create [ОПЦИИ] [НАЗВАНИЕ]
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `НАЗВАНИЕ` | нет | — | Название новой колонки (можно передать и --title) |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--board`, `-b` | `ДОСКА` | — | да | Доска: ID, имя или ссылка |
| `--title`, `-t` | `НАЗВАНИЕ` | — | — | Название колонки; синоним аргумента НАЗВАНИЕ |
| `--color`, `-c` | `ЧИСЛО` | — | — | Цвет колонки: индекс палитры от 1 до 16 |
| `--json` | `ПОЛЯ` | — | — | JSON только с этими полями через запятую; --json "" печатает список полей |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Прогнать JSON через фильтр jq |

Пример:

```bash
yougile column create 'На ревью' --board 'Спринт 12' --color 7
```

### `yougile column edit`

Переименовать колонку или сменить её цвет.

```
yougile column edit [ОПЦИИ] {КОЛОНКА}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `КОЛОНКА` | да | — | Колонка: ID, имя или ссылка |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--title`, `-t` | `НАЗВАНИЕ` | — | — | Новое название колонки |
| `--color`, `-c` | `ЧИСЛО` | — | — | Цвет колонки: индекс палитры от 1 до 16 |
| `--board`, `-b` | `ДОСКА` | — | — | Доска для поиска колонки по имени: ID, имя или ссылка |
| `--json` | `ПОЛЯ` | — | — | JSON только с этими полями через запятую; --json "" печатает список полей |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Прогнать JSON через фильтр jq |

Пример:

```bash
yougile column edit 'На ревью' --board 'Спринт 12' --title 'Ревью' --color 3
```

### `yougile column delete`

Удалить колонку.

```
yougile column delete [ОПЦИИ] {КОЛОНКА}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `КОЛОНКА` | да | — | Колонка: ID, имя или ссылка |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--board`, `-b` | `ДОСКА` | — | — | Доска для поиска колонки по имени: ID, имя или ссылка |
| `--yes`, `-y` | — | — | — | Не спрашивать подтверждение |
| `--json` | `ПОЛЯ` | — | — | JSON только с этими полями через запятую; --json "" печатает список полей |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Прогнать JSON через фильтр jq |

Пример:

```bash
yougile column delete Ревью --board 'Спринт 12' --yes
```

### `yougile column move`

Перенести колонку на другую доску.

```
yougile column move [ОПЦИИ] {КОЛОНКА}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `КОЛОНКА` | да | — | Колонка: ID, имя или ссылка |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--board`, `-b` | `ДОСКА` | — | да | Доска назначения: ID, имя или ссылка |
| `--json` | `ПОЛЯ` | — | — | JSON только с этими полями через запятую; --json "" печатает список полей |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Прогнать JSON через фильтр jq |

Пример:

```bash
yougile column move Ревью --board 'Спринт 13'
```

## task: задачи

Задачи: поиск, создание, изменение, перемещение, вложения и участники чата.

### `yougile task list`

Список задач с фильтрами по исполнителю, состоянию и месту.

```
yougile task list [ОПЦИИ]
```

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--assignee`, `-a` | `ИСПОЛНИТЕЛЬ` | — | — | Исполнитель: @me, почта, имя или ID. Можно повторять. |
| `--state`, `-s` | `open\|closed\|all` | `open` | — | Состояние: open, closed или all |
| `--column`, `-c` | `КОЛОНКА` | — | — | Колонка (ID или название) |
| `--board`, `-b` | `ДОСКА` | — | — | Доска: опрашиваются все её колонки |
| `--project`, `-p` | `ПРОЕКТ` | — | — | Проект: все доски и колонки проекта |
| `--search`, `-S` | `ТЕКСТ` | — | — | Поиск по заголовку задачи |
| `--sticker` | `СТИКЕР` | — | — | ID стикера |
| `--sticker-state` | `ID` | — | — | ID состояния стикера |
| `--include-deleted` | — | — | — | Показывать удалённые задачи |
| `--archived` / `--no-archived` | — | не задан | — | Только архивные / только неархивные |
| `--limit`, `-L` | `ЧИСЛО` | `30` | — | Сколько задач показать, 0 — все |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON с перечисленными полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq по JSON-выводу |
| `--full-ids` | — | — | — | Показывать ID целиком |

Пример:

```bash
yougile task list --assignee @me --state open --board 'Спринт 12'
```

### `yougile task view`

Подробности задачи: поля, чек-листы, подзадачи и, по флагу, чат.

```
yougile task view [ОПЦИИ] {ЗАДАЧА}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ЗАДАЧА` | да | — | Задача: код, ID, ссылка или заголовок |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--comments` | — | — | — | Показать чат задачи |
| `--raw-description` | — | — | — | Печатать описание исходным HTML |
| `--limit`, `-L` | `ЧИСЛО` | `30` | — | Сколько комментариев показать, 0 — все |
| `--web`, `-w` | — | — | — | Открыть задачу в браузере |
| `--no-browser` | — | — | — | Напечатать ссылку вместо открытия браузера |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON с перечисленными полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq по JSON-выводу |
| `--full-ids` | — | — | — | Показывать ID целиком |

Пример:

```bash
yougile task view ILS-343
```

### `yougile task attachments`

Файлы, приложенные к задаче в описании и в чате.

```
yougile task attachments [ОПЦИИ] {ЗАДАЧА}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ЗАДАЧА` | да | — | Задача: код, ID, ссылка или заголовок |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--download` | — | — | — | Скачать все найденные файлы |
| `--dir` | `КАТАЛОГ` | — | — | Куда скачивать; по умолчанию текущий |
| `--source` | `описание\|чат\|все` | `все` | — | Где искать вложения |
| `--force`, `-f` | — | — | — | Перезаписывать существующие файлы |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON с перечисленными полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq по JSON-выводу |

Пример:

```bash
yougile task attachments ILS-343 --download --dir ~/Downloads/ILS-343
```

### `yougile task create`

Создать задачу и напечатать ссылку на неё.

```
yougile task create [ОПЦИИ] [ЗАГОЛОВОК]
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ЗАГОЛОВОК` | нет | — | Заголовок задачи |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--title`, `-t` | `ЗАГОЛОВОК` | — | — | Заголовок задачи |
| `--column`, `-c` | `КОЛОНКА` | — | — | Колонка (ID или название) |
| `--board`, `-b` | `ДОСКА` | — | — | Доска для уточнения колонки по названию |
| `--body` | `ТЕКСТ` | — | — | Описание задачи |
| `--body-file`, `-F` | `ФАЙЛ` | — | — | Файл с описанием, «-» — stdin |
| `--editor`, `-e` | — | — | — | Написать описание в $EDITOR |
| `--assignee`, `-a` | `ИСПОЛНИТЕЛЬ` | — | — | Исполнитель: @me, почта, имя или ID. Можно повторять. |
| `--subtask` | `ЗАДАЧА` | — | — | Подзадача: ID, ссылка или заголовок. Можно повторять. |
| `--deadline` | `ДАТА` | — | — | Дедлайн «ГГГГ-ММ-ДД[ ЧЧ:ММ]» |
| `--start-date` | `ДАТА` | — | — | Дата начала «ГГГГ-ММ-ДД[ ЧЧ:ММ]» |
| `--color` | `ЦВЕТ` | — | — | Цвет: task-primary, task-gray, task-red, task-pink, task-yellow, task-green, task-turquoise, task-blue, task-violet |
| `--plan-hours` | `ЧИСЛО` | — | — | Плановые трудозатраты в часах |
| `--checklist` | `ЧЕК-ЛИСТ` | — | — | Чек-лист «Название:пункт1,пункт2». Можно повторять. |
| `--sticker` | `СТИКЕР` | — | — | Стикер в формате ID=СОСТОЯНИЕ. Можно повторять. |
| `--archived` | — | — | — | Создать сразу в архиве |
| `--completed` | — | — | — | Создать сразу выполненной |
| `--idempotency-key` | `КЛЮЧ` | — | — | Ключ идемпотентности |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON с перечисленными полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq по JSON-выводу |

Пример:

```bash
yougile task create 'Починить оплату' --board 'Спринт 12' --column 'В работе' \
  --assignee @me --deadline '2026-09-15 18:00'
```

### `yougile task edit`

Изменить поля задачи.

```
yougile task edit [ОПЦИИ] {ЗАДАЧА}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ЗАДАЧА` | да | — | Задача: код, ID, ссылка или заголовок |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--title`, `-t` | `ЗАГОЛОВОК` | — | — | Новый заголовок |
| `--column`, `-c` | `КОЛОНКА` | — | — | Переместить в колонку |
| `--board`, `-b` | `ДОСКА` | — | — | Доска для уточнения колонки по названию |
| `--body` | `ТЕКСТ` | — | — | Новое описание |
| `--body-file`, `-F` | `ФАЙЛ` | — | — | Файл с описанием, «-» — stdin |
| `--editor`, `-e` | — | — | — | Править описание в $EDITOR |
| `--assignee`, `-a` | `ИСПОЛНИТЕЛЬ` | — | — | Заменить список исполнителей. Можно повторять. |
| `--subtask` | `ЗАДАЧА` | — | — | Заменить список подзадач. Можно повторять. |
| `--deadline` | `ДАТА` | — | — | Дедлайн «ГГГГ-ММ-ДД[ ЧЧ:ММ]» |
| `--start-date` | `ДАТА` | — | — | Дата начала «ГГГГ-ММ-ДД[ ЧЧ:ММ]» |
| `--clear-deadline` | — | — | — | Убрать дедлайн |
| `--color` | `ЦВЕТ` | — | — | Цвет: task-primary, task-gray, task-red, task-pink, task-yellow, task-green, task-turquoise, task-blue, task-violet |
| `--plan-hours` | `ЧИСЛО` | — | — | Плановые трудозатраты в часах |
| `--checklist` | `ЧЕК-ЛИСТ` | — | — | Заменить чек-листы. Можно повторять. |
| `--sticker` | `СТИКЕР` | — | — | Стикер в формате ID=СОСТОЯНИЕ. Можно повторять. |
| `--archived` / `--no-archived` | — | не задан | — | В архив / из архива |
| `--completed` / `--no-completed` | — | не задан | — | Выполнена / не выполнена |
| `--undelete` | — | — | — | Восстановить удалённую задачу |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON с перечисленными полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq по JSON-выводу |

Пример:

```bash
yougile task edit ILS-343 --title 'Починить оплату картой' --column 'На ревью'
```

### `yougile task close`

Отметить задачу выполненной.

```
yougile task close [ОПЦИИ] {ЗАДАЧА}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ЗАДАЧА` | да | — | Задача: код, ID, ссылка или заголовок |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON с перечисленными полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq по JSON-выводу |

Пример:

```bash
yougile task close ILS-343
```

### `yougile task reopen`

Вернуть задачу в работу.

```
yougile task reopen [ОПЦИИ] {ЗАДАЧА}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ЗАДАЧА` | да | — | Задача: код, ID, ссылка или заголовок |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON с перечисленными полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq по JSON-выводу |

Пример:

```bash
yougile task reopen ILS-343
```

### `yougile task archive`

Убрать задачу в архив.

```
yougile task archive [ОПЦИИ] {ЗАДАЧА}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ЗАДАЧА` | да | — | Задача: код, ID, ссылка или заголовок |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON с перечисленными полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq по JSON-выводу |

Пример:

```bash
yougile task archive ILS-343
```

### `yougile task unarchive`

Достать задачу из архива.

```
yougile task unarchive [ОПЦИИ] {ЗАДАЧА}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ЗАДАЧА` | да | — | Задача: код, ID, ссылка или заголовок |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON с перечисленными полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq по JSON-выводу |

Пример:

```bash
yougile task unarchive ILS-343
```

### `yougile task delete`

Удалить задачу.

```
yougile task delete [ОПЦИИ] {ЗАДАЧА}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ЗАДАЧА` | да | — | Задача: код, ID, ссылка или заголовок |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--yes`, `-y` | — | — | — | Не спрашивать подтверждение |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON с перечисленными полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq по JSON-выводу |

Пример:

```bash
yougile task delete ILS-343 --yes
```

### `yougile task move`

Перенести задачу в другую колонку.

```
yougile task move [ОПЦИИ] {ЗАДАЧА} [КОЛОНКА]
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ЗАДАЧА` | да | — | Задача: код, ID, ссылка или заголовок |
| `КОЛОНКА` | нет | — | Колонка назначения: ID или название |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--column`, `-c` | `КОЛОНКА` | — | — | То же, что позиционный аргумент |
| `--board`, `-b` | `ДОСКА` | — | — | Доска для уточнения колонки |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON с перечисленными полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq по JSON-выводу |

Пример:

```bash
yougile task move ILS-343 'На ревью' --board 'Спринт 12'
```

### `yougile task assign`

Добавить исполнителей к задаче.

```
yougile task assign [ОПЦИИ] {ЗАДАЧА} [ИСПОЛНИТЕЛЬ...]
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ЗАДАЧА` | да | — | Задача: код, ID, ссылка или заголовок |
| `ИСПОЛНИТЕЛЬ...` | нет | — | @me, почта, имя или ID |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--assignee`, `-a` | `ИСПОЛНИТЕЛЬ` | — | — | То же, что позиционный аргумент. Можно повторять. |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON с перечисленными полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq по JSON-выводу |

Пример:

```bash
yougile task assign ILS-343 @me petr@example.com
```

### `yougile task unassign`

Убрать исполнителей из задачи.

```
yougile task unassign [ОПЦИИ] {ЗАДАЧА} [ИСПОЛНИТЕЛЬ...]
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ЗАДАЧА` | да | — | Задача: код, ID, ссылка или заголовок |
| `ИСПОЛНИТЕЛЬ...` | нет | — | @me, почта, имя или ID |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--assignee`, `-a` | `ИСПОЛНИТЕЛЬ` | — | — | То же, что позиционный аргумент. Можно повторять. |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON с перечисленными полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq по JSON-выводу |

Пример:

```bash
yougile task unassign ILS-343 petr@example.com
```

### `yougile task comment`

Написать в чат задачи.

```
yougile task comment [ОПЦИИ] {ЗАДАЧА} [ТЕКСТ]
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ЗАДАЧА` | да | — | Задача: код, ID, ссылка или заголовок |
| `ТЕКСТ` | нет | — | Текст |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--body` | `ТЕКСТ` | — | — | Текст комментария |
| `--body-file`, `-F` | `ФАЙЛ` | — | — | Файл с текстом, «-» — stdin |
| `--editor`, `-e` | — | — | — | Написать комментарий в $EDITOR |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON с перечисленными полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq по JSON-выводу |

Пример:

```bash
yougile task comment ILS-343 'Выкатил на прод'
```

### `yougile task subscribers list`

Показать участников чата задачи.

```
yougile task subscribers list [ОПЦИИ] {ЗАДАЧА}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ЗАДАЧА` | да | — | Задача: код, ID, ссылка или заголовок |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON с перечисленными полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq по JSON-выводу |
| `--full-ids` | — | — | — | Показывать ID целиком |

Пример:

```bash
yougile task subscribers list ILS-343
```

### `yougile task subscribers add`

Добавить участников в чат задачи.

```
yougile task subscribers add [ОПЦИИ] {ЗАДАЧА} [СОТРУДНИК...]
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ЗАДАЧА` | да | — | Задача: код, ID, ссылка или заголовок |
| `СОТРУДНИК...` | нет | — | @me, почта, имя или ID |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON с перечисленными полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq по JSON-выводу |

Пример:

```bash
yougile task subscribers add ILS-343 petr@example.com
```

### `yougile task subscribers remove`

Убрать участников из чата задачи.

```
yougile task subscribers remove [ОПЦИИ] {ЗАДАЧА} [СОТРУДНИК...]
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ЗАДАЧА` | да | — | Задача: код, ID, ссылка или заголовок |
| `СОТРУДНИК...` | нет | — | @me, почта, имя или ID |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON с перечисленными полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq по JSON-выводу |

Пример:

```bash
yougile task subscribers remove ILS-343 petr@example.com
```

### `yougile task subscribers set`

Заменить список участников чата задачи.

```
yougile task subscribers set [ОПЦИИ] {ЗАДАЧА} [СОТРУДНИК...]
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ЗАДАЧА` | да | — | Задача: код, ID, ссылка или заголовок |
| `СОТРУДНИК...` | нет | — | @me, почта, имя или ID |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON с перечисленными полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq по JSON-выводу |

Пример:

```bash
yougile task subscribers set ILS-343 @me petr@example.com
```

## user: сотрудники

Сотрудники компании.

### `yougile user list`

Список сотрудников компании

```
yougile user list [ОПЦИИ]
```

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--email` | `ПОЧТА` | — | — | Фильтр по почте сотрудника |
| `--project` | `ПРОЕКТ` | — | — | Только участники проекта (ID или название) |
| `--search`, `-S` | `ТЕКСТ` | — | — | Поиск по имени или почте |
| `-L`, `--limit` | `ЧИСЛО` | `30` | — | Сколько сотрудников показать (0 — все) |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с указанными полями (через запятую) |
| `-q`, `--jq` | `ВЫРАЖЕНИЕ` | — | — | Прогнать JSON через фильтр jq |

Пример:

```bash
yougile user list --project Разработка --search Иван
```

### `yougile user view`

Карточка сотрудника: @me, ID, почта или имя

```
yougile user view [ОПЦИИ] [СОТРУДНИК]
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `СОТРУДНИК` | нет | `@me` | @me, ID, почта или имя сотрудника |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с указанными полями (через запятую) |
| `-q`, `--jq` | `ВЫРАЖЕНИЕ` | — | — | Прогнать JSON через фильтр jq |

Пример:

```bash
yougile user view @me
```

### `yougile user invite`

Пригласить сотрудника в компанию

```
yougile user invite [ОПЦИИ] [ПОЧТА]
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ПОЧТА` | нет | — | Почта приглашаемого сотрудника |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--email` | `ПОЧТА` | — | — | Та же почта, но флагом |
| `--admin` | — | — | — | Выдать права администратора |
| `--messenger-only` | — | — | — | Доступ только к мессенджеру |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с указанными полями (через запятую) |
| `-q`, `--jq` | `ВЫРАЖЕНИЕ` | — | — | Прогнать JSON через фильтр jq |

Пример:

```bash
yougile user invite petr@example.com --admin
```

### `yougile user edit`

Изменить права сотрудника

```
yougile user edit [ОПЦИИ] {СОТРУДНИК}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `СОТРУДНИК` | да | — | @me, ID, почта или имя сотрудника |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--admin` / `--no-admin` | — | не задан | — | Выдать или снять права администратора |
| `--messenger-only` / `--no-messenger-only` | — | не задан | — | Доступ только к мессенджеру |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с указанными полями (через запятую) |
| `-q`, `--jq` | `ВЫРАЖЕНИЕ` | — | — | Прогнать JSON через фильтр jq |

Пример:

```bash
yougile user edit petr@example.com --no-admin
```

### `yougile user delete`

Удалить сотрудника из компании

```
yougile user delete [ОПЦИИ] {СОТРУДНИК}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `СОТРУДНИК` | да | — | ID, почта или имя сотрудника |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--yes`, `-y` | — | — | — | Не спрашивать подтверждение |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с указанными полями (через запятую) |
| `-q`, `--jq` | `ВЫРАЖЕНИЕ` | — | — | Прогнать JSON через фильтр jq |

Пример:

```bash
yougile user delete petr@example.com --yes
```

## department: отделы

Отделы компании и их иерархия.

### `yougile department list`

Список отделов.

```
yougile department list [ОПЦИИ]
```

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--parent`, `-p` | `ОТДЕЛ` | — | — | Родительский отдел: ID или название. |
| `--search`, `-S` | `ТЕКСТ` | — | — | Искать по названию отдела. |
| `--include-deleted` | — | — | — | Показывать удалённые отделы. |
| `--limit`, `-L` | `ЧИСЛО` | `30` | — | Сколько отделов показать (0 — все). |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями. |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Прогнать JSON через выражение jq. |

Пример:

```bash
yougile department list --parent Разработка
```

### `yougile department view`

Показать отдел.

```
yougile department view [ОПЦИИ] {ОТДЕЛ}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ОТДЕЛ` | да | — | ID или название отдела. |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями. |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Прогнать JSON через выражение jq. |

Пример:

```bash
yougile department view Бэкенд
```

### `yougile department create`

Создать отдел.

```
yougile department create [ОПЦИИ] [НАЗВАНИЕ]
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `НАЗВАНИЕ` | нет | — | Название нового отдела. |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--title`, `-t` | `НАЗВАНИЕ` | — | — | То же название, но флагом. |
| `--parent`, `-p` | `ОТДЕЛ` | — | — | Родительский отдел: ID или название. |
| `--user`, `-u` | `КТО=РОЛЬ` | — | — | Сотрудник и его роль, можно повторять. |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями. |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Прогнать JSON через выражение jq. |

Пример:

```bash
yougile department create Бэкенд --parent Разработка --user ivan@example.com=admin
```

### `yougile department edit`

Изменить отдел.

```
yougile department edit [ОПЦИИ] {ОТДЕЛ}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ОТДЕЛ` | да | — | ID или название отдела. |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--title`, `-t` | `НАЗВАНИЕ` | — | — | Новое название. |
| `--parent`, `-p` | `ОТДЕЛ` | — | — | Родительский отдел: ID или название. |
| `--user`, `-u` | `КТО=РОЛЬ` | — | — | Сотрудник и его роль, можно повторять. |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями. |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Прогнать JSON через выражение jq. |

Пример:

```bash
yougile department edit Бэкенд --title 'Бэкенд и инфраструктура'
```

### `yougile department delete`

Удалить отдел.

```
yougile department delete [ОПЦИИ] {ОТДЕЛ}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ОТДЕЛ` | да | — | ID или название отдела. |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--yes`, `-y` | — | — | — | Не спрашивать подтверждение. |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями. |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Прогнать JSON через выражение jq. |

Пример:

```bash
yougile department delete Бэкенд --yes
```

### `yougile department tree`

Дерево отделов по parentId.

```
yougile department tree [ОПЦИИ] [ОТДЕЛ]
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ОТДЕЛ` | нет | — | Корневой отдел (ID или название). По умолчанию — все. |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--include-deleted` | — | — | — | Показывать удалённые отделы. |
| `--limit`, `-L` | `ЧИСЛО` | `0` | — | Сколько отделов показать (0 — все): дерево по умолчанию выводится целиком. |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями. |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Прогнать JSON через выражение jq. |

Пример:

```bash
yougile department tree Разработка
```

## sticker: стикеры

Стикеры двух видов: строковые (`string`) и спринты (`sprint`), у каждого — свои состояния.

### `yougile sticker string icons`

Показать допустимые иконки строкового стикера.

```
yougile sticker string icons [ОПЦИИ]
```

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Отфильтровать JSON выражением jq |

Пример:

```bash
yougile sticker string icons
```

### `yougile sticker string list`

Список строковых стикеров.

```
yougile sticker string list [ОПЦИИ]
```

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--search`, `-S` | `ТЕКСТ` | — | — | Фильтр по имени стикера |
| `--board`, `-b` | `ДОСКА` | — | — | Доска (ID, ссылка или название) |
| `--include-deleted` | — | — | — | Показывать удалённые объекты |
| `--limit`, `-L` | `ЧИСЛО` | `30` | — | Сколько записей показать (0 — все) |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Отфильтровать JSON выражением jq |

Пример:

```bash
yougile sticker string list --board 'Спринт 12'
```

### `yougile sticker string view`

Показать строковый стикер.

```
yougile sticker string view [ОПЦИИ] {СТИКЕР}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `СТИКЕР` | да | — | Стикер: ID или название |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Отфильтровать JSON выражением jq |

Пример:

```bash
yougile sticker string view Приоритет
```

### `yougile sticker string create`

Создать строковый стикер.

```
yougile sticker string create [ОПЦИИ] [НАЗВАНИЕ]
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `НАЗВАНИЕ` | нет | — | Название нового стикера |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--name`, `-n` | `НАЗВАНИЕ` | — | — | То же название, но флагом |
| `--icon`, `-i` | `ИКОНКА` | — | — | Иконка стикера; пустая строка — без иконки. Полный список: yougile sticker string icons |
| `--state`, `-s` | `СОСТОЯНИЕ` | — | — | Состояние «Название[:цвет]»; можно повторять |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Отфильтровать JSON выражением jq |

Пример:

```bash
yougile sticker string create Приоритет --icon flag --state 'Высокий:red' --state 'Низкий:green'
```

### `yougile sticker string edit`

Изменить строковый стикер.

```
yougile sticker string edit [ОПЦИИ] {СТИКЕР}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `СТИКЕР` | да | — | Стикер: ID или название |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--name`, `-n` | `НАЗВАНИЕ` | — | — | Новое название |
| `--icon`, `-i` | `ИКОНКА` | — | — | Иконка стикера; пустая строка — без иконки. Полный список: yougile sticker string icons |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Отфильтровать JSON выражением jq |

Пример:

```bash
yougile sticker string edit Приоритет --name Важность --icon star
```

### `yougile sticker string delete`

Удалить строковый стикер.

```
yougile sticker string delete [ОПЦИИ] {СТИКЕР}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `СТИКЕР` | да | — | Стикер: ID или название |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--yes`, `-y` | — | — | — | Не спрашивать подтверждение |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Отфильтровать JSON выражением jq |

Пример:

```bash
yougile sticker string delete Важность --yes
```

### `yougile sticker string state list`

Список состояний строкового стикера.

```
yougile sticker string state list [ОПЦИИ] {СТИКЕР}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `СТИКЕР` | да | — | Стикер: ID или название |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--include-deleted` | — | — | — | Показывать удалённые объекты |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Отфильтровать JSON выражением jq |

Пример:

```bash
yougile sticker string state list Приоритет
```

### `yougile sticker string state add`

Добавить состояние строковому стикеру.

```
yougile sticker string state add [ОПЦИИ] {СТИКЕР} {НАЗВАНИЕ}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `СТИКЕР` | да | — | Стикер: ID или название |
| `НАЗВАНИЕ` | да | — | Название |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--color`, `-c` | `ЦВЕТ` | — | — | Цвет состояния, например red |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Отфильтровать JSON выражением jq |

Пример:

```bash
yougile sticker string state add Приоритет Средний --color yellow
```

### `yougile sticker string state edit`

Изменить состояние строкового стикера.

```
yougile sticker string state edit [ОПЦИИ] {СТИКЕР} {СОСТОЯНИЕ}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `СТИКЕР` | да | — | Стикер: ID или название |
| `СОСТОЯНИЕ` | да | — | Состояние: ID или название |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--name`, `-n` | `НАЗВАНИЕ` | — | — | Новое название |
| `--color`, `-c` | `ЦВЕТ` | — | — | Цвет состояния, например red |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Отфильтровать JSON выражением jq |

Пример:

```bash
yougile sticker string state edit Приоритет Средний --name Обычный --color blue
```

### `yougile sticker string state delete`

Удалить состояние строкового стикера.

```
yougile sticker string state delete [ОПЦИИ] {СТИКЕР} {СОСТОЯНИЕ}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `СТИКЕР` | да | — | Стикер: ID или название |
| `СОСТОЯНИЕ` | да | — | Состояние: ID или название |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--yes`, `-y` | — | — | — | Не спрашивать подтверждение |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Отфильтровать JSON выражением jq |

Пример:

```bash
yougile sticker string state delete Приоритет Обычный --yes
```

### `yougile sticker sprint list`

Список стикеров-спринтов.

```
yougile sticker sprint list [ОПЦИИ]
```

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--search`, `-S` | `ТЕКСТ` | — | — | Фильтр по имени стикера |
| `--board`, `-b` | `ДОСКА` | — | — | Доска (ID, ссылка или название) |
| `--include-deleted` | — | — | — | Показывать удалённые объекты |
| `--limit`, `-L` | `ЧИСЛО` | `30` | — | Сколько записей показать (0 — все) |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Отфильтровать JSON выражением jq |

Пример:

```bash
yougile sticker sprint list --board 'Спринт 12'
```

### `yougile sticker sprint view`

Показать стикер-спринт.

```
yougile sticker sprint view [ОПЦИИ] {СТИКЕР}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `СТИКЕР` | да | — | Стикер: ID или название |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Отфильтровать JSON выражением jq |

Пример:

```bash
yougile sticker sprint view Спринты
```

### `yougile sticker sprint create`

Создать стикер-спринт.

```
yougile sticker sprint create [ОПЦИИ] [НАЗВАНИЕ]
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `НАЗВАНИЕ` | нет | — | Название нового стикера |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--name`, `-n` | `НАЗВАНИЕ` | — | — | То же название, но флагом |
| `--state`, `-s` | `СОСТОЯНИЕ` | — | — | Состояние «Название[:начало[:конец]]» (или через «;», если во времени есть двоеточие); можно повторять |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Отфильтровать JSON выражением jq |

Пример:

```bash
yougile sticker sprint create Спринты --state 'Спринт 12:2026-09-01:2026-09-14'
```

### `yougile sticker sprint edit`

Изменить стикер-спринт.

```
yougile sticker sprint edit [ОПЦИИ] {СТИКЕР}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `СТИКЕР` | да | — | Стикер: ID или название |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--name`, `-n` | `НАЗВАНИЕ` | — | да | Новое название |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Отфильтровать JSON выражением jq |

Пример:

```bash
yougile sticker sprint edit Спринты --name 'Спринты 2026'
```

### `yougile sticker sprint delete`

Удалить стикер-спринт.

```
yougile sticker sprint delete [ОПЦИИ] {СТИКЕР}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `СТИКЕР` | да | — | Стикер: ID или название |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--yes`, `-y` | — | — | — | Не спрашивать подтверждение |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Отфильтровать JSON выражением jq |

Пример:

```bash
yougile sticker sprint delete 'Спринты 2026' --yes
```

### `yougile sticker sprint state list`

Список состояний стикера-спринта.

```
yougile sticker sprint state list [ОПЦИИ] {СТИКЕР}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `СТИКЕР` | да | — | Стикер: ID или название |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--include-deleted` | — | — | — | Показывать удалённые объекты |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Отфильтровать JSON выражением jq |

Пример:

```bash
yougile sticker sprint state list Спринты
```

### `yougile sticker sprint state add`

Добавить состояние стикеру-спринту.

```
yougile sticker sprint state add [ОПЦИИ] {СТИКЕР} {НАЗВАНИЕ}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `СТИКЕР` | да | — | Стикер: ID или название |
| `НАЗВАНИЕ` | да | — | Название |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--begin` | `ДАТА` | — | — | Начало спринта: дата или миллисекунды |
| `--end` | `ДАТА` | — | — | Конец спринта: дата или миллисекунды |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Отфильтровать JSON выражением jq |

Пример:

```bash
yougile sticker sprint state add Спринты 'Спринт 13' --begin 2026-09-15 --end 2026-09-28
```

### `yougile sticker sprint state edit`

Изменить состояние стикера-спринта.

```
yougile sticker sprint state edit [ОПЦИИ] {СТИКЕР} {СОСТОЯНИЕ}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `СТИКЕР` | да | — | Стикер: ID или название |
| `СОСТОЯНИЕ` | да | — | Состояние: ID или название |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--name`, `-n` | `НАЗВАНИЕ` | — | — | Новое название |
| `--begin` | `ДАТА` | — | — | Начало спринта: дата или миллисекунды |
| `--end` | `ДАТА` | — | — | Конец спринта: дата или миллисекунды |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Отфильтровать JSON выражением jq |

Пример:

```bash
yougile sticker sprint state edit Спринты 'Спринт 13' --end 2026-09-30
```

### `yougile sticker sprint state delete`

Удалить состояние стикера-спринта.

```
yougile sticker sprint state delete [ОПЦИИ] {СТИКЕР} {СОСТОЯНИЕ}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `СТИКЕР` | да | — | Стикер: ID или название |
| `СОСТОЯНИЕ` | да | — | Состояние: ID или название |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--yes`, `-y` | — | — | — | Не спрашивать подтверждение |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Отфильтровать JSON выражением jq |

Пример:

```bash
yougile sticker sprint state delete Спринты 'Спринт 13' --yes
```

## chat: чаты и сообщения

Групповые чаты и сообщения. Везде, где ждут чат, принимается и задача — чат задачи это обычный чат.

### `yougile chat list`

Список групповых чатов.

```
yougile chat list [ОПЦИИ]
```

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--search`, `-S` | `ТЕКСТ` | — | — | Искать по имени чата |
| `--limit`, `-L` | `ЧИСЛО` | `30` | — | Сколько элементов показать; 0 — все |
| `--include-deleted` | — | — | — | Показывать удалённые |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с этими полями (через запятую) |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON |

Пример:

```bash
yougile chat list --search Дежурные
```

### `yougile chat view`

Показать чат.

```
yougile chat view [ОПЦИИ] {ЧАТ}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ЧАТ` | да | — | Чат: ID, имя или ссылка |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с этими полями (через запятую) |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON |

Пример:

```bash
yougile chat view Дежурные
```

### `yougile chat create`

Создать групповой чат.

```
yougile chat create [ОПЦИИ] [НАЗВАНИЕ]
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `НАЗВАНИЕ` | нет | — | Имя нового чата |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--title`, `-t` | `НАЗВАНИЕ` | — | — | Имя нового чата (то же, что аргумент) |
| `--user`, `-u` | `СОТРУДНИК` | — | — | Участник в формате «сотрудник[=роль]» (ID, e-mail или имя; роль — user). Можно повторять. |
| `--notify` / `--no-notify` | — | `--notify` | — | Включить участникам уведомления чата |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с этими полями (через запятую) |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON |

Пример:

```bash
yougile chat create Дежурные --user ivan@example.com --user petr@example.com
```

### `yougile chat edit`

Изменить чат.

```
yougile chat edit [ОПЦИИ] {ЧАТ}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ЧАТ` | да | — | Чат: ID, имя или ссылка |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--title`, `-t` | `НАЗВАНИЕ` | — | — | Новое имя чата |
| `--user`, `-u` | `СОТРУДНИК` | — | — | Участник в формате «сотрудник[=роль]» (ID, e-mail или имя; роль — user). Можно повторять. |
| `--notify` / `--no-notify` | — | `--notify` | — | Включить участникам уведомления чата |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с этими полями (через запятую) |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON |

Пример:

```bash
yougile chat edit Дежурные --title 'Дежурные 24/7' --no-notify
```

### `yougile chat delete`

Удалить чат.

```
yougile chat delete [ОПЦИИ] {ЧАТ}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ЧАТ` | да | — | Чат: ID, имя или ссылка |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--yes`, `-y` | — | — | — | Не спрашивать подтверждение |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с этими полями (через запятую) |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON |

Пример:

```bash
yougile chat delete 'Дежурные 24/7' --yes
```

### `yougile chat send`

Отправить сообщение в чат или в задачу.

```
yougile chat send [ОПЦИИ] {ЧАТ} [ТЕКСТ]
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ЧАТ` | да | — | Чат или задача: ID, код задачи, имя или ссылка |
| `ТЕКСТ` | нет | — | Текст сообщения |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--body-file`, `-F` | `ФАЙЛ` | — | — | Прочитать текст из файла («-» — stdin) |
| `--editor`, `-e` | — | — | — | Написать текст в $EDITOR |
| `--html` | `ТЕКСТ` | — | — | HTML-версия сообщения (по умолчанию — текст в &lt;p&gt;…&lt;/p&gt;) |
| `--label`, `-l` | `ТЕКСТ` | — | — | Быстрая ссылка сообщения |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с этими полями (через запятую) |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON |

Пример:

```bash
yougile chat send ILS-343 'Выкатил на прод'
```

### `yougile chat messages`

История сообщений чата или задачи.

```
yougile chat messages [ОПЦИИ] {ЧАТ}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ЧАТ` | да | — | Чат или задача: ID, код задачи, имя или ссылка |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--from-user` | `СОТРУДНИК` | — | — | Только сообщения этого сотрудника (ID, e-mail, имя или @me) |
| `--search`, `-S` | `ТЕКСТ` | — | — | Искать сообщения с этой подстрокой |
| `--label`, `-l` | `ТЕКСТ` | — | — | Быстрая ссылка сообщения |
| `--since` | `ДАТА` | — | — | Сообщения новее даты (ISO или timestamp) |
| `--include-system` | — | — | — | Включать системные сообщения |
| `--include-deleted` | — | — | — | Показывать удалённые |
| `--limit`, `-L` | `ЧИСЛО` | `30` | — | Сколько элементов показать; 0 — все |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с этими полями (через запятую) |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON |

Пример:

```bash
yougile chat messages ILS-343 --limit 0 --include-system
```

### `yougile chat typing`

Показать в чате, что вы печатаете.

```
yougile chat typing [ОПЦИИ] {ЧАТ}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ЧАТ` | да | — | Чат или задача: ID, код задачи, имя или ссылка |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с этими полями (через запятую) |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON |

Пример:

```bash
yougile chat typing Дежурные
```

### `yougile chat message view`

Показать сообщение.

```
yougile chat message view [ОПЦИИ] {ЧАТ} {ID}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ЧАТ` | да | — | Чат или задача: ID, код задачи, имя или ссылка |
| `ID` | да | — | ID сообщения (число) |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с этими полями (через запятую) |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON |

Пример:

```bash
yougile chat message view ILS-343 42
```

### `yougile chat message edit`

Изменить быструю ссылку или поставить реакцию.

```
yougile chat message edit [ОПЦИИ] {ЧАТ} {ID}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ЧАТ` | да | — | Чат или задача: ID, код задачи, имя или ссылка |
| `ID` | да | — | ID сообщения (число) |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--label`, `-l` | `ТЕКСТ` | — | — | Новая быстрая ссылка |
| `--react`, `-r` | `РЕАКЦИЯ` | — | — | Реакция, одна из: 👍 👎 👏 🙂 😀 😕 🎉 ❤ 🚀 ✔ |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с этими полями (через запятую) |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON |

Пример:

```bash
yougile chat message edit ILS-343 42 --react 👍
```

### `yougile chat message delete`

Удалить сообщение.

```
yougile chat message delete [ОПЦИИ] {ЧАТ} {ID}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ЧАТ` | да | — | Чат или задача: ID, код задачи, имя или ссылка |
| `ID` | да | — | ID сообщения (число) |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--yes`, `-y` | — | — | — | Не спрашивать подтверждение |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с этими полями (через запятую) |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON |

Пример:

```bash
yougile chat message delete ILS-343 42 --yes
```

## webhook: подписки на события

Вебхуки: подписки на события компании.

### `yougile webhook list`

Список вебхуков.

```
yougile webhook list [ОПЦИИ]
```

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--include-deleted` | — | — | — | Показывать в том числе удалённые вебхуки |
| `--limit`, `-L` | `ЧИСЛО` | `30` | — | Сколько записей вернуть; 0 — все |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON-вывода |
| `--full-ids` | — | — | — | Показывать идентификаторы целиком |

Пример:

```bash
yougile webhook list --include-deleted
```

### `yougile webhook view`

Показать вебхук.

```
yougile webhook view [ОПЦИИ] {ВЕБХУК}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ВЕБХУК` | да | — | Вебхук: ID или его URL |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON-вывода |
| `--full-ids` | — | — | — | Показывать идентификаторы целиком |

Пример:

```bash
yougile webhook view https://example.com/hooks/yougile
```

### `yougile webhook create`

Создать вебхук.

```
yougile webhook create [ОПЦИИ] [URL]
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `URL` | нет | — | URL, на который слать события |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--url`, `-u` | `URL` | — | — | Тот же URL, но флагом |
| `--event`, `-e` | `СОБЫТИЕ` | — | да | Событие, например task-created или .* (см. `yougile webhook events`) |
| `--filter`, `-f` | `ФИЛЬТР` | — | — | Фильтр вида имя=значение: location=&lt;проект/доска/колонка&gt;, title=&lt;regexp&gt;, chat_message=&lt;regexp&gt;. Можно повторять |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON-вывода |

Пример:

```bash
yougile webhook create https://example.com/hooks/yougile --event 'task-.*' --filter 'location=Разработка'
```

### `yougile webhook edit`

Изменить вебхук.

```
yougile webhook edit [ОПЦИИ] {ВЕБХУК}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ВЕБХУК` | да | — | Вебхук: ID или его URL |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--url`, `-u` | `URL` | — | — | Новый URL вебхука |
| `--event`, `-e` | `СОБЫТИЕ` | — | — | Новое событие вебхука |
| `--enable` / `--disable` | — | не задан | — | Включить или выключить вебхук |
| `--filter`, `-f` | `ФИЛЬТР` | — | — | Фильтр вида имя=значение: location=&lt;проект/доска/колонка&gt;, title=&lt;regexp&gt;, chat_message=&lt;regexp&gt;. Можно повторять |
| `--undelete` | — | — | — | Восстановить удалённый вебхук |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON-вывода |

Пример:

```bash
yougile webhook edit https://example.com/hooks/yougile --disable
```

### `yougile webhook delete`

Удалить вебхук.

```
yougile webhook delete [ОПЦИИ] {ВЕБХУК}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ВЕБХУК` | да | — | Вебхук: ID или его URL |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--yes`, `-y` | — | — | — | Не спрашивать подтверждение |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON-вывода |

Пример:

```bash
yougile webhook delete https://example.com/hooks/yougile --yes
```

### `yougile webhook events`

Известные события, на которые можно подписаться.

```
yougile webhook events [ОПЦИИ]
```

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с перечисленными через запятую полями |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON-вывода |

Пример:

```bash
yougile webhook events
```

## company: компания

Текущая компания.

### `yougile company view`

Показать детали текущей компании.

```
yougile company view [ОПЦИИ]
```

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--company-id`, `-c` | `ID` | — | — | ID компании; по умолчанию — компания текущего ключа |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с этими полями (через запятую) |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON |

Пример:

```bash
yougile company view
```

### `yougile company edit`

Изменить название или произвольные данные компании.

```
yougile company edit [ОПЦИИ]
```

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--title`, `-t` | `НАЗВАНИЕ` | — | — | Новое название компании |
| `--api-data`, `-a` | `КЛЮЧ=ЗНАЧЕНИЕ` | — | — | Произвольные данные (можно повторять) |
| `--deleted` / `--restore` | — | не задан | — | Пометить компанию удалённой или снять пометку |
| `--company-id`, `-c` | `ID` | — | — | ID компании; по умолчанию — компания текущего ключа |
| `--yes`, `-y` | — | — | — | Не спрашивать подтверждение |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с этими полями (через запятую) |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON |

Пример:

```bash
yougile company edit --title 'Моя компания' --api-data crm=1 --yes
```

## file: файлы

Загрузка и скачивание файлов YouGile.

### `yougile file upload`

Загрузить файл и получить его ссылку.

```
yougile file upload [ОПЦИИ] {ФАЙЛ}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `ФАЙЛ` | да | — | Путь к файлу, который нужно загрузить |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с этими полями (через запятую) |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON |

Пример:

```bash
yougile file upload ./схема.png
```

### `yougile file download`

Скачать файл по ссылке YouGile.

```
yougile file download [ОПЦИИ] {URL}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `URL` | да | — | Ссылка на файл или путь вида /user-data/&lt;id&gt;/&lt;имя&gt; |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--output`, `-o` | `ФАЙЛ\|КАТАЛОГ` | — | — | Куда сохранить: имя файла или существующий каталог |
| `--preview` | — | — | — | Скачать превью 480×480, а не оригинал |
| `--force`, `-f` | — | — | — | Перезаписать существующий файл |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с этими полями (через запятую) |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON |

Пример:

```bash
yougile file download 'https://ru.yougile.com/user-data/9f0c.../IMG_20260828_173932.jpg' -o ~/Downloads
```

## crm: CRM

Контактные лица CRM.

### `yougile crm contact create`

Создать контактное лицо CRM.

```
yougile crm contact create [ОПЦИИ] [НАЗВАНИЕ]
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `НАЗВАНИЕ` | нет | — | Имя контактного лица (можно передать и флагом --title) |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--title`, `-t` | `НАЗВАНИЕ` | — | — | То же имя, но флагом |
| `--project`, `-p` | `ПРОЕКТ` | — | да | Проект: ID, имя или ссылка |
| `--position` | `ДОЛЖНОСТЬ` | — | — | Должность |
| `--phone` | `ТЕЛЕФОН` | — | — | Телефон |
| `--additional-phone` | `ТЕЛЕФОН` | — | — | Дополнительный телефон |
| `--email`, `-e` | `ПОЧТА` | — | — | Электронная почта |
| `--address` | `АДРЕС` | — | — | Адрес |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с этими полями (через запятую) |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON |

Пример:

```bash
yougile crm contact create --title 'Пётр Петров' --project Продажи --email petr@example.com
```

### `yougile crm contact view`

Найти контакт CRM по ID чата во внешнем мессенджере.

```
yougile crm contact view [ОПЦИИ]
```

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--external-id`, `-i` | `ПРОВАЙДЕР:ЧАТ` | — | — | Внешний идентификатор целиком, например telegram:12345 |
| `--provider` | `ПРОВАЙДЕР` | — | — | Провайдер внешней интеграции, например telegram |
| `--chat-id` | `ЧАТ` | — | — | ID чата во внешнем мессенджере |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с этими полями (через запятую) |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON |

Пример:

```bash
yougile crm contact view --external-id telegram:12345
```

## config: настройки

Локальные настройки и кэш.

### `yougile config get`

Показать значение настройки.

```
yougile config get [ОПЦИИ] {КЛЮЧ}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `КЛЮЧ` | да | — | Имя настройки, например output или aliases.mine |

Пример:

```bash
yougile config get output
```

### `yougile config set`

Задать значение настройки.

```
yougile config set [ОПЦИИ] {КЛЮЧ} {ЗНАЧЕНИЕ}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `КЛЮЧ` | да | — | Имя настройки, например output или aliases.mine |
| `ЗНАЧЕНИЕ` | да | — | Новое значение |

Пример:

```bash
yougile config set output json
```

### `yougile config list`

Показать все настройки.

```
yougile config list [ОПЦИИ]
```

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с этими полями (через запятую) |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON |

Пример:

```bash
yougile config list
```

### `yougile config clear-cache`

Очистить локальный кэш каталога конфигурации.

```
yougile config clear-cache [ОПЦИИ]
```

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с этими полями (через запятую) |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON |

Пример:

```bash
yougile config clear-cache
```

## alias: алиасы

Пользовательские алиасы команд.

### `yougile alias list`

Показать сохранённые алиасы.

```
yougile alias list [ОПЦИИ]
```

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--json` | `ПОЛЯ` | — | — | Вывести JSON только с этими полями (через запятую) |
| `--jq`, `-q` | `ВЫРАЖЕНИЕ` | — | — | Фильтр jq для JSON |

Пример:

```bash
yougile alias list
```

### `yougile alias set`

Задать алиас: yougile alias set mine 'task list --assignee @me'.

```
yougile alias set [ОПЦИИ] {НАЗВАНИЕ} {КОМАНДА}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `НАЗВАНИЕ` | да | — | Имя алиаса |
| `КОМАНДА` | да | — | Команда, в которую он разворачивается |

Пример:

```bash
yougile alias set mine 'task list --assignee @me --state open'
```

### `yougile alias delete`

Удалить алиас.

```
yougile alias delete [ОПЦИИ] {НАЗВАНИЕ}
```

| Аргумент | Обязателен | По умолчанию | Описание |
| --- | --- | --- | --- |
| `НАЗВАНИЕ` | да | — | Имя алиаса |

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--yes`, `-y` | — | — | — | Не спрашивать подтверждение |

Пример:

```bash
yougile alias delete mine --yes
```

## completion: автодополнение

Автодополнение команд для оболочки. `yougile completion` работает и как группа, и как самостоятельная команда: без подкоманды она печатает скрипт в stdout.

### `yougile completion`

Автодополнение команд для оболочки

```
yougile completion [ОПЦИИ] КОМАНДА [АРГУМЕНТЫ]...
```

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--shell`, `-s` | `ОБОЛОЧКА` | — | — | Оболочка: bash, zsh, fish, powershell или pwsh |

Пример:

```bash
yougile completion -s zsh
```

### `yougile completion install`

Установить автодополнение в файл настроек оболочки.

```
yougile completion install [ОПЦИИ]
```

| Флаг | Значение | По умолчанию | Обяз. | Описание |
| --- | --- | --- | --- | --- |
| `--shell`, `-s` | `ОБОЛОЧКА` | — | — | Оболочка: bash, zsh, fish, powershell или pwsh |

Пример:

```bash
yougile completion install -s zsh
```
