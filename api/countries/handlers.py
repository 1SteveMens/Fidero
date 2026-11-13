"""CTY event handlers. Idempotent: each acts only while its object waits."""
from django.db import transaction

from core.events import subscribe
from core.models import ApprovalRequest

from . import services
from .models import Country, CountryConfig


def _approvers(req):
    return [a.approver for a in req.approvals.filter(decision="approve").select_related("approver")]


@subscribe("approval.approved")
def on_approved(ev):
    st = ev.payload.get("subject_type")
    if st not in ("country_config_publish", "country_activation"):
        return
    req = ApprovalRequest.objects.get(pk=ev.payload.get("request_id") or ev.aggregate_id)
    with transaction.atomic():
        if st == "country_config_publish":
            cfg = CountryConfig.objects.filter(pk=req.subject_id).first()
            if cfg:
                services._publish(cfg, _approvers(req))
        else:
            c = Country.objects.filter(pk=req.subject_id).first()
            if c:
                services._activate(c, req, _approvers(req))


@subscribe("approval.rejected", "approval.withdrawn")
def on_rejected(ev):
    from core import state

    if ev.payload.get("subject_type") == "country_config_publish":
        cfg = CountryConfig.objects.filter(pk=ev.payload.get("subject_id"), status="pending_approval").first()
        if cfg:
            state.transition(cfg, "country_config", "draft", reason="Publication was rejected or withdrawn")


@subscribe("config.published")
def on_config_published(ev):
    """ADR-11: a published country configuration keeps the versions it names.
    Log when a newer version of a referenced item is published, so an
    administrator can draft a new country configuration that uses it."""
    from audit.services import record

    code = ev.payload.get("country")
    kind = ev.payload.get("kind")
    if not code or not kind:
        return
    c = Country.objects.filter(code=code).first()
    if not c:
        return
    current = c.configs.filter(status="published").order_by("-version").first()
    versions = ((current.data if current else {}).get("refs") or {}).get("config_versions", {})
    line = ev.payload.get("product_line") or ""
    used = versions.get(f"{kind}:{line}")
    if used is None and versions.get(kind):
        from administration.models import ConfigVersion

        named = ConfigVersion.objects.filter(pk=versions[kind]).first()
        used = versions[kind] if named is None or named.product_line == line else None
    if used and str(used) != str(ev.payload.get("config_version_id")):
        record(action="country_config.refs_outdated", entity="country_config", entity_id=current.pk, country=c,
               data={"kind": kind, "uses": used, "newer": ev.payload.get("config_version_id")})


@subscribe("person.registered")
def on_person_registered(ev):
    """ADR-16: add the new sign-in to the routing directory as a blind index."""
    from accounts.models import Person

    p = Person.objects.filter(pk=ev.payload.get("person_id")).select_related("home_country").first()
    if p:
        services.register_signin(p.email, p.home_country)
