"""Which customer a run is about: the declared tax code, else the one the tax filings state."""

import re
from typing import Any, NamedTuple

_TAX_CODE = re.compile(r"^\d{10}(?:\d{3})?$")

DECLARED = "run parameter"
KEY_SOURCES: tuple[tuple[str, str], ...] = (
    ("financial_statement", "xml"), ("vat_return", "xml"), ("vat_return", "xlsx"),
    ("vat_return", "xls"), ("vat_return", "pdf"), ("financial_statement", "pdf"),
)


class CustomerKey(NamedTuple):
    """A tax code, and the evidence for it."""

    tax_code: str
    name: str
    source_file: str
    source_field: str
    warnings: tuple[str, ...]

    @property
    def usable(self) -> bool:
        return bool(self.tax_code)


def _clean(raw: Any) -> str:
    """Digits only. Forms print "0104498100-001" and "0104 498 100"."""

    return re.sub(r"\D", "", str(raw or ""))


def _candidates(filings: list[dict], declared: str) -> list[tuple[int, str, str, str, str]]:
    """(rank, tax_code, name, filename, field) for every source that names one."""

    found = []
    if _clean(declared):
        found.append((0, _clean(declared), "", DECLARED, "tax_code"))
    for rank, (kind, fmt) in enumerate(KEY_SOURCES, start=1):
        for filing in filings:
            code = _clean(filing.get("tax_code"))
            if (filing.get("kind"), filing.get("format")) != (kind, fmt) or not code:
                continue
            if filing.get("error") and fmt != "xml":
                continue
            found.append((rank, code, str(filing.get("taxpayer_name") or ""),
                          str(filing.get("file") or ""), f"{kind} {fmt} tax code"))
    return sorted(found, key=lambda row: row[0])


def resolve_customer_key(filings: list[dict], declared: str = "") -> CustomerKey:
    """The customer this run is about, or an empty key with the reason why."""

    candidates = _candidates(filings, declared)
    if not candidates:
        return CustomerKey("", "", "", "", (
            "No tax code was declared and no tax filing states one, so no reference data was queried.",
        ))

    rank, code, name, filename, field = candidates[0]
    warnings = []

    distinct = {row[1] for row in candidates}
    if len(distinct) > 1:
        sources: dict[str, list[str]] = {}
        for row in candidates:
            sources.setdefault(row[1], []).append(row[3])
        listed = ", ".join(f"{tax} ({files[0]}" + (f" + {len(files) - 1} more" if len(files) > 1 else "") + ")"
                           for tax, files in sources.items())
        warnings.append(
            f"The dossier states {len(distinct)} different tax codes: {listed}. "
            f"Using {code} by source precedence — check whether another "
            f"customer's documents got mixed in."
        )

    if not _TAX_CODE.match(code):
        return CustomerKey("", name, filename, field, tuple(warnings) + (
            f"The tax code read from {filename} is {code!r} ({len(code)} digits) "
            f"— not 10 or 13, so NO query was made.",
        ))
    return CustomerKey(code, name, filename, field, tuple(warnings))
