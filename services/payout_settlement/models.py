"""Settlement service domain models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class SettlementStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    settled = "settled"
    failed = "failed"


class SettlementRequest(BaseModel):
    claim_id: str
    policy_id: str
    partner_id: str
    payout_amount: float = Field(gt=0)
    destination_handle: str
    recommended_action: str


class SettlementResult(BaseModel):
    settlement_id: str
    claim_id: str
    status: SettlementStatus
    razorpay_reference: str | None = None
    amount: float
    initiated_at: datetime
    settled_at: datetime | None = None
    failure_reason: str | None = None
