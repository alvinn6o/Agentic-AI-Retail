"""Base agent utilities: model factory, prompt loading, and retry-with-repair."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

import yaml
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from backend.app.core.config import Settings, get_settings
from backend.app.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt(name: str) -> dict[str, str]:
    """Load a YAML prompt file. Returns dict with 'system' and 'user' keys."""
    path = _PROMPTS_DIR / f"{name}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {"system": data["system"], "user": data["user"]}


def build_llm(settings: Settings | None = None) -> BaseChatModel:
    """Instantiate the configured language model provider (Anthropic, OpenAI, or Ollama)."""
    s = settings or get_settings()
    if s.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=s.llm_model_name,
            api_key=s.anthropic_api_key,  # type: ignore[arg-type]
            temperature=0,
            max_tokens=8192,
        )
    if s.llm_provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=s.llm_model_name,
            api_key=s.openai_api_key,  # type: ignore[arg-type]
            temperature=0,
            max_tokens=8192,
        )
    # Ollama
    from langchain_community.chat_models import ChatOllama
    return ChatOllama(
        model=s.llm_model_name,
        base_url=s.ollama_base_url,
        temperature=0,
    )


def call_with_repair(
    llm: BaseChatModel,
    system: str,
    user: str,
    schema: type[T],
    max_retries: int = 3,
) -> T:
    """
    Invoke the language model and parse the response into `schema`.
    On parse failure, send a structured repair prompt and retry up to max_retries times.
    Ensures all agent outputs conform to the expected Pydantic schema before returning.
    """
    messages = [SystemMessage(content=system), HumanMessage(content=user)]

    for attempt in range(max_retries):
        response = llm.invoke(messages)
        raw = response.content

        # Extract JSON block if wrapped in markdown code fences
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()

        try:
            data = json.loads(raw)
            return schema.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning(
                "call_with_repair.parse_failed",
                attempt=attempt + 1,
                error=str(exc)[:200],
            )
            if attempt + 1 >= max_retries:
                raise
            # Repair prompt
            repair_msg = HumanMessage(
                content=(
                    f"Your previous response could not be parsed.\n"
                    f"Error: {exc}\n\n"
                    f"Please return ONLY valid JSON conforming to the {schema.__name__} schema. "
                    "No markdown, no explanation, just the JSON object."
                )
            )
            messages = [SystemMessage(content=system), HumanMessage(content=user), repair_msg]

    raise RuntimeError("Unreachable")
