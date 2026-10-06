"""BL/WL - whether a tax code is on the bank's black or watch list."""

from __future__ import annotations

from typing import Annotated, Any

from langchain_core.tools import InjectedToolArg, tool

from src.tools._executor import rows

BLWL_SQL = """
SELECT  list_type, reason
FROM    v_blwl
WHERE   tax_code = :tax_code
"""


@tool("get_blwl_hits")
def get_blwl_hits(
    tax_code: Annotated[str, InjectedToolArg],
    executor: Annotated[Any, InjectedToolArg],
) -> list[dict]:
    """Every list entry for the tax code; empty means not listed."""

    return rows(executor, BLWL_SQL, {"tax_code": tax_code})
