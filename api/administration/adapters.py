"""ADM ports. `fx_guide_source` gives the day's reference rate for the
exchange-rate guides (07.12 administration.refresh_fx). The fake returns
fixed working assumptions so the flow runs offline; they are not market data."""
from decimal import Decimal

# Working assumptions only, never shown as real rates [TO VERIFY].
FAKE_RATES = {("USD", "GHS"): Decimal("15.50"), ("GBP", "GHS"): Decimal("19.60"), ("EUR", "GHS"): Decimal("16.80"),
              ("USD", "NGN"): Decimal("1550.00"), ("GBP", "NGN"): Decimal("1960.00"),
              ("USD", "KES"): Decimal("129.00")}


class FakeGuideRateSource:
    name = "fake_reference"

    def rate(self, base: str, quote: str):
        return FAKE_RATES.get((base.upper(), quote.upper()))
