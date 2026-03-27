# Agentic Change Control SOP

## Scope
- Applies when the workflow runs with the `regulated` control profile
- Covers agent-generated inventory, pricing, staffing, and quality actions before release to operational systems

## Release Rules
- Only targeted actions with an explicit `stock_code` or `category` may be auto-released
- Customer-facing price changes must be held for human approval before release
- Non-standard `other` actions are blocked until a human defines the procedure and approves it
- If the downstream audit contains any error finding, no tasks may be exported to enterprise systems

## Inventory Escalation
- Inventory changes of 100 units or fewer may auto-release when targeted and not high urgency
- Inventory changes above 100 units require operations manager approval
- Inventory changes above 500 units require director approval

## Operational Escalation
- Staffing changes require operations manager approval
- Investigative quality checks may auto-release, but remain logged as controlled actions

## Evidence Requirements
- Every released task must retain the originating `run_id`, approval state, and acceptance criteria in the outbound payload
