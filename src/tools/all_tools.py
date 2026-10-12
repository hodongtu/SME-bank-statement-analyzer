"""Every query tool, checked once at import."""

from src.tools._executor import assert_no_model_arguments, assert_registry_is_sound
from src.tools.blwl import get_blwl_hits
from src.tools.cic import get_cic_debt
from src.tools.fraud import get_fraud_screening
from src.tools.registry import get_registration
from src.tools.t24 import get_t24_accounts, get_t24_balance, get_t24_transactions
from src.tools.virac import get_virac_financials
from src.tools.trade import get_trade_turnover

ALL_TOOLS = (get_t24_accounts, get_t24_balance, get_t24_transactions, get_fraud_screening, get_cic_debt,
             get_virac_financials, get_trade_turnover, get_blwl_hits, get_registration)

assert_registry_is_sound(ALL_TOOLS)
assert_no_model_arguments(ALL_TOOLS)
