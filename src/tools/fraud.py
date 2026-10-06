"""Fraud - the screening result for each account the statements cover."""

from __future__ import annotations

from typing import Annotated, Any

from langchain_core.tools import InjectedToolArg, tool

from src.tools._executor import rows

FRAUD_SQL = """
SELECT  account_no, screened_on, status, alert, note
FROM    v_fraud_screening
WHERE   tax_code = :tax_code
"""


@tool("get_fraud_screening")
def get_fraud_screening(
    tax_code: Annotated[str, InjectedToolArg],
    executor: Annotated[Any, InjectedToolArg],
) -> list[dict]:
    """One row per screened account: status, alert flag, note."""

    return rows(executor, FRAUD_SQL, {"tax_code": tax_code})
