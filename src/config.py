"""LLM client factory + runtime Config."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


def build_llm(model_env: str, temperature: float = 0.0,
              timeout_env: str = "LLM_TIMEOUT_SECONDS", max_tokens_env: str = "LLM_MAX_TOKENS"):
    from langchain_openai import ChatOpenAI

    model = os.getenv(model_env, "")
    if not model:
        raise ValueError(f"{model_env} is not set; add it to .env")
    return ChatOpenAI(
        model=model,
        base_url=os.getenv("OPENAI_API_BASE"),
        temperature=temperature,
        timeout=float(os.getenv(timeout_env, "60")),
        max_retries=int(os.getenv("LLM_CLIENT_MAX_RETRIES", "1")),
        max_tokens=int(os.getenv(max_tokens_env, "4096")),
    )


@dataclass
class Config:
    """Everything defaults to None: an unwired system reports missing data, never guesses."""

    query_executor: Any = None
    classifier_llm: Any = None
    max_classifier_calls: int = 6
    patterns_per_call: int = 80
    manual_trade_assessment: str = ""
