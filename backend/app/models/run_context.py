"""RunContext — shared across all agents in a single workflow run."""

import uuid
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RunContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    start_date: date
    as_of_date: date
    mode: Literal["bounded", "omniscient"]
    control_profile: Literal["standard", "regulated"] = "standard"
    start_time: datetime = Field(default_factory=lambda: datetime.now(UTC))
