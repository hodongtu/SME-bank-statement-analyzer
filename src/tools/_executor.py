"""Row helpers plus the import-time guard every query tool relies on."""

from typing import Any


def rows(executor: Any, sql: str, params: dict) -> list[dict]:
    return [dict(row) for row in (executor(sql, params) or [])]


def one_row(executor: Any, sql: str, params: dict) -> dict:
    found = rows(executor, sql, params)
    return found[0] if found else {}


def assert_registry_is_sound(tools: tuple[Any, ...]) -> None:
    """No tool appears twice in the registry. """

    seen: set[str] = set()
    for tool_object in tools:
        name = getattr(tool_object, "name", repr(tool_object))
        if name in seen:
            raise TypeError(f"Tool '{name}' is listed twice in ALL_TOOLS.")
        seen.add(name)


def assert_no_model_arguments(tools: tuple[Any, ...]) -> None:
    """No tool may expose an argument a model could fill in. """

    for tool_object in tools:
        schema = getattr(tool_object, "tool_call_schema", None)
        exposed = list(getattr(schema, "model_fields", {}) or {})
        if exposed:
            raise TypeError(
                f"Tool '{tool_object.name}' exposes {exposed} to the model. "
                f"Every argument must be Annotated[..., InjectedToolArg]."
            )


def sqlite_executor(db_path: str) -> Any:
    """A `query_executor` backed by a SQLite file. """

    import sqlite3

    def execute(sql: str, params: dict) -> list[dict]:
        with sqlite3.connect(db_path) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(sql, params).fetchall()]

    return execute
