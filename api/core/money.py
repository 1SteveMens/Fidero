"""Money as numeric(18,2) plus an ISO 4217 code. Never floating point (6.1)."""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.db import models
from rest_framework import serializers

TWOPLACES = Decimal("0.01")


def amount_field(**kw):
    return models.DecimalField(max_digits=18, decimal_places=2, **kw)


def currency_field(**kw):
    return models.CharField(max_length=3, **kw)


def q(value) -> Decimal:
    return Decimal(str(value)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self):
        object.__setattr__(self, "amount", q(self.amount))
        object.__setattr__(self, "currency", self.currency.upper())

    def __add__(self, other: "Money") -> "Money":
        self._same(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._same(other)
        return Money(self.amount - other.amount, self.currency)

    def _same(self, other):
        if self.currency != other.currency:
            raise ValueError(f"Currency mismatch: {self.currency} and {other.currency}")

    def as_dict(self):
        return {"amount": f"{self.amount:.2f}", "currency": self.currency}


class MoneyField(serializers.Field):
    """Serialises `<prefix>_amount` and `<prefix>_currency` model fields as
    {"amount": "250.00", "currency": "USD"} (7.1).

    Usage: price = MoneyField(prefix="price")
    """

    def __init__(self, prefix, **kw):
        self.prefix = prefix
        kw.setdefault("source", "*")
        super().__init__(**kw)

    def to_representation(self, obj):
        amount = getattr(obj, f"{self.prefix}_amount", None)
        if amount is None:
            return None
        return {"amount": f"{Decimal(amount):.2f}", "currency": getattr(obj, f"{self.prefix}_currency")}

    def to_internal_value(self, data):
        try:
            amount = q(data["amount"])
            currency = str(data["currency"]).upper()
        except Exception as exc:  # noqa: BLE001
            raise serializers.ValidationError('Use {"amount": "250.00", "currency": "USD"}.') from exc
        if len(currency) != 3:
            raise serializers.ValidationError("Currency must be an ISO 4217 code.")
        if amount < 0:
            raise serializers.ValidationError("Amount cannot be negative.")
        return {f"{self.prefix}_amount": amount, f"{self.prefix}_currency": currency}
