"""CARE ports (ADR-10). Each has a fake or manual adapter so the line runs before any integration.

- care_oncall_pager: pages the on-call reviewer for an urgent concern (FR-CARE-006, 02 7.12
  care.route_concerns). The console adapter logs the page and raises an audit alert, which is
  the manual path: the on-call reviewer watches the alert list.
"""
import logging

log = logging.getLogger("tenmina.care")


class ConsolePager:
    def page(self, *, country, summary, concern_id=None) -> dict:
        from audit.services import raise_alert

        log.warning("PAGE on-call reviewer (%s): %s", getattr(country, "code", country), summary)
        try:
            raise_alert("care.urgent_concern", severity="high", summary=summary, entity="care_concern",
                        entity_id=str(concern_id or ""), country=country)
        except Exception:  # noqa: BLE001 - a page never blocks the concern being stored
            log.exception("could not raise the alert for an urgent concern")
        return {"paged": True, "channel": "console"}
