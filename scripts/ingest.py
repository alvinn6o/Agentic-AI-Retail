#!/usr/bin/env python3
"""Ingest raw CSV into DuckDB curated layer."""

import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.app.agents.data_engineer_agent import DataEngineerAgent
from backend.app.core.config import get_settings
from backend.app.core.logging import configure_logging, get_logger
from backend.app.models.run_context import RunContext
from datetime import date

configure_logging()
logger = get_logger(__name__)


def main() -> None:
    settings = get_settings()
    agent = DataEngineerAgent(settings)
    ctx = RunContext(as_of_date=date.today(), mode="omniscient")
    summary = agent.ingest(ctx)
    logger.info("ingest.complete", **{k: v for k, v in summary.items() if k != "validation_findings"})
    if summary["validation_findings"]:
        logger.warning("ingest.validation_findings", count=len(summary["validation_findings"]))
        for finding in summary["validation_findings"]:
            logger.warning("finding", **finding)


if __name__ == "__main__":
    main()
