"""T24 - the customer's accounts at TCB and their end-of-day balances."""

from __future__ import annotations

from typing import Annotated, Any

from langchain_core.tools import InjectedToolArg, tool

from src.tools._executor import one_row, rows

ACCOUNTS_SQL = """
SELECT  account_no, currency, status
FROM    v_t24_accounts
WHERE   tax_code = :tax_code
"""

BALANCE_SQL = """
SELECT  balance_date, balance
FROM    v_t24_balances
WHERE   account_no = :account AND balance_date <= :day
ORDER BY balance_date DESC
LIMIT 1
"""


@tool("get_t24_accounts")
def get_t24_accounts(
    tax_code: Annotated[str, InjectedToolArg],
    executor: Annotated[Any, InjectedToolArg],
) -> list[dict]:
    """Current and settlement accounts the customer holds at TCB."""

    return rows(executor, ACCOUNTS_SQL, {"tax_code": tax_code})


@tool("get_t24_balance")
def get_t24_balance(
    account: Annotated[str, InjectedToolArg],
    day: Annotated[str, InjectedToolArg],
    executor: Annotated[Any, InjectedToolArg],
) -> dict:
    """End-of-day balance of one account on or before a day (ISO date)."""

    return one_row(executor, BALANCE_SQL, {"account": account, "day": day})
