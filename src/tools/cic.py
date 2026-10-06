"""CIC - outstanding debt by lender, for the customer or a counterparty."""

from __future__ import annotations

from typing import Annotated, Any

from langchain_core.tools import InjectedToolArg, tool

from src.tools._executor import rows

CIC_SQL = """
SELECT  reported_on, lender, outstanding, debt_group
FROM    v_cic_debt
WHERE   tax_code = :tax_code
"""


@tool("get_cic_debt")
def get_cic_debt(
    tax_code: Annotated[str, InjectedToolArg],
    executor: Annotated[Any, InjectedToolArg],
) -> list[dict]:
    """Latest debt per lender with its debt group."""

    return rows(executor, CIC_SQL, {"tax_code": tax_code})
