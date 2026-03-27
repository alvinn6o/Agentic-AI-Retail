"""Deterministic control review for regulated and safety-sensitive workflows."""

from __future__ import annotations

from backend.app.models.controls import ActionControlReview, ControlReviewReport, PolicyCitation
from backend.app.models.decisions import Action, Decision
from backend.app.models.run_context import RunContext

_RISK_ORDER = ["low", "medium", "high", "critical"]

_POLICY_MAP: dict[str, list[PolicyCitation]] = {
    "restock": [
        PolicyCitation(
            source="sop_restock_policy.md",
            control_id="RESTOCK_APPROVAL",
            summary="Large replenishment orders require manager or director sign-off.",
        ),
        PolicyCitation(
            source="sop_agent_change_control.md",
            control_id="REG_INV_RELEASE",
            summary="Only low-risk targeted inventory changes may auto-release.",
        ),
    ],
    "reorder": [
        PolicyCitation(
            source="sop_restock_policy.md",
            control_id="RESTOCK_APPROVAL",
            summary="Large replenishment orders require manager or director sign-off.",
        ),
        PolicyCitation(
            source="sop_agent_change_control.md",
            control_id="REG_INV_RELEASE",
            summary="Only low-risk targeted inventory changes may auto-release.",
        ),
    ],
    "markdown": [
        PolicyCitation(
            source="sop_markdown_policy.md",
            control_id="MARKDOWN_APPROVAL",
            summary="Customer-facing markdowns require approval based on discount tier.",
        ),
        PolicyCitation(
            source="sop_agent_change_control.md",
            control_id="REG_PRICE_REVIEW",
            summary="Customer-facing price changes require human approval before release.",
        ),
    ],
    "promo": [
        PolicyCitation(
            source="sop_markdown_policy.md",
            control_id="MARKDOWN_APPROVAL",
            summary="Customer-facing markdowns require approval based on discount tier.",
        ),
        PolicyCitation(
            source="sop_agent_change_control.md",
            control_id="REG_PRICE_REVIEW",
            summary="Customer-facing price changes require human approval before release.",
        ),
    ],
    "staffing": [
        PolicyCitation(
            source="sop_agent_change_control.md",
            control_id="REG_STAFF_REVIEW",
            summary="Staffing changes are operational changes and require human approval.",
        )
    ],
    "audit_returns": [
        PolicyCitation(
            source="sop_agent_change_control.md",
            control_id="REG_QA_ALLOWED",
            summary="Investigative quality checks may auto-release when targeted and low impact.",
        )
    ],
    "other": [
        PolicyCitation(
            source="sop_agent_change_control.md",
            control_id="REG_NON_STANDARD_BLOCK",
            summary="Non-standard actions are blocked until human review defines the procedure.",
        )
    ],
}


def _raise_risk(risk_tier: str) -> str:
    idx = _RISK_ORDER.index(risk_tier)
    return _RISK_ORDER[min(idx + 1, len(_RISK_ORDER) - 1)]


def _has_explicit_target(action: Action) -> bool:
    return bool((action.stock_code or "").strip() or (action.category or "").strip())


class ControlReviewService:
    def review(self, ctx: RunContext, decision: Decision) -> ControlReviewReport:
        action_reviews: list[ActionControlReview] = []
        auto_releasable_actions: list[int] = []
        approval_required_actions: list[int] = []
        blocked_actions: list[int] = []

        for idx, action in enumerate(decision.actions):
            review = self._review_action(ctx, action, idx)
            action_reviews.append(review)

            if review.execution_state == "auto_release":
                auto_releasable_actions.append(idx)
            elif review.execution_state == "hold_for_approval":
                approval_required_actions.append(idx)
            else:
                blocked_actions.append(idx)

        overall_state = "auto_release"
        if blocked_actions:
            overall_state = "blocked"
        elif approval_required_actions:
            overall_state = "approval_required"

        summary = self._build_summary(
            ctx.control_profile,
            len(auto_releasable_actions),
            len(approval_required_actions),
            len(blocked_actions),
        )

        return ControlReviewReport(
            run_id=ctx.run_id,
            as_of_date=ctx.as_of_date,
            mode=ctx.mode,
            control_profile=ctx.control_profile,
            overall_state=overall_state,
            summary=summary,
            action_reviews=action_reviews,
            auto_releasable_actions=auto_releasable_actions,
            approval_required_actions=approval_required_actions,
            blocked_actions=blocked_actions,
            requires_human_approval=bool(approval_required_actions),
        )

    def executable_actions(self, decision: Decision, review: ControlReviewReport | None) -> list[Action]:
        if review is None:
            return decision.actions
        return [decision.actions[idx] for idx in review.auto_releasable_actions]

    def _review_action(self, ctx: RunContext, action: Action, idx: int) -> ActionControlReview:
        action_type = action.action_type
        citations = list(_POLICY_MAP.get(action_type, _POLICY_MAP["other"]))
        family = {
            "restock": "inventory",
            "reorder": "inventory",
            "markdown": "pricing",
            "promo": "pricing",
            "staffing": "operations",
            "audit_returns": "quality",
            "other": "manual_review",
        }.get(action_type, "manual_review")

        risk_tier = "medium"
        approval_role = "none"
        execution_state = "auto_release"
        reasons: list[str] = []
        quantity = action.quantity or 0

        if action_type in {"restock", "reorder"}:
            risk_tier = "medium"
            if quantity > 500:
                risk_tier = "critical"
                approval_role = "director"
                execution_state = "hold_for_approval"
                reasons.append("Large inventory movement exceeds the director review threshold.")
            elif quantity > 100 or action.urgency == "high":
                risk_tier = "high"
                approval_role = "operations_manager"
                execution_state = "hold_for_approval"
                reasons.append("Inventory change exceeds the low-risk release window.")
            else:
                reasons.append("Targeted, low-volume inventory change is eligible for auto-release.")
        elif action_type in {"markdown", "promo"}:
            risk_tier = "high"
            approval_role = "category_manager"
            execution_state = "hold_for_approval"
            reasons.append("Customer-facing pricing changes require a human approval step.")
            if action.urgency == "high":
                approval_role = "operations_manager"
                reasons.append("High-urgency pricing changes escalate to operations manager review.")
        elif action_type == "staffing":
            risk_tier = "high"
            approval_role = "operations_manager"
            execution_state = "hold_for_approval"
            reasons.append("Staffing changes are operational changes and require human review.")
        elif action_type == "audit_returns":
            risk_tier = "low"
            reasons.append("Investigative quality checks may be released automatically.")
        else:
            risk_tier = "critical"
            approval_role = "manual_review_board"
            execution_state = "blocked"
            reasons.append("Non-standard action types are blocked until a human defines the procedure.")

        if family in {"inventory", "pricing", "quality"} and not _has_explicit_target(action):
            risk_tier = "critical"
            approval_role = "manual_review_board"
            execution_state = "blocked"
            reasons.append("Action lacks an explicit stock_code or category target.")

        if ctx.control_profile == "regulated":
            if family in {"inventory", "pricing", "operations"}:
                risk_tier = _raise_risk(risk_tier)
            reasons.append("Regulated profile applies stricter release thresholds.")

            if action_type in {"markdown", "promo", "staffing"} and execution_state != "blocked":
                execution_state = "hold_for_approval"
                approval_role = "operations_manager"
            elif action_type in {"restock", "reorder"}:
                if quantity <= 100 and action.urgency != "high" and _has_explicit_target(action):
                    approval_role = "none"
                    execution_state = "auto_release"
                    reasons.append("Targeted inventory change remains within regulated low-risk limits.")
                elif execution_state != "blocked":
                    approval_role = "operations_manager" if quantity <= 500 else "director"
                    execution_state = "hold_for_approval"
            elif action_type == "audit_returns" and execution_state != "blocked":
                risk_tier = "medium"
                reasons.append("Quality investigations remain executable but are tracked more closely.")
            elif execution_state != "blocked":
                execution_state = "blocked"

        return ActionControlReview(
            action_index=idx,
            action_type=action_type,
            stock_code=action.stock_code,
            category=action.category,
            description=action.description,
            control_family=family,
            risk_tier=risk_tier,
            approval_role=approval_role,
            execution_state=execution_state,
            reasons=reasons,
            policy_citations=citations,
        )

    def _build_summary(
        self,
        control_profile: str,
        auto_count: int,
        approval_count: int,
        blocked_count: int,
    ) -> str:
        return (
            f"Control profile '{control_profile}' released {auto_count} action(s), "
            f"held {approval_count} for approval, and blocked {blocked_count} for manual review."
        )
