import uuid
from copy import deepcopy

import pytest
from yookassa.domain.response import PaymentResponse

from apps.payments import gateway


class FakeYooKassa:
    def __init__(self):
        self.payments = {}
        self.keys = {}
        self.created = []
        self.fail = False

    def _check(self):
        if self.fail:
            raise ConnectionError("ЮKassa недоступна")

    def create(self, params, idempotency_key=None):
        self._check()
        self.created.append((deepcopy(params), idempotency_key))
        if idempotency_key in self.keys:
            return self.find_one(self.keys[idempotency_key])
        payment_id = str(uuid.uuid4())
        self.keys[idempotency_key] = payment_id
        self.payments[payment_id] = {
            "id": payment_id,
            "status": "pending",
            "paid": False,
            "amount": params["amount"],
            "description": params["description"],
            "confirmation": {
                "type": "redirect",
                "confirmation_url": f"https://yoomoney.ru/checkout/payments/v2/contract?orderId={payment_id}",
            },
            "created_at": "2026-11-03T10:00:00.000Z",
            "metadata": params["metadata"],
            "recipient": {"account_id": "123456", "gateway_id": "1"},
            "refundable": False,
            "test": True,
        }
        return PaymentResponse(self.payments[payment_id])

    def find_one(self, payment_id):
        self._check()
        return PaymentResponse(self.payments[payment_id])

    def succeed(self, payment_id):
        self.payments[payment_id].update(status="succeeded", paid=True)

    def cancel(self, payment_id, reason="general_decline"):
        self.payments[payment_id].update(
            status="canceled",
            cancellation_details={"party": "payment_network", "reason": reason},
        )


@pytest.fixture
def yookassa(monkeypatch):
    fake = FakeYooKassa()
    monkeypatch.setattr(gateway, "YooPayment", fake)
    return fake
