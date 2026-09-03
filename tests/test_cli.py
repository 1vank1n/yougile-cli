"""Root application: help, version, mounting, exit codes and alias expansion."""

from __future__ import annotations

import importlib
import re
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import typer

from yougile_cli import __version__

EXPECTED_GROUPS = {
    "alias",
    "auth",
    "board",
    "chat",
    "column",
    "company",
    "completion",
    "config",
    "crm",
    "department",
    "file",
    "project",
    "sticker",
    "task",
    "user",
    "webhook",
}
EXPECTED_LEAVES = {"api", "browse", "status", "version"}


def _cli() -> Any:
    return importlib.import_module("yougile_cli.cli")


def _root() -> Any:
    return typer.main.get_command(_cli().app)


def _walk(command: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[str, ...]]:
    """Every command path in the tree, root first."""
    yield path
    children = getattr(command, "commands", None)
    if isinstance(children, dict):
        for name, child in children.items():
            yield from _walk(child, (*path, name))


ALL_PATHS = sorted(_walk(_root()))


# --------------------------------------------------------------------------- mounting


def test_root_help_exits_zero(run: Callable[..., Any]) -> None:
    result = run(["--help"], token=None)
    assert result.exit_code == 0
    assert "yougile" in result.output


def test_expected_commands_are_mounted() -> None:
    names = set(_root().commands)
    assert names >= EXPECTED_GROUPS | EXPECTED_LEAVES


@pytest.mark.parametrize("path", [p for p in ALL_PATHS if p], ids=lambda p: " ".join(p))
def test_every_command_help_exits_zero(run: Callable[..., Any], path: tuple[str, ...]) -> None:
    result = run([*path, "--help"], token=None)
    assert result.exit_code == 0, f"{' '.join(path)} --help: {result.output}"


def test_help_works_without_any_credentials(run: Callable[..., Any]) -> None:
    result = run(["task", "list", "--help"], token=None)
    assert result.exit_code == 0


# --------------------------------------------------------------------------- version


def test_version_flag(run: Callable[..., Any]) -> None:
    result = run(["--version"], token=None)
    assert result.exit_code == 0
    assert __version__ in result.output


def test_version_short_flag(run: Callable[..., Any]) -> None:
    result = run(["-V"], token=None)
    assert result.exit_code == 0
    assert __version__ in result.output


def test_version_command(run: Callable[..., Any]) -> None:
    result = run(["version"], token=None)
    assert result.exit_code == 0
    assert f"yougile version {__version__}" in result.output


# --------------------------------------------------------------------------- errors


def test_unknown_command_is_a_usage_error(run: Callable[..., Any]) -> None:
    result = run(["definitely-not-a-command"], token=None)
    assert result.exit_code != 0


def test_unknown_subcommand_is_a_usage_error(run: Callable[..., Any]) -> None:
    result = run(["task", "definitely-not-a-verb"], token=None)
    assert result.exit_code != 0


def test_no_arguments_prints_help(run: Callable[..., Any]) -> None:
    result = run([], token=None)
    assert "Использование" in result.output


def test_authenticated_command_without_key_exits_four(run: Callable[..., Any]) -> None:
    result = run(["project", "list"], token=None)
    assert result.exit_code == 4
    assert "ошибка" in result.output


def test_error_report_carries_a_hint(run: Callable[..., Any]) -> None:
    result = run(["project", "list"], token=None)
    assert "подсказка" in result.output


# --------------------------------------------------------------------------- completion


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish", "powershell"])
def test_completion_prints_a_script(run: Callable[..., Any], shell: str) -> None:
    result = run(["completion", "-s", shell], token=None)
    assert result.exit_code == 0
    assert result.stdout.strip()


def test_completion_rejects_unknown_shell(run: Callable[..., Any]) -> None:
    result = run(["completion", "-s", "tcsh"], token=None)
    assert result.exit_code != 0


def test_completion_script_follows_the_invoked_program_name(
    run: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["/usr/local/bin/yg", "completion", "-s", "zsh"])
    result = run(["completion", "-s", "zsh"], token=None)
    assert result.exit_code == 0
    assert "#compdef yg" in result.stdout
    assert "_YG_COMPLETE" in result.stdout
    assert "yougile" not in result.stdout


def test_completion_classes_are_registered(run: Callable[..., Any]) -> None:
    """The generated script is useless unless click knows the shell class."""
    from typer._click import shell_completion

    assert shell_completion.get_completion_class("zsh") is not None
    assert shell_completion.get_completion_class("bash") is not None


# --------------------------------------------------------------------------- aliases


def _write_alias(config_home: Path, name: str, expansion: str) -> None:
    from yougile_cli.config import set_alias

    set_alias(name, expansion)
    assert (config_home / "config.yml").exists()


def test_alias_expands(isolated_config: Path) -> None:
    _write_alias(isolated_config, "mine", "task list --assignee @me")
    assert _cli().expand_argv(["mine", "--limit", "5"]) == [
        "task",
        "list",
        "--assignee",
        "@me",
        "--limit",
        "5",
    ]


def test_alias_with_positional_placeholder(isolated_config: Path) -> None:
    _write_alias(isolated_config, "onboard", "user invite $1 --admin")
    assert _cli().expand_argv(["onboard", "ivan@example.com"]) == [
        "user",
        "invite",
        "ivan@example.com",
        "--admin",
    ]


def test_alias_never_shadows_a_real_command(isolated_config: Path) -> None:
    _write_alias(isolated_config, "task", "project list")
    assert _cli().expand_argv(["task", "list"]) == ["task", "list"]


def test_unknown_first_word_is_left_alone(isolated_config: Path) -> None:
    assert _cli().expand_argv(["nope", "--flag"]) == ["nope", "--flag"]


def test_leading_flag_is_left_alone(isolated_config: Path) -> None:
    _write_alias(isolated_config, "mine", "task list")
    assert _cli().expand_argv(["--version"]) == ["--version"]


def test_main_expands_aliases(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_alias(isolated_config, "ver", "version")
    monkeypatch.setattr("sys.argv", ["yougile", "ver"])
    with pytest.raises(SystemExit) as excinfo:
        _cli().main()
    assert excinfo.value.code in (0, None)
    assert f"yougile version {__version__}" in capsys.readouterr().out


def test_main_maps_yougile_errors_to_exit_codes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from yougile_cli.errors import AuthError

    cli = _cli()
    monkeypatch.setattr("sys.argv", ["yougile"])
    monkeypatch.setattr(cli, "app", _raising(AuthError("нет ключа")))
    with pytest.raises(SystemExit) as excinfo:
        cli.main()
    assert excinfo.value.code == 4
    assert "ошибка:" in capsys.readouterr().err


def test_main_handles_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    cli = _cli()
    monkeypatch.setattr("sys.argv", ["yougile"])
    monkeypatch.setattr(cli, "app", _raising(KeyboardInterrupt()))
    with pytest.raises(SystemExit) as excinfo:
        cli.main()
    assert excinfo.value.code == 130


def test_main_handles_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    from yougile_cli.errors import CancelledError

    cli = _cli()
    monkeypatch.setattr("sys.argv", ["yougile"])
    monkeypatch.setattr(cli, "app", _raising(CancelledError()))
    with pytest.raises(SystemExit) as excinfo:
        cli.main()
    assert excinfo.value.code == 1


def test_cancelled_editor_exits_one_silently(
    run: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Отмена в редакторе проходит через настоящий _RootGroup: код 1 и причина в stderr."""
    from yougile_cli.commands import tasks as tasks_module

    monkeypatch.setattr(tasks_module, "_is_tty", lambda *_a: True)
    monkeypatch.setattr(tasks_module, "_open_editor", lambda initial="": None)
    result = run(["task", "create", "Задача", "--editor"])
    assert result.exit_code == 1
    assert "отменено" in result.output.lower()


def test_usage_line_metavars_are_russian(run: Callable[..., Any]) -> None:
    result = run(["bogus"])
    assert "[ОПЦИИ] КОМАНДА [АРГУМЕНТЫ]..." in result.output
    assert "[OPTIONS]" not in result.output


def _raising(exc: BaseException) -> Callable[..., None]:
    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise exc

    return _boom


def test_normalize_json_flag_inserts_empty_value() -> None:
    normalize = _cli().normalize_json_flag
    assert normalize(["task", "list", "--json"]) == ["task", "list", "--json", ""]
    assert normalize(["task", "list", "--json", "-L", "5"]) == [
        "task",
        "list",
        "--json",
        "",
        "-L",
        "5",
    ]
    assert normalize(["task", "list", "--json", "id,title"]) == [
        "task",
        "list",
        "--json",
        "id,title",
    ]


# --------------------------------------------------------------------------- localization

BOX_DRAWING = re.compile(r"[\u2500-\u257f]")
CYRILLIC = re.compile(r"[А-Яа-яЁё]")
LATIN_SENTENCE = re.compile(r"[A-Za-z]{2,} [A-Za-z]{2,}")


def _command_words() -> set[str]:
    """Command names are Latin by design and may be quoted inside Russian prose."""
    return {"yougile", "yg", *(word for path in ALL_PATHS for word in path)}


def _latin_sentences(text: str) -> list[str]:
    words = _command_words()
    offenders = []
    for raw in text.splitlines():
        line = BOX_DRAWING.sub(" ", raw)
        if CYRILLIC.search(line):
            continue
        stripped = " ".join(w for w in line.split() if w.strip("`'\"(),.") not in words)
        if LATIN_SENTENCE.search(stripped):
            offenders.append(raw.strip())
    return offenders


@pytest.mark.parametrize("path", ALL_PATHS, ids=lambda p: " ".join(p) or "root")
def test_help_screens_carry_no_english_sentences(
    run: Callable[..., Any], path: tuple[str, ...]
) -> None:
    result = run([*path, "--help"], token=None)
    assert _latin_sentences(result.output) == []


def test_help_option_description_is_russian(run: Callable[..., Any]) -> None:
    result = run(["task", "list", "--help"], token=None)
    assert "Show this message and exit." not in result.output


def test_usage_and_panels_are_russian(run: Callable[..., Any]) -> None:
    result = run(["--help"], token=None)
    assert "Использование:" in result.output
    assert "Опции" in result.output
    assert "Команды" in result.output


def test_missing_argument_error_is_russian(run: Callable[..., Any]) -> None:
    result = run(["task", "view"], token=None)
    assert result.exit_code == 2
    assert "Отсутствует аргумент" in result.output
    assert "для справки" in result.output


def test_invalid_value_error_is_russian(run: Callable[..., Any]) -> None:
    result = run(["-o", "bogus", "task", "list"], token=None)
    assert result.exit_code == 2
    assert "Недопустимое значение" in result.output


def test_unknown_command_error_is_russian(run: Callable[..., Any]) -> None:
    result = run(["definitely-not-a-command"], token=None)
    assert "Нет такой команды" in result.output


def test_command_typo_hint_is_russian(run: Callable[..., Any]) -> None:
    result = run(["auth", "logn"], token=None)
    assert "Возможно, вы имели в виду" in result.output
    assert "Did you mean" not in result.output


def test_extra_arguments_error_is_russian(run: Callable[..., Any]) -> None:
    result = run(["task", "list", "junk"], token=None)
    assert "Получены лишние аргументы" in result.output


def test_install_russian_ui_is_idempotent() -> None:
    from yougile_cli.i18n import install_russian_ui

    install_russian_ui()
    install_russian_ui()
    import typer.rich_utils as rich_utils

    assert rich_utils.OPTIONS_PANEL_TITLE == "Опции"


def test_install_russian_ui_survives_a_renamed_internal(monkeypatch: pytest.MonkeyPatch) -> None:
    from yougile_cli import i18n

    monkeypatch.setattr(i18n, "_import", lambda _name: None)
    i18n.install_russian_ui()


def test_confirm_prompt_is_russian_and_accepts_both_alphabets() -> None:
    import typer
    from typer.testing import CliRunner

    sub = typer.Typer()

    @sub.command()
    def go() -> None:
        typer.confirm("Удалить?", abort=True)
        typer.echo("готово")

    runner = CliRunner()
    assert "[д/Н]" in runner.invoke(sub, [], input="y\n").output
    assert runner.invoke(sub, [], input="д\n").exit_code == 0
    assert runner.invoke(sub, [], input="n\n").exit_code == 1


# --------------------------------------------------------------------------- flag hoisting


def _hoist(argv: list[str]) -> list[str]:
    return _cli().hoist_root_flags(argv)


def test_hoist_moves_a_trailing_root_option() -> None:
    assert _hoist(["task", "list", "-o", "json"]) == ["-o", "json", "task", "list"]
    assert _hoist(["task", "list", "--output", "json"]) == ["--output", "json", "task", "list"]


def test_hoist_moves_the_inline_value_form() -> None:
    assert _hoist(["task", "list", "--output=json"]) == ["--output=json", "task", "list"]
    assert _hoist(["task", "list", "-ojson"]) == ["-ojson", "task", "list"]


def test_hoist_moves_value_less_boolean_flags() -> None:
    assert _hoist(["column", "list", "--full-ids"]) == ["--full-ids", "column", "list"]
    assert _hoist(["task", "list", "--quiet", "--no-color"]) == [
        "--quiet",
        "--no-color",
        "task",
        "list",
    ]


def test_hoist_leaves_options_the_target_declares_itself() -> None:
    assert _hoist(["webhook", "list", "--full-ids"]) == ["webhook", "list", "--full-ids"]
    assert _hoist(["auth", "login", "--hostname", "foo"]) == ["auth", "login", "--hostname", "foo"]
    assert _hoist(["task", "list", "--full-ids"]) == ["task", "list", "--full-ids"]


def test_output_flag_hoists_uniformly_across_nouns() -> None:
    """`-o` is a root flag everywhere: no noun may redeclare it and shadow the hoist."""
    for noun in ("project", "webhook", "board", "task", "user"):
        assert _hoist([noun, "list", "-o", "json"]) == ["-o", "json", noun, "list"]


def test_hoist_is_a_no_op_when_flags_already_lead() -> None:
    argv = ["-o", "json", "task", "list"]
    assert _hoist(argv) == argv
    assert _hoist(_hoist(argv)) == _hoist(argv)


def test_hoist_is_idempotent_for_trailing_flags() -> None:
    once = _hoist(["task", "list", "--full-ids", "-o", "json"])
    assert _hoist(once) == once


def test_hoist_stops_at_the_double_dash() -> None:
    assert _hoist(["api", "task-list", "--", "-o", "json"]) == [
        "api",
        "task-list",
        "--",
        "-o",
        "json",
    ]


def test_hoist_never_moves_the_value_of_another_option() -> None:
    assert _hoist(["task", "list", "--search", "--quiet"]) == [
        "task",
        "list",
        "--search",
        "--quiet",
    ]
    assert _hoist(["task", "edit", "T1", "--title", "--full-ids"]) == [
        "task",
        "edit",
        "T1",
        "--title",
        "--full-ids",
    ]


def test_hoist_leaves_help_and_version_in_place() -> None:
    assert _hoist(["task", "list", "--help"]) == ["task", "list", "--help"]
    assert _hoist(["task", "list", "-h"]) == ["task", "list", "-h"]


def test_hoist_leaves_an_unknown_command_alone() -> None:
    assert _hoist(["nope", "-o", "json"]) == ["nope", "-o", "json"]


def test_hoist_keeps_positional_targets_in_order() -> None:
    assert _hoist(["task", "view", "T1", "-o", "json"]) == ["-o", "json", "task", "view", "T1"]


def test_expand_argv_hoists_before_normalizing_json(isolated_config: Path) -> None:
    assert _cli().expand_argv(["task", "list", "-o", "json", "--json"]) == [
        "-o",
        "json",
        "task",
        "list",
        "--json",
        "",
    ]


@pytest.mark.parametrize(
    "argv",
    [
        ["task", "list", "-o", "json", "--help"],
        ["-o", "json", "task", "list", "--help"],
        ["column", "list", "--full-ids", "--help"],
        ["project", "list", "-o", "json", "--help"],
        ["api", "--help"],
        ["auth", "login", "--hostname", "foo", "--help"],
    ],
)
def test_hoisted_invocations_still_reach_help(run: Callable[..., Any], argv: list[str]) -> None:
    result = run(_cli().expand_argv(argv), token=None)
    assert result.exit_code == 0, result.output


# --------------------------------------------------------------------------- short help


@pytest.mark.parametrize("path", [p for p in ALL_PATHS if p], ids=lambda p: " ".join(p))
def test_short_help_flag_works_everywhere(run: Callable[..., Any], path: tuple[str, ...]) -> None:
    result = run([*path, "-h"], token=None)
    assert result.exit_code == 0, f"{' '.join(path)} -h: {result.output}"


def test_short_help_on_a_nested_group(run: Callable[..., Any]) -> None:
    result = run(["sticker", "string", "-h"], token=None)
    assert result.exit_code == 0
    assert "Использование:" in result.output


# ------------------------------------------------------------- config resilience


def test_invalid_output_in_config_falls_back_to_table(
    run: Callable[..., Any], isolated_config: Path
) -> None:
    """A typo in config.yml must not brick the command that repairs it."""
    (isolated_config / "config.yml").write_text("output: jsonl\n", encoding="utf-8")
    result = run(["config", "set", "output", "json"], token=None)
    assert result.exit_code == 0, result.output
    assert "jsonl" in result.output


def test_invalid_output_in_config_still_lets_version_run(
    run: Callable[..., Any], isolated_config: Path
) -> None:
    (isolated_config / "config.yml").write_text("output: jsonl\n", encoding="utf-8")
    assert run(["version"], token=None).exit_code == 0


# ------------------------------------------------------------------ colour flags


def test_no_color_flag_beats_clicolor_force(run: Callable[..., Any]) -> None:
    """`--no-color` is a flag: the environment must not override it."""
    result = run(["task", "list", "--no-color"], token=None, env={"CLICOLOR_FORCE": "1"})
    assert "\x1b[" not in result.output


# ---------------------------------------------------------- bare --json + flags


def test_bare_json_does_not_swallow_a_following_root_flag() -> None:
    expand = _cli().expand_argv
    assert expand(["task", "list", "--json", "-o", "json"]) == [
        "-o",
        "json",
        "task",
        "list",
        "--json",
        "",
    ]
    assert expand(["task", "list", "--json", "--quiet"]) == [
        "--quiet",
        "task",
        "list",
        "--json",
        "",
    ]
    assert expand(["task", "list", "--json", "id", "--quiet"]) == [
        "--quiet",
        "task",
        "list",
        "--json",
        "id",
    ]


def test_detect_shell_survives_an_old_typer(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_get_shell_name` приватный: на старом typer его нет, а падать нельзя."""
    cli = _cli()
    module = type(sys)("typer.completion")
    monkeypatch.setitem(sys.modules, "typer.completion", module)
    assert cli._detect_shell() == ""


def test_i18n_warns_when_typer_has_no_vendored_click(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Без typer._click весь каркас снова английский — молчать об этом нельзя."""
    from yougile_cli import i18n

    monkeypatch.setattr(i18n, "_import", lambda _name: None)
    i18n._warn_missing_vendored_click()
    assert "typer._click" in capsys.readouterr().err
