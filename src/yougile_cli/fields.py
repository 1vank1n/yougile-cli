"""Static field schema of the API v2 resources, used by `--json` with no value.

``gh`` answers a bare ``--json`` with the list of fields; that answer must not
depend on a network round trip, on a saved token, or on the response being
non-empty. There is no machine-readable description of the endpoints in this
repository, so nothing here is invented: every name below is one this project
already sends in a request body, prints as a table column, or receives in a
response fixture under ``tests/``. A few rows this CLI composes itself (task
attachments, aliases, the cache report) live here for the same reason: their
keys are literals in ``commands/``. A resource whose field list is not confirmed
that way is deliberately absent — :func:`static_fields` returns an empty tuple
for it and the caller falls back to the fields of the rows it has.
"""

from __future__ import annotations

from .config import SETTING_KEYS

__all__ = ["RESOURCE_FIELDS", "static_fields"]

RESOURCE_FIELDS: dict[str, tuple[str, ...]] = {
    "task": (
        "archived",
        "assigned",
        "checklists",
        "color",
        "columnId",
        "completed",
        "createdBy",
        "deadline",
        "deleted",
        "description",
        "id",
        "idTaskCommon",
        "idTaskProject",
        "stickers",
        "subtasks",
        "timeTracking",
        "timestamp",
        "title",
    ),
    "board": (
        "deleted",
        "id",
        "projectId",
        "stickers",
        "title",
    ),
    "column": (
        "boardId",
        "color",
        "deleted",
        "id",
        "title",
    ),
    "project": (
        "deleted",
        "departments",
        "id",
        "timestamp",
        "title",
        "users",
    ),
    "project-role": (
        "description",
        "id",
        "name",
        "permissions",
    ),
    "department": (
        "deleted",
        "id",
        "parentId",
        "title",
        "users",
    ),
    "user": (
        "email",
        "id",
        "isAdmin",
        "lastActivity",
        "messengerOnly",
        "realName",
        "status",
    ),
    "webhook": (
        "deleted",
        "disabled",
        "event",
        "failuresSinceLastSuccess",
        "filters",
        "id",
        "lastSuccess",
        "url",
    ),
    "chat": (
        "deleted",
        "id",
        "roleConfigMap",
        "title",
        "userRoleMap",
        "users",
    ),
    "chat-message": (
        "deleted",
        "editTimestamp",
        "fromUserId",
        "id",
        "label",
        "text",
        "textHtml",
    ),
    "company": (
        "apiData",
        "deleted",
        "id",
        "title",
    ),
    "sticker-string": (
        "deleted",
        "icon",
        "id",
        "name",
        "states",
    ),
    "sticker-string-state": (
        "color",
        "deleted",
        "id",
        "name",
    ),
    "sticker-sprint": (
        "deleted",
        "id",
        "name",
        "states",
    ),
    "sticker-sprint-state": (
        "begin",
        "deleted",
        "end",
        "id",
        "name",
    ),
    "alias": (
        "expansion",
        "name",
    ),
    "assigned-task": (
        "board",
        "boardId",
        "code",
        "column",
        "deadline",
        "id",
        "title",
    ),
    "cache": (
        "entries",
        "path",
        "removed",
    ),
    # The settings live in config.yml, so their names come from config itself.
    "setting": tuple(sorted(SETTING_KEYS)),
    "webhook-event": (
        "description",
        "event",
    ),
    "task-attachment": (
        "kind",
        "name",
        "path",
        "size",
        "source",
        "url",
    ),
    "api-key": (
        "companyId",
        "deleted",
        "key",
        "timestamp",
    ),
}


def static_fields(resource: str | None) -> tuple[str, ...]:
    """Known field names of `resource`; empty when the resource has no confirmed schema."""
    if not resource:
        return ()
    return RESOURCE_FIELDS.get(resource, ())
