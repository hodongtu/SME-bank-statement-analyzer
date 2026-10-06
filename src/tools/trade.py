"""Customs - import and export turnover by tax code."""

from __future__ import annotations

from typing import Annotated, Any

from langchain_core.tools import InjectedToolArg, tool

from src.tools._executor import rows

TRADE_SQL = """
SELECT  year, export_value, import_value, main_goods, main_market
FROM    v_customs_trade
WHERE   tax_code = :tax_code
"""


@tool("get_trade_turnover")
def get_trade_turnover(
    tax_code: Annotated[str, InjectedToolArg],
    executor: Annotated[Any, InjectedToolArg],
) -> dict:
    """Export and import turnover by year, in VND."""

    return {str(r["year"]): r for r in rows(executor, TRADE_SQL, {"tax_code": tax_code})}
