"""Tests for control review and enterprise dispatch services."""

from __future__ import annotations

from datetime import date

from backend.app.core.config import Settings
from backend.app.models.audit import AuditFinding, AuditReport
from backend.app.models.decisions import Action, Decision, WorkerTask
from backend.app.models.run_context import RunContext
from backend.app.services.control_review import ControlReviewService
from backend.app.services.enterprise_dispatch import EnterpriseDispatchService

RUN_ID = "test-run-00000000"
AS_OF = date(2011, 6, 30)
START = date(2011, 4, 1)


def _make_ctx(control_profile: str = "standard") -> RunContext:
    return RunContext(
        run_id=RUN_ID,
        start_date=START,
        as_of_date=AS_OF,
        mode="bounded",
        control_profile=control_profile,  # type: ignore[arg-type]
    )


def _make_decision(actions: list[Action]) -> Decision:
    return Decision(
        run_id=RUN_ID,
        as_of_date=AS_OF,
        mode="bounded",
        rationale="Based on the KPI and demand evidence.",
        confidence=0.8,
        actions=actions,
    )


def _make_task() -> WorkerTask:
    return WorkerTask(
        run_id=RUN_ID,
        task_id="task-123",
        assigned_to="warehouse_team",
        action_type="restock",
        title="Restock SKU1",
        description="Restock the validated SKU1 replenishment order.",
        priority="medium",
        acceptance_criteria=["Order submitted to approved supplier"],
    )


def _make_audit(passed: bool = True) -> AuditReport:
    findings = []
    if not passed:
        findings = [
            AuditFinding(
                run_id=RUN_ID,
                as_of_date=AS_OF,
                severity="error",
                finding_type="policy_violation",
                description="Critical audit failure",
            )
        ]
    return AuditReport(
        run_id=RUN_ID,
        as_of_date=AS_OF,
        mode="bounded",
        findings=findings,
        summary="audit summary",
    )


class TestControlReviewService:
    def test_standard_profile_auto_releases_low_risk_inventory_change(self) -> None:
        decision = _make_decision(
            [
                Action(
                    action_type="restock",
                    stock_code="SKU1",
                    description="Restock the validated top seller.",
                    quantity=50,
                )
            ]
        )

        review = ControlReviewService().review(_make_ctx("standard"), decision)

        assert review.overall_state == "auto_release"
        assert review.auto_releasable_actions == [0]
        assert review.approval_required_actions == []

    def test_regulated_profile_blocks_untargeted_pricing_change(self) -> None:
        decision = _make_decision(
            [
                Action(
                    action_type="promo",
                    description="Launch a broad promotional push.",
                    urgency="high",
                )
            ]
        )

        review = ControlReviewService().review(_make_ctx("regulated"), decision)

        assert review.overall_state == "blocked"
        assert review.blocked_actions == [0]
        assert review.action_reviews[0].approval_role == "manual_review_board"

    def test_regulated_profile_holds_large_reorder_for_approval(self) -> None:
        decision = _make_decision(
            [
                Action(
                    action_type="reorder",
                    stock_code="SKU2",
                    description="Place a larger supplier order for SKU2.",
                    quantity=200,
                )
            ]
        )

        review = ControlReviewService().review(_make_ctx("regulated"), decision)

        assert review.overall_state == "approval_required"
        assert review.approval_required_actions == [0]
        assert review.action_reviews[0].approval_role == "operations_manager"


class TestEnterpriseDispatchService:
    def test_dispatch_blocks_when_audit_fails(self) -> None:
        service = EnterpriseDispatchService(Settings(enterprise_dry_run=True))
        report = service.dispatch(
            _make_ctx("regulated"),
            control_review=None,
            audit_report=_make_audit(passed=False),
            worker_tasks=[_make_task()],
        )

        assert report.status == "blocked"
        assert "audit" in report.summary.lower()

    def test_dispatch_returns_dry_run_records_for_released_tasks(self) -> None:
        settings = Settings(
            enterprise_dry_run=True,
            enterprise_target_system="jira",
            enterprise_api_base_url="https://example.internal",
        )
        service = EnterpriseDispatchService(settings)
        review = ControlReviewService().review(
            _make_ctx("regulated"),
            _make_decision(
                [
                    Action(
                        action_type="restock",
                        stock_code="SKU1",
                        description="Restock the validated top seller.",
                        quantity=50,
                    )
                ]
            ),
        )

        report = service.dispatch(
            _make_ctx("regulated"),
            control_review=review,
            audit_report=_make_audit(passed=True),
            worker_tasks=[_make_task()],
        )

        assert report.status == "dry_run"
        assert len(report.records) == 1
        assert report.records[0].status == "dry_run"
        assert report.records[0].target_system == "jira"
