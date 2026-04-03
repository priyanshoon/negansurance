# Payout Settlement Service

Handles payout execution after a claim has been approved. Uses Razorpay to process actual fund transfers to partners.

## Pipeline

```
ClaimDecision (approved)
         ↓
PayoutService.enqueue()
         ↓
SettlementService.process()
         ↓
RazorpayClient.initiate_payout()
         ↓
Fund Transfer (UPI/Bank)
```

## Flow

1. **Action routing** – SettlementService checks `recommended_action`:
   - `auto_deny` → immediately mark as failed
   - `manual_review` → queue for manual review (pending)
   - `auto_pay` → proceed to Razorpay payout

2. **Razorpay flow** – For approved payouts:
   - Create/fetch contact (partner identifier)
   - Create/fetch fund account (UPI address)
   - Create payout via Razorpay API

3. **Result mapping** – SettlementResult → PayoutInstruction for API response

## Quick Start

```python
from datetime import datetime

from services.payout_settlement import (
    SettlementService,
    SettlementRequest,
    SettlementStatus,
)

service = SettlementService()

# Process an approved claim payout
request = SettlementRequest(
    claim_id="CLM-12345",
    policy_id="POL-001",
    partner_id="partner-99",
    payout_amount=500.00,
    destination_handle="abc@upi",
    recommended_action="auto_pay",
)

result = await service.process(request)

print(result.status, result.settlement_id, result.razorpay_reference)
# Output: settled STL-ABC123 XYZ-PAYOUT-789
```

## Components

| Module | Responsibility |
|--------|----------------|
| `settlement.py` | Main orchestrator - routes by action, handles results |
| `razorpay_client.py` | Razorpay API wrapper with retry logic |
| `models.py` | SettlementRequest, SettlementResult, SettlementStatus |

## Retry Logic

The Razorpay client uses exponential backoff:
- 3 max retries
- Base delay: 1s, then 2s, then 4s
- Retries on `BadRequestError`, `GatewayError`, `ServerError`

## Configuration

```bash
RAZORPAY_KEY_ID=your_key_id
RAZORPAY_KEY_SECRET=your_key_secret
```

If not set, the client logs a warning and continues (useful for testing).

## Operational Notes

- Fund accounts are cached per `partner_id` to avoid redundant Razorpay calls
- Payouts use sandbox account (`7878780083036318`) for testing
- All blocking Razorpay SDK calls run in executor to avoid blocking event loop
- Failed payouts include `failure_reason` for debugging