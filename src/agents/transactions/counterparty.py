"""Who is on the other side of a transaction, and is it someone we know."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from src.types import Ledger, Transaction
from src.utils.common import digits_only, normalize_text

SELF, RELATED, LENDER, LEDGER_131, LEDGER_331, EXTERNAL = (
    "self", "related", "lender", "131", "331", "external")
PREFERENCE = {
    "IN": (SELF, RELATED, LENDER, LEDGER_131, LEDGER_331),
    "OUT": (SELF, RELATED, LENDER, LEDGER_331, LEDGER_131),
}

_STOP = {"chuyen", "ck", "ct", "tu", "toi", "ma", "gd", "mbvcb", "nop", "techcombank",
         "qua", "zalo", "zal", "nhanh", "khoan", "mua", "tt", "cho", "so", "cmnd", "cccd", "rut",
         "ibft", "ref", "den", "sang", "lan", "dot", "ngay", "hd", "tien", "trung", "ho", "b",
         "o"}
_PREFIX_NOISE = {"qr", "techcombank", "mbvcb", "ibft", "ft", "vcb", "bidv", "acb", "mb",
                 "tpb", "vpb", "agribank", "vietinbank", "ib", "sms", "napas"}
_BEFORE_TRIGGER = {"chuyen", "ck", "nop"}
_NAME_TOKEN = re.compile(r"^[a-z]+$")
_HONORIFICS = {"ong", "ba", "anh", "chi"}
_TIME_WORDS = {"thang", "nam", "ngay", "ky", "quy"}


@dataclass
class Party:
    id: str
    kind: str
    name: str
    tax_code: str = ""
    accounts: set[str] = field(default_factory=set)
    core: str = ""


def core_name(name: str, legal_forms: list[str], branch_markers: list[str]) -> str:
    text = f" {normalize_text(name)} "
    for marker in branch_markers:
        position = text.find(f" {marker} ")
        if position > 0:
            text = text[:position] + " "
    for form in sorted(legal_forms, key=len, reverse=True):
        text = text.replace(f" {form} ", " ")
    return " ".join(text.split())


def similarity(left: str, right: str) -> tuple[float, str]:
    if not left or not right:
        return 0.0, ""
    if left == right:
        return 1.0, "trùng tên"
    if left.replace(" ", "") == right.replace(" ", ""):
        return 0.99, "trùng tên (khác khoảng trắng)"
    small, large = sorted((left.split(), right.split()), key=len)
    if (len(small) >= 2 and set(small) <= set(large)
            and small[0] == large[0] and small[-1] == large[-1]):
        return 0.92, "khớp tên rút gọn"
    if len(small) >= 2 and len(" ".join(small)) >= 6 and large[:len(small)] == small:
        return 0.90, "khớp phần đầu tên"
    return SequenceMatcher(None, left, right).ratio(), "tên gần giống"


def _take_name(tokens: list[str]) -> str:
    while tokens and tokens[0] in _HONORIFICS:
        tokens = tokens[1:]
    taken: list[str] = []
    for index, token in enumerate(tokens):
        if token in _STOP or not _NAME_TOKEN.match(token) or len(token) == 1:
            break
        if token == "thanh" and tokens[index + 1:index + 2] == ["toan"]:
            break
        taken.append(token)
        if len(taken) == 12:
            break
    following = tokens[len(taken):len(taken) + 1]
    if taken and taken[-1] in _TIME_WORDS and following and following[0].isdigit():
        taken.pop()
    return " ".join(taken) if len(taken) >= 2 else ""


def names_in_narrative(narrative: str, direction: str = "IN") -> list[str]:
    """Candidate party names written into a transfer description, best first."""

    tokens = normalize_text(narrative).split()
    found: list[str] = []
    for index, token in enumerate(tokens):
        if token == "ho" and set(tokens[max(0, index - 3):index]) & {"chuyen", "nop", "trung", "tien"}:
            rest = tokens[index + 1:]
            found.append(_take_name(rest[1:] if rest[:1] == ["cho"] else rest))
        if token == "b" and tokens[index + 1:index + 2] == ["o"]:
            found.append(_take_name(tokens[index + 2:]))
        if token == "cho" and direction == "OUT":
            found.append(_take_name(tokens[index + 1:]))
        if token == "tu" and index > 0 and tokens[index - 1] == "ct":
            rest = [t for t in tokens[index + 1:] if not t.isdigit()]
            found.append(_take_name(rest))
    if direction == "OUT":
        return _unique(found)
    start = 0
    while start < len(tokens) and (tokens[start] in _PREFIX_NOISE or not _NAME_TOKEN.match(tokens[start])
                                   or len(tokens[start]) == 1):
        start += 1
    head: list[str] = []
    for token in tokens[start:]:
        if token in _BEFORE_TRIGGER:
            if 2 <= len(head) <= 8:
                found.append(" ".join(head))
            break
        if token in _PREFIX_NOISE:
            head = []
        elif _NAME_TOKEN.match(token):
            head.append(token)
    return _unique(found)


def _unique(found: list[str]) -> list[str]:
    unique: list[str] = []
    for name in found:
        if name and name not in unique:
            unique.append(name)
    return unique


class Directory:
    """Every party the case already names: the customer, its people, its ledgers."""

    def __init__(self, settings: dict) -> None:
        matching = settings["matching"]
        self.legal_forms = matching["legal_forms"]
        self.branch_markers = matching.get("branch_markers") or []
        self.threshold = float(matching["name_similarity_min"])
        self.parties: list[Party] = []

    def add(self, kind: str, name: str, tax_code: str = "", accounts: set[str] | None = None,
            party_id: str = "") -> Party:
        party = Party(id=party_id or f"{kind}:{len(self.parties)}", kind=kind, name=name,
                      tax_code=digits_only(tax_code), accounts=set(accounts or ()),
                      core=core_name(name, self.legal_forms, self.branch_markers))
        self.parties.append(party)
        return party

    def add_ledger(self, ledger: Ledger) -> None:
        kind = LEDGER_131 if ledger.account == "131" else LEDGER_331
        for index, entry in enumerate(ledger.entries):
            self.add(kind, entry.name, entry.tax_code, party_id=f"{kind}:{index}")

    def by_tax_code(self, tax_code: str, kinds: tuple[str, ...]) -> Party | None:
        code = digits_only(tax_code)
        if not code:
            return None
        return next((p for kind in kinds for p in self.parties
                     if p.kind == kind and p.tax_code == code), None)

    def by_account(self, account: str) -> Party | None:
        number = digits_only(account)
        return next((p for p in self.parties if number and number in p.accounts), None)

    def by_name(self, name: str, kinds: tuple[str, ...]) -> tuple[Party, float, str] | None:
        core = core_name(name, self.legal_forms, self.branch_markers)
        if len(core) < 4:
            return None
        for kind in kinds:
            hits = []
            for party in self.parties:
                if party.kind == kind:
                    score, how = similarity(core, party.core)
                    if score >= self.threshold:
                        hits.append((party, score, how))
            if not hits:
                continue
            hits.sort(key=lambda hit: hit[1], reverse=True)
            top = hits[0]
            rivals = [h for h in hits if h[1] == top[1] and h[0].core != top[0].core]
            if top[1] < 0.95 and rivals:
                continue
            return top
        return None


def resolve(txn: Transaction, directory: Directory) -> None:
    """Fill counterparty_id / counterparty_name on one transaction."""

    kinds = PREFERENCE[txn.direction]
    party = directory.by_tax_code(txn.cp_tax_code, kinds) or directory.by_account(txn.cp_account)
    if party:
        txn.counterparty_id, txn.counterparty_name = party.id, party.name
        txn.match_note = "khớp MST" if txn.cp_tax_code and party.tax_code else "khớp số tài khoản"
        return

    candidates = ([txn.cp_name] if txn.cp_name else []) + names_in_narrative(txn.narrative, txn.direction)
    for candidate in candidates:
        hit = directory.by_name(candidate, kinds)
        if hit is None:
            continue
        party, _, how = hit
        if party.kind == SELF and txn.direction == "OUT" and candidate != txn.cp_name:
            continue
        txn.counterparty_id, txn.counterparty_name = party.id, party.name
        txn.match_note = how + ("" if candidate == txn.cp_name else " trong nội dung chuyển khoản")
        return

    outsider = txn.cp_name or next(
        (c for c in names_in_narrative(txn.narrative, txn.direction)
         if not directory.by_name(c, (SELF,))), "")
    if outsider:
        core = core_name(outsider, directory.legal_forms, directory.branch_markers)
        txn.counterparty_id = f"{EXTERNAL}:{core}"
        txn.counterparty_name = txn.cp_name or outsider.title()
        txn.match_note = "đối tác chưa có trong sổ 131/331"


def kind_of(counterparty_id: str) -> str:
    return counterparty_id.split(":", 1)[0] if counterparty_id else ""
