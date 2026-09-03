"""Typer sub-applications and stand-alone commands, one module per API resource group.

Everything the root application mounts is re-exported from here so that
``cli.py`` has a single import site.
"""

from __future__ import annotations

from .api_cmd import api_cmd, normalize_endpoint
from .auth import app as auth_app
from .auth import keys_app
from .boards import app as board_app
from .chats import app as chat_app
from .chats import message_app
from .columns import app as column_app
from .departments import app as department_app
from .misc import (
    alias_app,
    browse_cmd,
    company_app,
    config_app,
    crm_app,
    expand_alias,
    file_app,
    status_cmd,
    version_cmd,
)
from .projects import app as project_app
from .projects import role_app
from .stickers import app as sticker_app
from .stickers import sprint_app, sprint_state_app, string_app, string_state_app
from .tasks import app as task_app
from .tasks import subscribers_app
from .users import app as user_app
from .webhooks import app as webhook_app

__all__ = [
    "alias_app",
    "api_cmd",
    "auth_app",
    "board_app",
    "browse_cmd",
    "chat_app",
    "column_app",
    "company_app",
    "config_app",
    "crm_app",
    "department_app",
    "expand_alias",
    "file_app",
    "keys_app",
    "message_app",
    "normalize_endpoint",
    "project_app",
    "role_app",
    "sprint_app",
    "sprint_state_app",
    "status_cmd",
    "sticker_app",
    "string_app",
    "string_state_app",
    "subscribers_app",
    "task_app",
    "user_app",
    "version_cmd",
    "webhook_app",
]
