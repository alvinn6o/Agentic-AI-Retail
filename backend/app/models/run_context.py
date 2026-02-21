"""RunContext — shared across all agents in a single workflow run."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class RunContext(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    start_date: date
    as_of_date: date
    mode: Literal["bounded", "omniscient"]
    start_time: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        frozen = True
