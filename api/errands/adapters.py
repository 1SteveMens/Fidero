"""TSK ports (ADR-10). Agencies and couriers have no integration yet: the manual path is the agent's signed
photos of acknowledgements, receipts and handovers in Tenmina Field, and the courier's tracking reference typed
in.

- errand_courier_tracking: turns a courier's tracking reference into a link the client can follow.
"""


class ManualCourierTracking:
    def tracking_url(self, courier_name: str, reference: str) -> str | None:
        return None  # no courier integration yet; the client sees the reference itself


def courier():
    from core.adapters import get_adapter

    return get_adapter("errand_courier_tracking", default="errands.adapters.ManualCourierTracking")
