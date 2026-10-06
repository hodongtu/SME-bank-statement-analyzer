"""Virac - independently collected financials by tax code."""

from __future__ import annotations

from typing import Annotated, Any

from langchain_core.tools import InjectedToolArg, tool

from src.tools._executor import rows

VIRAC_SQL = """
SELECT  year, revenue, total_assets, equity
FROM    v_virac_financials
WHERE   tax_code = :tax_code
"""


@tool("get_virac_financials")
def get_virac_financials(
    tax_code: Annotated[str, InjectedToolArg],
    executor: Annotated[Any, InjectedToolArg],
) -> dict:
    """Revenue, total assets and equity by year."""

    return {str(r["year"]): r for r in rows(executor, VIRAC_SQL, {"tax_code": tax_code})}
