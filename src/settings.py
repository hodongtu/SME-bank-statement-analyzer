"""Load and validate the YAML files under config/."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from src.categories import LABELS, direction_of
from src.utils.paths import PROJECT_ROOT

CONFIG_DIR = PROJECT_ROOT / "config"
INDICATORS = ("inflow_to_reported_revenue", "vat_gap", "inflow_matched_131",
              "unclassified_share", "reported_vs_third_party", "trade_industry_legal")
BACKENDS = ("local", "it_service")
LEVELS = ("Tốt", "Trung bình", "Cao")


class SettingsError(RuntimeError):
    """A file under config/ is malformed."""


def _read(name: str, directory: Path) -> dict[str, Any]:
    path = directory / name
    if not path.is_file():
        raise SettingsError(f"config/{name}: file not found")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _need(raw: dict, dotted: str, source: str) -> Any:
    node: Any = raw
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            raise SettingsError(f"config/{source}: missing {dotted}")
        node = node[part]
    return node


def _check_rules(rules: list[dict], source: str) -> None:
    for rule in rules:
        code, direction = rule.get("category"), rule.get("direction")
        if code not in LABELS:
            raise SettingsError(f"config/{source}: unknown category {code!r}")
        if direction_of(code) != direction:
            raise SettingsError(f"config/{source}: {code} is not an {direction} category")
        if not (rule.get("names") or rule.get("keywords")):
            raise SettingsError(f"config/{source}: rule for {code} has no words")


def _check_scoring(scoring: dict) -> None:
    indicators = scoring.get("indicators") or {}
    if tuple(indicators) != INDICATORS:
        raise SettingsError(f"config/policy.yaml: scoring.indicators must be {INDICATORS}")
    total = sum(entry.get("weight", 0) for entry in indicators.values())
    if total != 100:
        raise SettingsError(f"config/policy.yaml: indicator weights sum to {total}, not 100")
    for key, entry in indicators.items():
        if not entry.get("label"):
            raise SettingsError(f"config/policy.yaml: indicator {key} has no label")
        if "levels" not in entry and ("bands" not in entry or "otherwise" not in entry):
            raise SettingsError(f"config/policy.yaml: indicator {key} needs bands+otherwise or levels")
    minimums = [band["min"] for band in scoring.get("rating") or []]
    if not minimums or minimums != sorted(minimums, reverse=True) or minimums[-1] != 0:
        raise SettingsError("config/policy.yaml: scoring.rating must descend to min 0")


def load_settings(directory: Path | str | None = None) -> dict[str, Any]:
    base = Path(directory) if directory else CONFIG_DIR
    policy = _read("policy.yaml", base)
    for dotted in ("analysis.required_months", "analysis.window_months",
                   "analysis.full_month_min_day_share", "analysis.min_overlap_months_financials",
                   "analysis.vat_required_months", "analysis.balance_tolerance_vnd",
                   "analysis.base_currency", "business_inflow_codes", "business_outflow_codes",
                   "coverage.high", "coverage.medium", "coverage.conclusion_by_level",
                   "trend.recent_months", "partners.top_n", "partners.min_overlap_months",
                   "matching.name_similarity_min", "matching.legal_forms",
                   "scoring.indicators", "scoring.rating", "scoring.insufficient",
                   "classification.code_rules", "classification.keyword_rules"):
        _need(policy, dotted, "policy.yaml")
    for code in policy["business_inflow_codes"] + policy["business_outflow_codes"]:
        if code not in LABELS:
            raise SettingsError(f"config/policy.yaml: unknown category {code!r}")
    if set(policy["coverage"]["conclusion_by_level"]) != set(LEVELS):
        raise SettingsError(f"config/policy.yaml: conclusion_by_level must name {LEVELS}")
    if policy["analysis"]["window_months"] < policy["analysis"]["required_months"]:
        raise SettingsError("config/policy.yaml: window_months < required_months")
    _check_rules(policy["classification"]["code_rules"], "policy.yaml")
    _check_rules(policy["classification"]["keyword_rules"], "policy.yaml")
    _check_scoring(policy["scoring"])

    formats = _read("statement_formats.yaml", base).get("formats") or []
    if not formats:
        raise SettingsError("config/statement_formats.yaml: no format declared")
    for entry in formats:
        if not entry.get("id") or not entry.get("date_formats"):
            raise SettingsError("config/statement_formats.yaml: format needs id and date_formats")
        if bool(entry.get("columns")) == bool(entry.get("header_synonyms")):
            raise SettingsError(
                f"config/statement_formats.yaml: {entry['id']} needs exactly one of "
                f"columns / header_synonyms")

    documents = _read("documents.yaml", base).get("types") or {}
    if not documents:
        raise SettingsError("config/documents.yaml: no document type declared")

    extraction = _read("extraction.yaml", base)
    for dotted in ("routing.structured", "routing.ocr", "formats.structured", "formats.ocr",
                   "it_service.base_url_env", "it_service.token_env", "it_service.timeout_seconds",
                   "it_service.max_calls_per_run", "it_service.doc_types"):
        _need(extraction, dotted, "extraction.yaml")
    for group, backend in extraction["routing"].items():
        if backend not in BACKENDS:
            raise SettingsError(f"config/extraction.yaml: routing.{group} must be one of {BACKENDS}")
        if group not in extraction["formats"]:
            raise SettingsError(f"config/extraction.yaml: routing.{group} has no formats entry")

    return {**policy, "statement_formats": formats, "document_types": documents, "extraction": extraction}


@lru_cache(maxsize=1)
def get_settings() -> dict[str, Any]:
    return load_settings()
