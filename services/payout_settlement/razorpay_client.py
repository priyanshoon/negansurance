"""Real Razorpay client with exponential backoff retry."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Any

import razorpay
from razorpay.errors import BadRequestError, GatewayError, ServerError


class RazorpayRetryError(Exception):
    """Raised when Razorpay operations fail after max retries."""

    pass


RazorpayError = (BadRequestError, GatewayError, ServerError)

logger = logging.getLogger(__name__)


@dataclass
class PayoutResponse:
    payout_id: str
    status: str
    amount: int
    destination: str
    reference: str
    initiated_at: str
    completed_at: str | None = None


class RazorpayClient:
    """Real Razorpay client with exponential backoff retry."""

    MAX_RETRIES = 3
    BASE_DELAY = 1.0

    RAZORPAY_SANDBOX_ACCOUNT = "7878780083036318"

    def __init__(
        self,
        key_id: str | None = None,
        key_secret: str | None = None,
    ) -> None:
        self._key_id = key_id or os.getenv("RAZORPAY_KEY_ID", "")
        self._key_secret = key_secret or os.getenv("RAZORPAY_KEY_SECRET", "")

        if not self._key_id or not self._key_secret:
            logger.warning(
                "Razorpay credentials not configured. Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET"
            )

        self._client = razorpay.Client(auth=(self._key_id, self._key_secret))
        self._fund_accounts: dict[str, str] = {}

    def _run_sync(self, func, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return loop.run_in_executor(None, partial(func, *args, **kwargs))

    async def initiate_payout(
        self,
        amount: int,
        destination: str,
        reference: str,
        partner_id: str = "",
    ) -> PayoutResponse:
        for attempt in range(self.MAX_RETRIES):
            try:
                contact_id = await self._run_sync(
                    self._get_or_create_contact, partner_id, reference
                )
                fund_account_id = await self._run_sync(
                    self._get_or_create_fund_account,
                    contact_id,
                    destination,
                    partner_id,
                )
                return await self._run_sync(
                    self._create_payout, fund_account_id, amount, reference
                )

            except RazorpayError as e:
                if attempt == self.MAX_RETRIES - 1:
                    logger.error(
                        "Razorpay payout failed after %d retries: %s",
                        self.MAX_RETRIES,
                        e,
                    )
                    raise RazorpayRetryError(f"Max retries exceeded: {e}") from e

                delay = self.BASE_DELAY * (2**attempt)
                logger.warning(
                    "Razorpay error (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1,
                    self.MAX_RETRIES,
                    delay,
                    e,
                )
                await asyncio.sleep(delay)

        raise RazorpayRetryError("Max retries exceeded")

    def _get_or_create_contact(self, partner_id: str, reference: str) -> dict[str, Any]:
        try:
            contact = self._client.contact.create(
                {
                    "name": f"Partner-{partner_id[:8]}"
                    if partner_id
                    else f"Partner-{reference[:8]}",
                    "email": f"partner-{partner_id[:8]}@test.com"
                    if partner_id
                    else f"{reference[:8]}@test.com",
                    "type": "vendor",
                    "reference_id": reference,
                }
            )
            logger.info("Created Razorpay contact: %s", contact["id"])
            return contact
        except RazorpayError as e:
            logger.warning("Failed to create contact, attempting to fetch: %s", e)
            contacts = self._client.contact.all({"reference_id": reference})
            if contacts.get("entities"):
                return contacts["entities"][0]
            raise

    def _get_or_create_fund_account(
        self, contact_id: dict[str, Any], destination: str, partner_id: str
    ) -> str:
        contact_id_str = (
            contact_id["id"] if isinstance(contact_id, dict) else contact_id
        )

        if partner_id and partner_id in self._fund_accounts:
            return self._fund_accounts[partner_id]

        try:
            account = self._client.fund_account.create(
                {
                    "contact_id": contact_id_str,
                    "account_type": "vpa",
                    "vpa": {
                        "address": destination,
                    },
                }
            )
            fund_account_id = account["id"]
            if partner_id:
                self._fund_accounts[partner_id] = fund_account_id
            logger.info("Created Razorpay fund account: %s", fund_account_id)
            return fund_account_id
        except RazorpayError as e:
            logger.warning("Failed to create fund account, attempting to fetch: %s", e)
            accounts = self._client.fund_account.all({"contact_id": contact_id_str})
            if accounts.get("entities"):
                fund_account_id = accounts["entities"][0]["id"]
                if partner_id:
                    self._fund_accounts[partner_id] = fund_account_id
                return fund_account_id
            raise

    def _create_payout(
        self,
        fund_account_id: str,
        amount: int,
        reference: str,
    ) -> PayoutResponse:
        payout = self._client.payout.create(
            {
                "account_number": self.RAZORPAY_SANDBOX_ACCOUNT,
                "fund_account_id": fund_account_id,
                "amount": amount,
                "currency": "INR",
                "mode": "UPI",
                "purpose": "refund",
                "reference_id": reference,
            }
        )

        logger.info(
            "Created Razorpay payout: %s, status: %s",
            payout["id"],
            payout["status"],
        )

        return PayoutResponse(
            payout_id=payout["id"],
            status=payout["status"],
            amount=payout["amount"],
            destination=fund_account_id,
            reference=reference,
            initiated_at=str(payout["created_at"]),
            completed_at=str(payout.get("completed_at"))
            if payout.get("completed_at")
            else None,
        )
