"""The chat models the agent's parts run on, through OpenRouter: the claim
agent's, from a version of its configuration, and the improver's."""

import os
from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MODEL_TIMEOUT = 120
# How a run records a model given no reasoning effort, since Luna has "none" as a
# level; the backend's models allowed use the same word.
DEFAULT_EFFORT = "default"


def model(configuration: dict[str, Any], timeout: int = MODEL_TIMEOUT) -> ChatOpenAI:
    """Return the model a configuration names, at its reasoning effort, or the model
    in MODEL_NAME at its default effort when that is set."""
    name = os.getenv("MODEL_NAME")
    return ChatOpenAI(
        model=name or configuration["model"],
        base_url=OPENROUTER_BASE_URL,
        api_key=SecretStr(os.environ["OPENROUTER_API_KEY"]),
        reasoning_effort=None if name else configuration["reasoning_effort"],
        timeout=timeout,
        max_retries=5,
    )
