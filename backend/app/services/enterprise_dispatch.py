"""Enterprise-system dispatch with deterministic release conditions."""

from __future__ import annotations

from typing import Any

import httpx

from backend.app.core.config import Settings, get_settings
from backend.app.core.logging import get_logger
from backend.app.models.audit import AuditReport
from backend.app.models.controls import ControlReviewReport
from backend.app.models.decisions import WorkerTask
from backend.app.models.integration import DispatchRecord, DispatchReport
from backend.app.models.run_context import RunContext

logger = get_logger(__name__)


class EnterpriseDispatchService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def dispatch(
        self,
        ctx: RunContext,
        control_review: ControlReviewReport | None,
        audit_report: AuditReport | None,
        worker_tasks: list[WorkerTask] | None,
    ) -> DispatchReport:
        target_system = self.settings.enterprise_target_system
        tasks = worker_tasks or []

        if audit_report is None:
            return DispatchReport(
                run_id=ctx.run_id,
                as_of_date=ctx.as_of_date,
                control_profile=ctx.control_profile,
                target_system=target_system,
                status="blocked",
                summary="Dispatch blocked because no audit artifact was available.",
            )

        if not audit_report.passed:
            return DispatchReport(
                run_id=ctx.run_id,
                as_of_date=ctx.as_of_date,
                control_profile=ctx.control_profile,
                target_system=target_system,
                status="blocked",
                summary="Dispatch blocked because the audit reported error-level findings.",
            )

        if not tasks:
            status = "approval_required" if control_review and control_review.requires_human_approval else "skipped"
            summary = (
                "No executable tasks were released because actions are waiting for approval."
                if status == "approval_required"
                else "No worker tasks were generated for enterprise dispatch."
            )
            return DispatchReport(
                run_id=ctx.run_id,
                as_of_date=ctx.as_of_date,
                control_profile=ctx.control_profile,
                target_system=target_system,
                status=status,
                summary=summary,
            )

        base_url = self.settings.enterprise_api_base_url.rstrip("/")
        endpoint = f"{base_url}{self.settings.enterprise_task_endpoint}" if base_url else ""
        records: list[DispatchRecord] = []

        if self.settings.enterprise_dry_run or not endpoint:
            dry_run_mode = self.settings.enterprise_dry_run
            status = "dry_run" if dry_run_mode else "not_configured"
            for task in tasks:
                payload = self._build_payload(ctx, task)
                records.append(
                    DispatchRecord(
                        task_id=task.task_id,
                        assigned_to=task.assigned_to,
                        title=task.title,
                        target_system=target_system,
                        endpoint=endpoint or "<not-configured>",
                        status="dry_run" if dry_run_mode else "skipped",
                        reason="Prepared but not sent because dispatch is running in dry-run mode."
                        if dry_run_mode
                        else "Prepared but not sent because no enterprise endpoint is configured.",
                        payload=payload,
                    )
                )
            return DispatchReport(
                run_id=ctx.run_id,
                as_of_date=ctx.as_of_date,
                control_profile=ctx.control_profile,
                target_system=target_system,
                status=status,
                summary=f"Prepared {len(records)} task payload(s) for {target_system}.",
                records=records,
            )

        headers = {"Content-Type": "application/json"}
        if self.settings.enterprise_api_key:
            headers["Authorization"] = f"Bearer {self.settings.enterprise_api_key}"

        for task in tasks:
            payload = self._build_payload(ctx, task)
            try:
                response = httpx.post(
                    endpoint,
                    json=payload,
                    headers=headers,
                    timeout=self.settings.enterprise_api_timeout_seconds,
                )
                response.raise_for_status()
                response_body: dict[str, Any]
                try:
                    response_body = response.json()
                except ValueError:
                    response_body = {"text": response.text[:500]}
                records.append(
                    DispatchRecord(
                        task_id=task.task_id,
                        assigned_to=task.assigned_to,
                        title=task.title,
                        target_system=target_system,
                        endpoint=endpoint,
                        status="dispatched",
                        external_id=str(
                            response_body.get("id")
                            or response_body.get("ticket_id")
                            or response_body.get("record_id")
                            or ""
                        ),
                        payload=payload,
                        response_body=response_body,
                    )
                )
            except Exception as exc:
                logger.error("dispatch.failed", task_id=task.task_id, error=str(exc))
                records.append(
                    DispatchRecord(
                        task_id=task.task_id,
                        assigned_to=task.assigned_to,
                        title=task.title,
                        target_system=target_system,
                        endpoint=endpoint,
                        status="failed",
                        reason=str(exc),
                        payload=payload,
                    )
                )

        overall_status = "dispatched" if all(r.status == "dispatched" for r in records) else "failed"
        return DispatchReport(
            run_id=ctx.run_id,
            as_of_date=ctx.as_of_date,
            control_profile=ctx.control_profile,
            target_system=target_system,
            status=overall_status,
            summary=f"Attempted dispatch for {len(records)} task(s) to {target_system}.",
            records=records,
        )

    def _build_payload(self, ctx: RunContext, task: WorkerTask) -> dict[str, Any]:
        return {
            "run_id": ctx.run_id,
            "as_of_date": str(ctx.as_of_date),
            "control_profile": ctx.control_profile,
            "task_id": task.task_id,
            "assigned_to": task.assigned_to,
            "title": task.title,
            "description": task.description,
            "priority": task.priority,
            "due_date": task.due_date,
            "acceptance_criteria": task.acceptance_criteria,
            "metadata": task.metadata,
        }
