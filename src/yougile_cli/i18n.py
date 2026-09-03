"""Russian localisation of the framework chrome typer and its vendored click emit.

Typer 0.27 vendors click as ``typer._click`` and, apart from ``typer.core`` and
``typer.rich_utils``, spells its user-facing strings as plain literals instead of
routing them through ``gettext``. So this module does two things: it rebinds the
``_`` / ``ngettext`` hooks wherever a module still exposes them, and it wraps the
handful of call sites that build English text directly.

Every patch is best-effort: a typer upgrade that renames an internal must degrade
to the English default, never crash the CLI, so nothing here raises.
"""

from __future__ import annotations

import functools
import importlib
import re
import sys
from collections.abc import Callable
from types import ModuleType
from typing import Any

__all__ = ["install_russian_ui"]

# Exact msgid -> Russian. Both the literals typer 0.27 uses and the classic click
# gettext msgids are listed, so the table keeps working across either style.
MESSAGES: dict[str, str] = {
    # help option and panels
    "Show this message and exit.": "Показать эту справку и выйти.",
    "Arguments": "Аргументы",
    "Options": "Опции",
    "Commands": "Команды",
    "Error": "Ошибка",
    "Usage: ": "Использование: ",
    "Usage:": "Использование:",
    # option metadata
    "(deprecated) ": "(устарело) ",
    "(dynamic)": "(вычисляется)",
    "[default: {}]": "[по умолчанию: {}]",
    "[env var: {}]": "[перем. окружения: {}]",
    "[required]": "[обязательно]",
    "default: {default}": "по умолчанию: {default}",
    "env var: {var}": "перем. окружения: {var}",
    "required": "обязательно",
    # aborts
    "Aborted!": "Прервано!",
    "Aborted.": "Прервано.",
    # usage errors
    "Missing command.": "Не указана команда.",
    "No such command {name!r}.": "Нет такой команды {name!r}.",
    "Missing argument": "Отсутствует аргумент",
    "Missing option": "Отсутствует опция",
    "Missing parameter": "Отсутствует параметр",
    "Missing %(param_type)s": "Отсутствует %(param_type)s",
    "Invalid value: %(message)s": "Недопустимое значение: %(message)s",
    "Invalid value for %(param_hint)s: %(message)s": (
        "Недопустимое значение для %(param_hint)s: %(message)s"
    ),
    "No such option: %(name)s": "Нет такой опции: %(name)s",
    "(Possible options: %(possibilities)s)": "(Возможные опции: %(possibilities)s)",
    "Got unexpected extra argument (%(args)s)": "Получен лишний аргумент (%(args)s)",
    "Got unexpected extra arguments (%(args)s)": "Получены лишние аргументы (%(args)s)",
    "Try '%(command)s %(option)s' for help.": ("Попробуйте '%(command)s %(option)s' для справки."),
    "Try [blue]'{command_path} {help_option}'[/] for help.": (
        "Попробуйте [blue]'{command_path} {help_option}'[/] для справки."
    ),
    # prompts
    "Do you want to continue?": "Продолжить?",
    "Error: invalid input": "Ошибка: недопустимый ввод",
    "Error: The value you entered was invalid.": "Ошибка: введено недопустимое значение.",
    "Error: The two entered values do not match.": "Ошибка: введённые значения не совпадают.",
}

# Rich panel/notice constants typer evaluates at import time, so they have to be
# re-assigned rather than picked up from the rebound `_`.
RICH_CONSTANTS: dict[str, str] = {
    "ARGUMENTS_PANEL_TITLE": MESSAGES["Arguments"],
    "OPTIONS_PANEL_TITLE": MESSAGES["Options"],
    "COMMANDS_PANEL_TITLE": MESSAGES["Commands"],
    "ERRORS_PANEL_TITLE": MESSAGES["Error"],
    "ABORTED_TEXT": MESSAGES["Aborted."],
    "DEPRECATED_STRING": MESSAGES["(deprecated) "],
    "DEFAULT_STRING": MESSAGES["[default: {}]"],
    "ENVVAR_STRING": MESSAGES["[env var: {}]"],
    "REQUIRED_LONG_STRING": MESSAGES["[required]"],
    "RICH_HELP": MESSAGES["Try [blue]'{command_path} {help_option}'[/] for help."],
}

TYPE_NAMES: dict[str, str] = {
    "integer": "целое число",
    "integer range": "целое число из диапазона",
    "float": "число",
    "float range": "число из диапазона",
    "boolean": "логическое значение",
    "text": "строка",
    "uuid": "UUID",
    "datetime": "дата и время",
}


def _type_name(name: str) -> str:
    return TYPE_NAMES.get(name, name)


def _not_valid(match: re.Match[str]) -> str:
    return f"{match.group(1)} — недопустимое значение типа «{_type_name(match.group(2))}»."


# Applied to already-rendered messages, whose dynamic parts rule out an exact lookup.
PATTERNS: tuple[tuple[re.Pattern[str], Any], ...] = (
    (re.compile(r"^Usage: ", re.M), "Использование: "),
    (re.compile(r"^Error: ", re.M), "Ошибка: "),
    (re.compile(r"^Try '(.+)' for help\.$", re.M), r"Попробуйте '\1' для справки."),
    (re.compile(r"^Invalid value for (.+?): ", re.M), r"Недопустимое значение для \1: "),
    (re.compile(r"^Invalid value: ", re.M), "Недопустимое значение: "),
    (re.compile(r"^Missing argument", re.M), "Отсутствует аргумент"),
    (re.compile(r"^Missing option", re.M), "Отсутствует опция"),
    (re.compile(r"^Missing parameter", re.M), "Отсутствует параметр"),
    (re.compile(r"^Missing command\.$", re.M), "Не указана команда."),
    (re.compile(r"^No such option: ", re.M), "Нет такой опции: "),
    (re.compile(r"^No such command ", re.M), "Нет такой команды "),
    (re.compile(r"\(Possible options: "), "(Возможные опции: "),
    # typer glues this hint onto an already-translated "No such command" message.
    (re.compile(r"Did you mean one of these\?"), "Возможно, вы имели в виду одно из:"),
    (re.compile(r"Did you mean "), "Возможно, вы имели в виду "),
    (
        re.compile(r"^Got unexpected extra (?:argument\(s\)|arguments?) \(", re.M),
        "Получены лишние аргументы (",
    ),
    (
        re.compile(r"^Option '(.+?)' does not take a value\.$", re.M),
        r"Опция '\1' не принимает значение.",
    ),
    # Usage-line metavariables: click builds them as literals, outside gettext.
    (re.compile(r"\[OPTIONS\]"), "[ОПЦИИ]"),
    (re.compile(r"\[ARGS\]\.\.\."), "[АРГУМЕНТЫ]..."),
    (re.compile(r"\bCOMMAND\b"), "КОМАНДА"),
    (re.compile(r"^Choose from:", re.M), "Выберите из:"),
    (re.compile(r"^(.*?) is not a valid (.+?)\.$", re.M), _not_valid),
    (re.compile(r" is not one of "), " не входит в число "),
    (re.compile(r" is not in the range "), " вне диапазона "),
    (re.compile(r" does not match the formats "), " не соответствует форматам "),
    (
        re.compile(r"^(\d+) values are required, but (\d+) given\.$", re.M),
        r"требуется значений: \1, передано: \2.",
    ),
)


def translate(text: str) -> str:
    """gettext-compatible lookup: the Russian msgstr, or the msgid untouched."""
    return MESSAGES.get(text, text)


def translate_message(text: str) -> str:
    """Translate an already-rendered message, English fragments included."""
    exact = MESSAGES.get(text)
    if exact is not None:
        return exact
    for pattern, replacement in PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# --------------------------------------------------------------------------- gettext

# Modules that historically bind `_` / `ngettext` at module level. Only the ones
# that really do are patched; the rest are skipped silently.
_GETTEXT_MODULES = (
    "typer.core",
    "typer.rich_utils",
    "typer.main",
    "typer._click.core",
    "typer._click.exceptions",
    "typer._click.parser",
    "typer._click.types",
    "typer._click.termui",
    "typer._click.decorators",
    "typer._click.formatting",
    "typer._click.shell_completion",
)


def _import(name: str) -> ModuleType | None:
    try:
        return importlib.import_module(name)
    except Exception:
        return None


def _wrap_gettext(attr: str, original: Callable[..., Any]) -> Callable[..., Any]:
    if attr == "ngettext":

        def ngettext(*args: Any, **kwargs: Any) -> str:
            return translate(str(original(*args, **kwargs)))

        ngettext.__ru__ = True  # type: ignore[attr-defined]
        return ngettext

    def gettext(*args: Any, **kwargs: Any) -> str:
        return translate(str(original(*args, **kwargs)))

    gettext.__ru__ = True  # type: ignore[attr-defined]
    return gettext


def _install_gettext() -> None:
    for name in _GETTEXT_MODULES:
        module = _import(name)
        if module is None:
            continue
        namespace = vars(module)
        for attr in ("_", "gettext", "ngettext"):
            original = namespace.get(attr)
            if not callable(original) or getattr(original, "__ru__", False):
                continue
            try:
                setattr(module, attr, _wrap_gettext(attr, original))
            except Exception:
                continue


# --------------------------------------------------------------------------- rich chrome


def _install_rich_constants() -> None:
    module = _import("typer.rich_utils")
    if module is None:
        return
    for name, value in RICH_CONSTANTS.items():
        if hasattr(module, name):
            try:
                setattr(module, name, value)
            except Exception:
                continue
    _retune_usage_highlighter(module)


def _retune_usage_highlighter(module: ModuleType) -> None:
    """The `Usage: ` styling rule must follow the prefix into Russian."""
    highlighter: Any = getattr(module, "OptionHighlighter", None)
    highlights = getattr(highlighter, "highlights", None)
    if highlighter is None or not isinstance(highlights, list):
        return
    highlighter.highlights = [
        rule.replace("Usage: ", MESSAGES["Usage: "]) if isinstance(rule, str) else rule
        for rule in highlights
    ]


# --------------------------------------------------------------------------- click chrome


def _install_help_option() -> None:
    """`--help`'s own description is a literal inside the vendored decorator."""
    module = _import("typer._click.decorators")
    original = getattr(module, "help_option", None)
    if module is None or not callable(original) or getattr(original, "__ru__", False):
        return

    def help_option(*args: Any, **kwargs: Any) -> Any:
        decorator = original(*args, **kwargs)

        def wrapper(command: Any) -> Any:
            result = decorator(command)
            for param in getattr(result, "params", []):
                if getattr(param, "help", None) in MESSAGES:
                    param.help = MESSAGES[param.help]
            return result

        return wrapper

    help_option.__ru__ = True  # type: ignore[attr-defined]
    module.help_option = help_option  # type: ignore[attr-defined]


def _install_usage_prefix() -> None:
    module = _import("typer._click.formatting")
    formatter: Any = getattr(module, "HelpFormatter", None)
    original = getattr(formatter, "write_usage", None)
    if formatter is None or not callable(original) or getattr(original, "__ru__", False):
        return

    @functools.wraps(original)
    def write_usage(self: Any, prog: str, args: str = "", prefix: str | None = None) -> Any:
        # `args` carries click's literal [OPTIONS] / COMMAND / [ARGS]... metavariables.
        return original(
            self,
            prog,
            translate_message(args) if isinstance(args, str) else args,
            MESSAGES["Usage: "] if prefix is None else prefix,
        )

    write_usage.__ru__ = True  # type: ignore[attr-defined]
    formatter.write_usage = write_usage


def _wrap_message(func: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        result = func(*args, **kwargs)
        return translate_message(result) if isinstance(result, str) else result

    wrapper.__ru__ = True  # type: ignore[attr-defined]
    return wrapper


def _install_exception_messages() -> None:
    module = _import("typer._click.exceptions")
    if module is None:
        return
    for value in list(vars(module).values()):
        if not isinstance(value, type):
            continue
        for attr in ("format_message", "__str__"):
            func = value.__dict__.get(attr)
            if not callable(func) or getattr(func, "__ru__", False):
                continue
            try:
                setattr(value, attr, _wrap_message(func))
            except Exception:
                continue
    _install_exception_echo(module)


def _install_exception_echo(module: ModuleType) -> None:
    """`show()` glues `Usage:`/`Try …`/`Error:` together itself when rich is off."""
    original = getattr(module, "echo", None)
    if not callable(original) or getattr(original, "__ru__", False):
        return

    @functools.wraps(original)
    def echo(message: Any = None, *args: Any, **kwargs: Any) -> Any:
        if isinstance(message, str):
            message = translate_message(message)
        return original(message, *args, **kwargs)

    echo.__ru__ = True  # type: ignore[attr-defined]
    module.echo = echo  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- prompts

_YES = ("y", "yes", "д", "да")
_NO = ("n", "no", "н", "нет")


def _install_confirm() -> None:
    """Русские `[д/Н]`, всё ещё принимающие y/n — иначе ломается мышечная память."""
    termui = _import("typer._click.termui")
    exceptions = _import("typer.exceptions")
    build_prompt = getattr(termui, "_build_prompt", None)
    abort_cls = getattr(exceptions, "Abort", None)
    if termui is None or not callable(build_prompt) or not isinstance(abort_cls, type):
        return
    if getattr(getattr(termui, "confirm", None), "__ru__", False):
        return

    def confirm(
        text: str,
        default: bool | None = False,
        abort: bool = False,
        prompt_suffix: str = ": ",
        show_default: bool = True,
        err: bool = False,
    ) -> bool:
        choices = "д/н" if default is None else ("Д/н" if default else "д/Н")
        prompt = build_prompt(translate_message(text), prompt_suffix, show_default, choices)
        while True:
            try:
                termui.echo(prompt[:-1], nl=False, err=err)
                value = termui.visible_prompt_func(prompt[-1:]).lower().strip()
            except (KeyboardInterrupt, EOFError):
                raise abort_cls() from None
            if value in _YES:
                answer = True
            elif value in _NO:
                answer = False
            elif default is not None and value == "":
                answer = default
            else:
                termui.echo(MESSAGES["Error: invalid input"], err=err)
                continue
            break
        if abort and not answer:
            raise abort_cls()
        return answer

    confirm.__ru__ = True  # type: ignore[attr-defined]
    for name in ("typer._click.termui", "typer._click", "typer"):
        module = _import(name)
        if module is not None and hasattr(module, "confirm"):
            try:
                module.confirm = confirm  # type: ignore[attr-defined]
            except Exception:
                continue


# --------------------------------------------------------------------------- entry point


def _warn_missing_vendored_click() -> None:
    """`typer._click` appears in typer 0.26; without it the UI would be English."""
    if _import("typer._click") is not None:
        return
    typer_module = _import("typer")
    version = getattr(typer_module, "__version__", "?")
    sys.stderr.write(
        f"предупреждение: typer {version} без typer._click — часть текстов будет "
        "по-английски; требуется typer>=0.26,<0.28.\n"
    )


def install_russian_ui() -> None:
    """Translate typer/click chrome into Russian. Never raises."""
    for step in (
        _warn_missing_vendored_click,
        _install_gettext,
        _install_rich_constants,
        _install_help_option,
        _install_usage_prefix,
        _install_exception_messages,
        _install_confirm,
    ):
        try:
            step()
        except Exception:
            continue
