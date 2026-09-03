"""Root Typer application: global flags, command mounting and the `yougile` entry point.

The root callback carries only the flags that are genuinely global (host,
credentials, output format, colour, verbosity, timeout, version). Everything
else lives on the individual commands, exactly as in `gh`.

The HTTP client stays lazy: `auth`, `config`, `alias`, `version`, `completion`
and any `--help` must keep working with no API key configured.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.markup import escape
from typer.core import TyperGroup

from . import __version__
from .client import YouGileClient
from .commands import (
    alias_app,
    api_cmd,
    auth_app,
    board_app,
    browse_cmd,
    chat_app,
    column_app,
    company_app,
    config_app,
    crm_app,
    department_app,
    expand_alias,
    file_app,
    project_app,
    status_cmd,
    sticker_app,
    task_app,
    user_app,
    version_cmd,
    webhook_app,
)
from .config import Settings, list_aliases, load_settings, resolve_auth, settings_path
from .context import AppContext
from .errors import (
    EXIT_ERROR,
    EXIT_INTERRUPT,
    LOGIN_HINT,
    AuthError,
    CancelledError,
    ValidationError,
    YouGileError,
    exit_code_for,
)
from .i18n import install_russian_ui
from .output import OutputFormat, OutputOptions, get_console, set_color_override

__all__ = ["app", "main"]

PROG_NAME = "yougile"
COMPLETE_VAR = "_YOUGILE_COMPLETE"
ENTRY_POINTS = ("yougile", "yg")
DEFAULT_TIMEOUT = 30.0
SHELLS = ("bash", "zsh", "fish", "powershell", "pwsh")
CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

install_russian_ui()

try:  # typer registers its shell classes only via the completion flags we disabled
    from typer._completion_classes import completion_init as _completion_init

    _completion_init()
except Exception:  # pragma: no cover - a typer upgrade must not break the CLI
    pass

HELP = """Консольный клиент YouGile в стиле GitHub CLI.

Форма команды: [bold]yougile <сущность> <действие> [ЦЕЛЬ] [ФЛАГИ][/bold],
например [bold]yougile task list --assignee @me[/bold].

Начните с [bold]yougile auth login[/bold]; справка по группе — [bold]yougile task --help[/bold].
"""


def _report(exc: YouGileError) -> None:
    """gh-style stderr report: `ошибка: …` and, on the next line, the hint."""
    console = get_console(stderr=True)
    console.print(f"[bold red]ошибка:[/bold red] {escape(str(exc))}", highlight=False)
    if exc.hint:
        console.print(f"[dim]подсказка:[/dim] {escape(exc.hint)}", highlight=False)


def _report_cancel(exc: CancelledError) -> None:
    """Cancelling is not an error, but its reason must still reach the user."""
    console = get_console(stderr=True)
    console.print(escape(str(exc)), highlight=False)
    if exc.hint:
        console.print(f"[dim]подсказка:[/dim] {escape(exc.hint)}", highlight=False)


class _RootGroup(TyperGroup):
    """Turns our exceptions into gh-compatible exit codes wherever the app is driven from."""

    def invoke(self, ctx: Any) -> Any:
        try:
            return super().invoke(ctx)
        except CancelledError as exc:
            _report_cancel(exc)
            ctx.exit(EXIT_ERROR)
        except YouGileError as exc:
            _report(exc)
            ctx.exit(exit_code_for(exc))


app = typer.Typer(
    name=PROG_NAME,
    cls=_RootGroup,
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=False,  # `yougile completion` replaces typer's own two flags
    help=HELP,
    context_settings=CONTEXT_SETTINGS,
)


@dataclass
class _RunContext(AppContext):
    """AppContext that remembers the `--timeout` this invocation was given."""

    timeout: float = DEFAULT_TIMEOUT

    def client(self) -> YouGileClient:
        if self._client is None:
            if not self.auth.api_key:
                raise AuthError(f"Вход на {self.auth.host} не выполнен.", hint=LOGIN_HINT)
            self._client = YouGileClient(
                api_key=self.auth.api_key,
                base_url=self.auth.base_url,
                host=self.auth.host,
                timeout=self.timeout,
            )
        return self._client


def _settings_format(settings: Settings, *, quiet: bool = False) -> OutputFormat:
    """`output:` from config.yml — the flag beats it, the default backs it.

    A bad value must not brick the CLI: raising here would also kill
    `yougile config set output …`, the one command able to repair the file.
    """
    raw = (settings.output or "").strip().lower()
    if not raw:
        return OutputFormat.TABLE
    try:
        return OutputFormat(raw)
    except ValueError:
        if not quiet:
            allowed = ", ".join(item.value for item in OutputFormat)
            console = get_console(stderr=True)
            console.print(
                f"[yellow]предупреждение:[/yellow] недопустимый формат вывода "
                f"«{escape(str(settings.output))}» в {escape(str(settings_path()))}; "
                "используется table.",
                highlight=False,
            )
            console.print(
                f"[dim]подсказка:[/dim] допустимы: {allowed}. "
                "Исправьте файл или выполните: yougile config set output table",
                highlight=False,
            )
        return OutputFormat.TABLE


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"{PROG_NAME} version {__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    ctx: typer.Context,
    hostname: Annotated[
        str | None,
        typer.Option("--hostname", metavar="ХОСТ", help="Хост YouGile (по умолчанию yougile.com)"),
    ] = None,
    api_key: Annotated[
        str | None,
        typer.Option(
            "--api-key",
            metavar="КЛЮЧ",
            help=(
                "API-ключ; важнее переменных окружения и hosts.yml. "
                "Небезопасно: ключ виден в списке процессов — лучше YOUGILE_TOKEN "
                "или yougile auth login --with-token"
            ),
        ),
    ] = None,
    output: Annotated[
        OutputFormat | None,
        typer.Option("--output", "-o", help="Формат вывода: table, json, yaml, csv, tsv, ids"),
    ] = None,
    full_ids: Annotated[
        bool, typer.Option("--full-ids", help="Показывать идентификаторы целиком")
    ] = False,
    no_color: Annotated[
        bool, typer.Option("--no-color", help="Отключить цвет и оформление вывода")
    ] = False,
    quiet: Annotated[
        bool, typer.Option("--quiet", help="Не печатать таблицы и служебные сообщения")
    ] = False,
    timeout: Annotated[
        float, typer.Option("--timeout", metavar="СЕК", help="Таймаут HTTP-запроса в секундах")
    ] = DEFAULT_TIMEOUT,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            help="Показать версию и выйти",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
    if no_color:
        # Downstream consoles built by output.get_console() must agree with the flag,
        # including CLICOLOR_FORCE-forced ones and the error reporter.
        os.environ["NO_COLOR"] = "1"
    set_color_override(False if no_color else None)

    settings = load_settings()
    color = False if no_color else None
    run = _RunContext(
        auth=resolve_auth(hostname, token=api_key, require_key=False),
        out=OutputOptions(
            fmt=output if output is not None else _settings_format(settings, quiet=quiet),
            full_ids=full_ids,
        ),
        settings=settings,
        console=get_console(color=color),
        err_console=get_console(stderr=True, color=color),
        prompt_enabled=(settings.prompt or "").strip().lower() != "disabled",
        quiet=quiet,
        timeout=timeout,
    )
    ctx.obj = run
    ctx.call_on_close(run.close)


# --------------------------------------------------------------------------- nouns

app.add_typer(auth_app, name="auth", help="Вход, учётные записи и API-ключи")
app.add_typer(project_app, name="project", help="Проекты и роли проекта")
app.add_typer(board_app, name="board", help="Доски: список, дерево, создание, изменение")
app.add_typer(column_app, name="column", help="Колонки досок")
app.add_typer(task_app, name="task", help="Задачи: поиск, создание, изменение, перемещение")
app.add_typer(user_app, name="user", help="Сотрудники компании")
app.add_typer(department_app, name="department", help="Отделы компании")
app.add_typer(sticker_app, name="sticker", help="Стикеры: строковые и спринты")
app.add_typer(chat_app, name="chat", help="Групповые чаты и сообщения")
app.add_typer(webhook_app, name="webhook", help="Подписки на события (вебхуки)")
app.add_typer(company_app, name="company", help="Текущая компания")
app.add_typer(file_app, name="file", help="Загрузка файлов")
app.add_typer(crm_app, name="crm", help="CRM: контактные лица")
app.add_typer(config_app, name="config", help="Локальные настройки")
app.add_typer(alias_app, name="alias", help="Алиасы команд")

# --------------------------------------------------------------------------- verbs

app.command("api", help="Произвольный запрос к API YouGile")(api_cmd)
app.command("browse", help="Открыть задачу, доску или проект в браузере")(browse_cmd)
app.command("status", help="Мои незакрытые задачи, сгруппированные по доскам")(status_cmd)
app.command("version", help="Показать версию CLI и окружения")(version_cmd)


# --------------------------------------------------------------------------- completion

completion_app = typer.Typer(
    invoke_without_command=True,
    help="Скрипт автодополнения для оболочки.",
)
app.add_typer(completion_app, name="completion", help="Автодополнение команд для оболочки")

_SHELL_HELP = "Оболочка: bash, zsh, fish, powershell или pwsh"


def _detect_shell() -> str:
    try:
        # Private helper: absent on older typer, so the import stays inside the guard.
        from typer.completion import _get_shell_name

        return (_get_shell_name() or "").strip()
    except Exception:
        return ""


def _prog_name() -> str:
    """The name the user actually typed, so `yg` gets completion for `yg`."""
    name = Path(sys.argv[0] or "").name.strip()
    if name.endswith(".exe"):
        name = name[: -len(".exe")]
    return name if name in ENTRY_POINTS else PROG_NAME


def _complete_var(prog: str) -> str:
    """Same shape click derives from the program name when it looks for the var."""
    return f"_{prog.replace('-', '_').upper()}_COMPLETE"


@completion_app.callback(invoke_without_command=True)
def completion_main(
    ctx: typer.Context,
    shell: Annotated[
        str | None, typer.Option("--shell", "-s", metavar="ОБОЛОЧКА", help=_SHELL_HELP)
    ] = None,
) -> None:
    """Напечатать скрипт автодополнения в stdout."""
    if ctx.invoked_subcommand is not None:
        return

    from typer.completion import get_completion_script

    name = (shell or _detect_shell()).strip().lower()
    if name not in SHELLS:
        raise ValidationError(
            f"Неизвестная оболочка «{name or '?'}».",
            hint=f"Укажите -s: {', '.join(SHELLS)}.",
        )
    prog = _prog_name()
    typer.echo(get_completion_script(prog_name=prog, complete_var=_complete_var(prog), shell=name))


@completion_app.command("install", help="Установить автодополнение в файл настроек оболочки.")
def completion_install(
    shell: Annotated[
        str | None, typer.Option("--shell", "-s", metavar="ОБОЛОЧКА", help=_SHELL_HELP)
    ] = None,
) -> None:
    from typer.completion import install

    name = (shell or _detect_shell()).strip().lower()
    if name not in SHELLS:
        raise ValidationError(
            f"Неизвестная оболочка «{name or '?'}».",
            hint=f"Укажите -s: {', '.join(SHELLS)}.",
        )
    installed_shell, path = install(shell=name, prog_name=_prog_name())
    typer.echo(f"Автодополнение для {installed_shell} установлено: {path}")
    typer.echo("Перезапустите терминал, чтобы оно заработало.")


# --------------------------------------------------------------------------- help flags


def _offer_short_help(typer_app: typer.Typer) -> None:
    """gh answers to `-h` at every level; typer only wires it where it is asked for."""
    if typer_app.info.context_settings is None:
        typer_app.info.context_settings = CONTEXT_SETTINGS
    for command in typer_app.registered_commands:
        if command.context_settings is None:
            command.context_settings = CONTEXT_SETTINGS
    for group in typer_app.registered_groups:
        if group.context_settings is None:
            group.context_settings = CONTEXT_SETTINGS
        if group.typer_instance is not None:
            _offer_short_help(group.typer_instance)


_offer_short_help(app)


# --------------------------------------------------------------------------- aliases


def _builtin_names() -> set[str]:
    """Names click will dispatch on — an alias must never shadow one of them."""
    command = typer.main.get_command(app)
    commands = getattr(command, "commands", None)
    return set(commands) if isinstance(commands, dict) else set()


def _expand_aliases(argv: list[str]) -> list[str]:
    if not argv or argv[0].startswith("-") or argv[0] in _builtin_names():
        return list(argv)
    aliases = list_aliases()
    if argv[0] not in aliases:
        return list(argv)
    return expand_alias(list(argv), aliases)


def normalize_json_flag(argv: list[str]) -> list[str]:
    """`--json` with no value must list the fields (gh); typer cannot express that."""
    result: list[str] = []
    for index, token in enumerate(argv):
        result.append(token)
        if token != "--json":
            continue
        following = argv[index + 1] if index + 1 < len(argv) else None
        if following is None or following.startswith("-"):
            result.append("")
    return result


# --------------------------------------------------------------------------- flag hoisting

# `--help`/`--version` are eager and root-only on purpose: moving them would change
# which screen the user gets.
_NEVER_HOISTED = frozenset({"-h", "--help", "-V", "--version"})


def _option_specs(command: Any) -> dict[str, bool]:
    """Option string -> whether that option swallows the token after it."""
    specs: dict[str, bool] = {}
    for param in getattr(command, "params", ()):
        takes_value = not getattr(param, "is_flag", False) and not getattr(param, "count", False)
        for opt in (*getattr(param, "opts", ()), *getattr(param, "secondary_opts", ())):
            if isinstance(opt, str) and opt.startswith("-"):
                specs[opt] = takes_value
    return specs


def _split_option(token: str) -> tuple[str | None, bool]:
    """Split a token into its option string and whether a value is glued to it."""
    if not token.startswith("-") or token in {"-", "--"}:
        return None, False
    if token.startswith("--"):
        name, separator, _ = token.partition("=")
        return name, bool(separator)
    return token[:2], len(token) > 2


def _resolve_target(
    argv: list[str], root: Any, root_specs: dict[str, bool]
) -> tuple[Any, dict[str, bool]]:
    """Walk the real command tree over argv; return the addressed command and its options."""
    command = root
    specs = dict(root_specs)
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--":
            break
        name, inline = _split_option(token)
        if name is not None:
            index += 2 if specs.get(name, False) and not inline else 1
            continue
        children = getattr(command, "commands", None)
        if not isinstance(children, dict) or token not in children:
            break
        command = children[token]
        specs.update(_option_specs(command))
        index += 1
    return command, specs


def hoist_root_flags(argv: list[str]) -> list[str]:
    """Accept `yougile task list -o json`: root flags may trail the subcommand, as in gh.

    A flag is only moved when the command it was typed after does not declare that
    option itself — `project list -o`, `webhook list --full-ids` and `auth login
    --hostname` keep their own meaning.
    """
    try:
        root = typer.main.get_command(app)
        root_specs = {
            name: takes_value
            for name, takes_value in _option_specs(root).items()
            if name not in _NEVER_HOISTED
        }
        target, specs = _resolve_target(argv, root, root_specs)
        own = _option_specs(target)
    except Exception:
        return list(argv)

    head: list[str] = []
    tail: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--":
            tail.extend(argv[index:])
            break
        name, inline = _split_option(token)
        takes_value = specs.get(name, False) if name is not None else False
        if name is not None and name in root_specs and name not in own:
            head.append(token)
            index += 1
            if takes_value and not inline and index < len(argv):
                head.append(argv[index])
                index += 1
            continue
        tail.append(token)
        index += 1
        # The value of a foreign option must never be mistaken for a flag of its own.
        if takes_value and not inline and index < len(argv):
            tail.append(argv[index])
            index += 1
    return head + tail


def expand_argv(argv: list[str]) -> list[str]:
    """Rewrite `argv` through aliases, then lift trailing root flags, gh-style."""
    # `--json` must get its empty placeholder *before* hoisting, or a bare `--json`
    # swallows the root flag that follows it.
    return hoist_root_flags(normalize_json_flag(_expand_aliases(argv)))


# --------------------------------------------------------------------------- entry point


def main() -> None:
    """Entry point of the `yougile` and `yg` scripts."""
    if "--no-color" in sys.argv[1:]:
        # Failures raised before the root callback runs must honour the flag too.
        os.environ["NO_COLOR"] = "1"
        set_color_override(False)
    try:
        sys.argv[1:] = expand_argv(sys.argv[1:])
        app(prog_name=_prog_name())
    except CancelledError as exc:
        _report_cancel(exc)
        raise SystemExit(EXIT_ERROR) from None
    except YouGileError as exc:
        _report(exc)
        raise SystemExit(exit_code_for(exc)) from None
    except KeyboardInterrupt:
        raise SystemExit(EXIT_INTERRUPT) from None


if __name__ == "__main__":
    main()
