"""``hermes auth add`` must not crash (or hang) when its interactive prompts hit an exhausted
stdin.

Regression for #136736: without ``--api-key`` the key prompt let a raw ``EOFError`` escape —
a traceback on POSIX and an indefinite block in ``msvcrt.getwch()`` on Windows.  ``--api-key``
alone then broke on the optional *label* prompt because ``sys.stdin.isatty()`` is True for the
Windows NUL device, so ``--api-key sk-... < /dev/null`` crashed while a piped stdin worked.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from hermes_cli import auth_commands


@pytest.fixture
def profile_env(tmp_path, monkeypatch):
    home = tmp_path / "hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home


def test_auth_add_api_key_prompt_eof_exits_without_traceback(profile_env, monkeypatch):
    """EOF on the key prompt is a user-facing message, not a traceback."""
    def exhausted(_prompt: str) -> str:
        raise EOFError

    monkeypatch.setattr(auth_commands, "masked_secret_prompt", exhausted)

    args = SimpleNamespace(provider="openrouter", auth_type="api-key", api_key=None, label=None)
    with pytest.raises(SystemExit) as excinfo:
        auth_commands.auth_add_command(args)

    assert excinfo.value.code is not None and excinfo.value.code != 0
    assert "--api-key" in str(excinfo.value.code)


def test_auth_add_api_key_skips_label_prompt_without_a_console(profile_env, monkeypatch):
    """`--api-key` alone must be enough non-interactively: a NUL stdin is not a console."""
    monkeypatch.setattr(auth_commands, "stdin_is_console", lambda: False)
    monkeypatch.setattr(
        auth_commands, "line_input",
        lambda _prompt: pytest.fail("label prompt must not run without a console"))

    auth_commands.auth_add_command(
        SimpleNamespace(provider="openrouter", auth_type="api-key",
                        api_key="sk-or-test", label=None))

    payload = json.loads((profile_env / "auth.json").read_text(encoding="utf-8-sig"))
    entry = next(e for e in payload["credential_pool"]["openrouter"] if e["source"] == "manual")
    assert entry["access_token"] == "sk-or-test"
    assert entry["label"] == "api-key-1"
