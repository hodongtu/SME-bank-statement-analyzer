"""T24 - the customer's accounts at TCB and their end-of-day balances."""

from __future__ import annotations

from typing import Annotated, Any

from langchain_core.tools import InjectedToolArg, tool

from src.tools._executor import one_row, rows

ACCOUNTS_SQL = """
SELECT  account_no, currency, status, opened_on
FROM    v_t24_accounts
WHERE   tax_code = :tax_code
"""

TRANSACTIONS_SQL = """
SELECT  t.account_number, t.currency, t.entry_id, t.debit_amount, t.credit_amount, t.narrative,
        t.transaction_code, t.transaction_name, t.date_time, t.transaction_type,
        t.settlement_account_number, t.settlement_customer_name, t.settlement_customer_tax_code,
        t.settlement_bank_code, t.settlement_bank_name
FROM    v_t24_transactions t
JOIN    v_t24_accounts a ON a.account_no = t.account_number
WHERE   a.tax_code = :tax_code AND t.date_time >= :date_from AND t.date_time < :date_to
ORDER BY t.account_number, t.date_time, t.entry_id
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


@tool("get_t24_transactions")
def get_t24_transactions(
    tax_code: Annotated[str, InjectedToolArg],
    date_from: Annotated[str, InjectedToolArg],
    date_to: Annotated[str, InjectedToolArg],
    executor: Annotated[Any, InjectedToolArg],
) -> list[dict]:
    """Every transaction on the customer's TCB accounts with date_from <= date_time < date_to (ISO dates)."""

    return rows(executor, TRANSACTIONS_SQL, {"tax_code": tax_code, "date_from": date_from, "date_to": date_to})
