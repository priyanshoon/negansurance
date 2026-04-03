"""Payout settlement service - processes settlements via Razorpay."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from .models import SettlementRequest, SettlementResult, SettlementStatus
from .razorpay_client import RazorpayClient, RazorpayRetryError

logger = logging.getLogger(__name__)


class SettlementService:
    def __init__(
        self,
        razorpay_client: RazorpayClient | None = None,
    ) -> None:
        self._razorpay = razorpay_client or RazorpayClient()
        self._settlements: dict[str, SettlementResult] = {}

    async def process(self, request: SettlementRequest) -> SettlementResult:
        settlement_id = f"STL-{uuid.uuid4().hex[:10].upper()}"
        initiated_at = datetime.utcnow()

        logger.info(
            "Processing settlement %s for claim %s, action: %s",
            settlement_id,
            request.claim_id,
            request.recommended_action,
        )

        if request.recommended_action == "auto_deny":
            return self._deny_settlement(
                settlement_id=settlement_id,
                claim_id=request.claim_id,
                amount=request.payout_amount,
                initiated_at=initiated_at,
                reason="blocked_by_fraud_engine",
            )

        if request.recommended_action == "manual_review":
            return self._queue_for_review(
                settlement_id=settlement_id,
                claim_id=request.claim_id,
                amount=request.payout_amount,
                initiated_at=initiated_at,
            )

        return await self._process_payout(
            settlement_id=settlement_id,
            claim_id=request.claim_id,
            amount=request.payout_amount,
            destination=request.destination_handle,
            partner_id=request.partner_id,
            initiated_at=initiated_at,
        )

    def _deny_settlement(
        self,
        settlement_id: str,
        claim_id: str,
        amount: float,
        initiated_at: datetime,
        reason: str,
    ) -> SettlementResult:
        result = SettlementResult(
            settlement_id=settlement_id,
            claim_id=claim_id,
            status=SettlementStatus.failed,
            amount=amount,
            initiated_at=initiated_at,
            settled_at=initiated_at,
            failure_reason=reason,
        )
        self._settlements[claim_id] = result
        logger.info("Settlement %s denied: %s", settlement_id, reason)
        return result

    def _queue_for_review(
        self,
        settlement_id: str,
        claim_id: str,
        amount: float,
        initiated_at: datetime,
    ) -> SettlementResult:
        result = SettlementResult(
            settlement_id=settlement_id,
            claim_id=claim_id,
            status=SettlementStatus.pending,
            amount=amount,
            initiated_at=initiated_at,
            failure_reason="manual_review_required",
        )
        self._settlements[claim_id] = result
        logger.info("Settlement %s queued for manual review", settlement_id)
        return result

    async def _process_payout(
        self,
        settlement_id: str,
        claim_id: str,
        amount: float,
        destination: str,
        partner_id: str,
        initiated_at: datetime,
    ) -> SettlementResult:
        amount_paise = int(amount * 100)

        try:
            razorpay_response = await self._razorpay.initiate_payout(
                amount=amount_paise,
                destination=destination,
                reference=settlement_id,
                partner_id=partner_id,
            )
        except RazorpayRetryError as e:
            logger.error("Settlement %s failed after retries: %s", settlement_id, e)
            result = SettlementResult(
                settlement_id=settlement_id,
                claim_id=claim_id,
                status=SettlementStatus.failed,
                amount=amount,
                initiated_at=initiated_at,
                settled_at=datetime.utcnow(),
                failure_reason=str(e),
            )
            self._settlements[claim_id] = result
            return result

        if razorpay_response.status == "processed":
            result = SettlementResult(
                settlement_id=settlement_id,
                claim_id=claim_id,
                status=SettlementStatus.settled,
                razorpay_reference=razorpay_response.payout_id,
                amount=amount,
                initiated_at=initiated_at,
                settled_at=datetime.utcnow(),
            )
            logger.info(
                "Settlement %s completed, razorpay: %s",
                settlement_id,
                razorpay_response.payout_id,
            )
        else:
            result = SettlementResult(
                settlement_id=settlement_id,
                claim_id=claim_id,
                status=SettlementStatus.failed,
                razorpay_reference=razorpay_response.payout_id,
                amount=amount,
                initiated_at=initiated_at,
                settled_at=datetime.utcnow(),
                failure_reason="razorpay_payout_failed",
            )
            logger.warning(
                "Settlement %s failed via razorpay: %s",
                settlement_id,
                razorpay_response.payout_id,
            )

        self._settlements[claim_id] = result
        return result

    def get(self, claim_id: str) -> SettlementResult | None:
        return self._settlements.get(claim_id)
