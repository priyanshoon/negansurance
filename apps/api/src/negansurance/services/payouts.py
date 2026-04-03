"""Payout orchestration service - delegates to settlement service."""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import load_dotenv

from ..domain import ClaimDecision, PayoutInstruction, PayoutStatus

logger = logging.getLogger(__name__)


def _resolve_repo_root() -> Path:
    current = Path(__file__).resolve()
    for candidate in current.parents:
        if (candidate / ".git").exists() or (candidate / "pyproject.toml").exists():
            return candidate
    return current.parents[-1]


REPO_ROOT = _resolve_repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

load_dotenv(REPO_ROOT / ".env")


class PayoutService:
    def __init__(self) -> None:
        from services.payout_settlement import SettlementService

        self._settlement = SettlementService()
        self._payouts: dict[str, PayoutInstruction] = {}

    async def enqueue(
        self, decision: ClaimDecision, destination_handle: str
    ) -> PayoutInstruction:
        from services.payout_settlement import SettlementRequest

        request = SettlementRequest(
            claim_id=decision.claim_id,
            policy_id=decision.policy_id,
            partner_id=decision.user_info.partner_id if decision.user_info else "",
            payout_amount=decision.payout_amount,
            destination_handle=destination_handle,
            recommended_action=decision.recommended_action or "auto_deny",
        )

        result = await self._settlement.process(request)

        instruction = PayoutInstruction(
            claim_id=result.claim_id,
            payout_reference=result.razorpay_reference or f"PYT-{result.settlement_id}",
            destination_handle=destination_handle,
            amount=result.amount,
            status=self._map_status(result.status),
            initiated_at=result.initiated_at,
            settled_at=result.settled_at,
        )
        self._payouts[decision.claim_id] = instruction
        logger.info(
            "Payout enqueued for claim %s: status=%s, amount=%.2f",
            decision.claim_id,
            instruction.status.value,
            instruction.amount,
        )
        return instruction

    def get(self, claim_id: str) -> PayoutInstruction | None:
        return self._payouts.get(claim_id)

    @staticmethod
    def _map_status(status: "SettlementStatus") -> PayoutStatus:
        mapping = {
            "pending": PayoutStatus.queued,
            "processing": PayoutStatus.processing,
            "settled": PayoutStatus.settled,
            "failed": PayoutStatus.failed,
        }
        return mapping.get(status.value, PayoutStatus.failed)
