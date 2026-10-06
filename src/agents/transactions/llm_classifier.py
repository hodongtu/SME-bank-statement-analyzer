"""Classify what the rules left unclassified, one call per batch of narrative patterns."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from src.categories import INFLOW, OUTFLOW, UNCLASSIFIED
from src.agents.transactions.counterparty import EXTERNAL, Directory, core_name
from src.agents.transactions.transaction_classification import MODEL_SOURCE, UNKNOWN_SOURCE
from src.prompts import system_prompt
from src.types import Transaction
from src.utils.common import normalize_text

MIN_CONFIDENCE = 0.6

HUMAN_PROMPT = "Items:\n{items}"


@dataclass
class Pattern:
    direction: str
    text: str
    transactions: list[Transaction] = field(default_factory=list)

    @property
    def value(self) -> float:
        return sum(float(t.amount) for t in self.transactions)


def pattern_of(txn: Transaction) -> str:
    return re.sub(r"\d+", "#", normalize_text(f"{txn.narrative} {txn.cp_name}")).strip()


def group_unclassified(transactions: list[Transaction]) -> list[Pattern]:
    groups: dict[tuple[str, str], Pattern] = {}
    for txn in transactions:
        if txn.label_source != UNKNOWN_SOURCE:
            continue
        text = pattern_of(txn)
        if not text:
            continue
        key = (txn.direction, text)
        groups.setdefault(key, Pattern(txn.direction, text)).transactions.append(txn)
    return sorted(groups.values(), key=lambda p: p.value, reverse=True)


def _codes(labels: dict[str, str]) -> str:
    return "\n".join(f"- {code}: {label}" for code, label in labels.items())


def build_chain(llm, customer: str):
    from langchain_core.messages import SystemMessage
    from langchain_core.output_parsers import JsonOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    system = system_prompt("classify_transactions", customer=customer or "khách hàng",
                           inflow=_codes(INFLOW), outflow=_codes(OUTFLOW),
                           unknown_in=UNCLASSIFIED["IN"], unknown_out=UNCLASSIFIED["OUT"])
    prompt = ChatPromptTemplate.from_messages([SystemMessage(content=system), ("human", HUMAN_PROMPT)])
    return prompt | llm | JsonOutputParser()


def apply_answers(batch: list[Pattern], answer: dict, directory: Directory | None) -> int:
    """Validate each answer against the closed vocabulary; return how many patterns were labelled."""

    labelled = 0
    for item in (answer or {}).get("items") or []:
        try:
            index, code = int(item.get("id")), str(item.get("category") or "")
            confidence = float(item.get("confidence") or 0)
        except (TypeError, ValueError):
            continue
        if not 0 <= index < len(batch):
            continue
        pattern = batch[index]
        allowed = INFLOW if pattern.direction == "IN" else OUTFLOW
        if code not in allowed or code == UNCLASSIFIED[pattern.direction] or confidence < MIN_CONFIDENCE:
            continue
        name = str(item.get("counterparty") or "").strip()
        for txn in pattern.transactions:
            txn.category, txn.label_source = code, MODEL_SOURCE
            txn.match_note = f"mô hình phân loại theo mẫu nội dung, độ tin cậy {confidence:.2f}"
            if name and not txn.counterparty_id:
                hit = directory.by_name(name, ("131", "331")) if directory else None
                if hit:
                    txn.counterparty_id, txn.counterparty_name = hit[0].id, hit[0].name
                elif directory is None or not directory.by_name(name, ("self",)):
                    legal = directory.legal_forms if directory else []
                    txn.counterparty_id = f"{EXTERNAL}:{core_name(name, legal, [])}"
                    txn.counterparty_name = name
        labelled += 1
    return labelled


def classify_remaining(transactions: list[Transaction], config, settings: dict,
                       customer: str = "", directory: Directory | None = None) -> int:
    """Spend at most config.max_classifier_calls calls; returns the number of calls made."""

    patterns = group_unclassified(transactions)
    if not patterns or config.classifier_llm is None:
        return 0
    chain = build_chain(config.classifier_llm, customer)
    size = max(1, int(config.patterns_per_call))
    calls = 0
    for start in range(0, len(patterns), size):
        if calls >= config.max_classifier_calls:
            break
        batch = patterns[start:start + size]
        items = "\n".join(json.dumps({"id": i, "direction": p.direction, "pattern": p.text,
                                      "occurrences": len(p.transactions)}, ensure_ascii=False)
                          for i, p in enumerate(batch))
        calls += 1
        try:
            answer = chain.invoke({"items": items})
        except Exception:                                  # noqa: BLE001 - a failed batch stays unclassified
            continue
        apply_answers(batch, answer, directory)
    return calls
