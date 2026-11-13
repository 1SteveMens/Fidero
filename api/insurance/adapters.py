"""IF-11 insurer partners (ADR-10). Port `insurer`: how an application and a claim reach the insurer.

The fake behaves like the manual path: it records what was sent and returns
an insurer reference. The insurer's answers come back through the portal
(role IS) or, later, the insurer's own API through `/v1/hooks/insurer`.
"""
import hashlib
import json
import logging

from core.adapters import get_adapter

log = logging.getLogger("insurance")


class FakeInsurer:
    name = "fake_insurer"
    sent: list = []  # what was passed to the insurer, for tests and the demo

    def _ref(self, prefix, obj):
        return f"{prefix}-{str(obj.pk)[-8:].upper()}"

    def submit_application(self, application) -> dict:
        """Pass the application in the agreed format [TO VERIFY] (US-INS-002 AC1)."""
        doc = {"product": application.product.name, "insured": application.insured_family_member.full_name,
               "answers": application.answers, "route": application.premium_route}
        digest = hashlib.sha256(json.dumps(doc, sort_keys=True, default=str).encode()).hexdigest()
        type(self).sent.append(("application", str(application.pk), digest))
        log.info("application %s passed to %s", application.pk, application.insurer.name)
        return {"reference": self._ref("APP", application), "channel": self.name, "sha256": digest}

    def submit_claim(self, claim) -> dict:
        doc = {"policy": claim.policy.policy_number, "description": claim.description,
               "event_date": claim.event_date}
        digest = hashlib.sha256(json.dumps(doc, sort_keys=True, default=str).encode()).hexdigest()
        type(self).sent.append(("claim", str(claim.pk), digest))
        return {"reference": self._ref("CLM", claim), "channel": self.name, "sha256": digest}


def insurer_port(insurer=None):
    if insurer is not None and insurer.adapter_path:
        from django.utils.module_loading import import_string

        return import_string(insurer.adapter_path)()
    return get_adapter("insurer", default="insurance.adapters.FakeInsurer")
