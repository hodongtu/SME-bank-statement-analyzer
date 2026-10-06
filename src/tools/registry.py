"""Business registry - legal identity, legal representative and members."""

from __future__ import annotations

from typing import Annotated, Any

from langchain_core.tools import InjectedToolArg, tool

from src.tools._executor import one_row, rows

COMPANY_SQL = """
SELECT  name, main_industry, status, legal_representative, charter_capital
FROM    v_registry_company
WHERE   tax_code = :tax_code
"""

MEMBERS_SQL = """
SELECT  name, stake_pct
FROM    v_registry_members
WHERE   tax_code = :tax_code
"""


@tool("get_registration")
def get_registration(
    tax_code: Annotated[str, InjectedToolArg],
    executor: Annotated[Any, InjectedToolArg],
) -> dict:
    """Registered name, main industry, status, representative, members."""

    company = one_row(executor, COMPANY_SQL, {"tax_code": tax_code})
    if not company:
        return {}
    company["members"] = rows(executor, MEMBERS_SQL, {"tax_code": tax_code})
    return company
