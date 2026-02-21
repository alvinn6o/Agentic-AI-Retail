"""WorkerAgent — converts manager decisions into executable task lists."""

from __future__ import annotations

import json
import uuid

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import TypeAdapter

from backend.app.agents.base import build_llm, load_prompt
from backend.app.core.config import Settings, get_settings
from backend.app.core.logging import get_logger
from backend.app.models.decisions import Decision, WorkerTask
from backend.app.models.run_context import RunContext

logger = get_logger(__name__)

_WORKER_LIST_ADAPTER = TypeAdapter(list[WorkerTask])


class WorkerAgent:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.llm = build_llm(self.settings)

    def run(self, ctx: RunContext, decision: Decision) -> list[WorkerTask]:
        logger.info("worker_agent.start", run_id=ctx.run_id, num_actions=len(decision.actions))

        prompt = load_prompt("worker")
        user_msg = prompt["user"].format(
            decision_json=decision.model_dump_json(indent=2),
            run_id=ctx.run_id,
            as_of_date=ctx.as_of_date,
        )

        messages = [
            SystemMessage(content=prompt["system"]),
            HumanMessage(content=user_msg),
        ]

        for attempt in range(self.settings.max_repair_retries):
            response = self.llm.invoke(messages)
            raw = response.content

            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()

            try:
                tasks = _WORKER_LIST_ADAPTER.validate_json(raw)
                # Stamp run_id and guarantee a task_id on every task.
                # Uses model_copy so the update is safe regardless of model config.
                tasks = [
                    task.model_copy(update={
                        "run_id": ctx.run_id,
                        "task_id": task.task_id or str(uuid.uuid4()),
                    })
                    for task in tasks
                ]
                logger.info("worker_agent.done", run_id=ctx.run_id, num_tasks=len(tasks))
                return tasks
            except Exception as exc:
                logger.warning("worker_agent.parse_failed", attempt=attempt + 1, error=str(exc)[:200])
                if attempt + 1 >= self.settings.max_repair_retries:
                    raise
                messages.append(HumanMessage(
                    content=(
                        f"Parse error: {exc}\n\n"
                        "Fix the errors above and return ONLY a valid JSON array. "
                        "Every object must include: assigned_to, action_type, title, description, priority. "
                        "No markdown, no explanation."
                    )
                ))

        return []
