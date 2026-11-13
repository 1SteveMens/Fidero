"""INS event subscribers and registry hooks. Idempotent."""
from accounts import home
from core.events import subscribe
from dataprotection import registry as dpr
from escrow import registry as esc_registry
from evidence import access


@subscribe("release.confirmed")
def on_release_confirmed(ev):
    from . import services

    services.on_release_confirmed(ev.payload or {})


@subscribe("release.withdrawn", "release.rejected", "release.rejected_by_bank")
def on_release_closed(ev):
    from . import services

    why = {"release.withdrawn": "the instruction was withdrawn", "release.rejected": "the payment was not approved",
           "release.rejected_by_bank": "the bank refused the payment"}[ev.topic]
    services.on_release_closed(ev.payload or {}, why)


@subscribe("payee.suspended", "payee.status_changed")
def on_payee(ev):
    from . import services

    p = ev.payload or {}
    to = p.get("to") or ("suspended" if ev.topic == "payee.suspended" else "")
    if p.get("payee_id") or p.get("id"):
        services.on_payee_status(p.get("payee_id") or p.get("id"), to)


def _premium_check(instruction):
    from . import services

    return services.release_check(instruction)


def _premium_label(subject_id):
    from .models import Premium

    pm = Premium.objects.filter(pk=subject_id).select_related("policy", "policy__insurer__partner").first()
    return f"Premium {pm.policy.policy_number}, {pm.policy.insurer.name}" if pm else ""


esc_registry.register_subject_check("premium", _premium_check)
esc_registry.subject_label("premium", _premium_label)


@home.register
def insurance_home_items(person):
    from .models import Application, Claim, Policy, Premium

    out = []
    if not person.has_tenmina_role("CL"):
        return out
    for app in Application.objects.filter(client=person, status__in=["draft", "submitted"]).select_related(
            "product", "insurer__partner"):
        out.append(home.item(kind="ins_application", id=app.pk, title=f"{app.product.name} application",
                             status=app.status, status_text="Sent to the insurer." if app.status == "submitted"
                             else "Not sent yet.", needs_action=app.status == "draft",
                             link=f"/insurance/applications/{app.pk}", family_member_id=app.insured_family_member_id,
                             line="ins"))
    for pol in Policy.objects.filter(client=person).exclude(status="cancelled").select_related("insurer__partner"):
        out.append(home.item(kind="ins_policy", id=pol.pk, title=f"{pol.insurer.name} policy {pol.policy_number}",
                             status=pol.status, status_text=(pol.status_note if pol.status == "lapsed" else
                                                             f"Renews on {pol.renews_on:%d %B %Y}. Claims: "
                                                             f"{pol.claim_contact}"),
                             next_date=pol.renews_on, link=f"/insurance/policies/{pol.pk}",
                             family_member_id=pol.insured_family_member_id, line="ins"))
    for pm in Premium.objects.filter(policy__client=person, status__in=["due", "overdue"],
                                     route="client_direct_to_insurer").select_related("policy__insurer__partner"):
        out.append(home.item(kind="ins_premium", id=pm.pk, title=f"Premium to {pm.policy.insurer.name}",
                             status=pm.status, status_text="Pay the insurer's own account, then tell us.",
                             next_date=pm.due_on, needs_action=True, link=f"/insurance/premiums/{pm.pk}", line="ins",
                             amount={"amount": f"{pm.amount:.2f}", "currency": pm.currency}))
    for c in Claim.objects.filter(policy__client=person).exclude(insurer_status__in=["paid", "declined"]) \
            .select_related("policy__insurer__partner"):
        out.append(home.item(kind="ins_claim", id=c.pk, title=f"Claim on {c.policy.policy_number}",
                             status=c.insurer_status or "sent",
                             status_text=f"{c.policy.insurer.name}: {(c.insurer_status or 'sent').replace('_', ' ')}.",
                             link=f"/insurance/claims/{c.pk}", line="ins"))
    return out


def _visible(selector):
    def can_view(user, sid):
        from . import selectors

        return getattr(selectors, selector)(user).filter(pk=sid).exists()

    return can_view


def _country(model_name):
    def get(sid):
        from . import models

        obj = getattr(models, model_name).objects.filter(pk=sid).select_related("country").first()
        return obj.country if obj else None

    return get


def _product_view(user, sid):
    from .models import Product

    return Product.objects.filter(pk=sid, status="published").exists()


def _claim_attach(user, sid):
    from .models import Claim
    from .services import insurer_ids_for

    c = Claim.objects.filter(pk=sid).select_related("policy").first()
    return c is not None and (c.policy.client_id == user.pk or c.policy.insurer_id in insurer_ids_for(user))


access.register("ins_product", can_view=_product_view, can_attach=lambda u, s: False, country=_country("Product"),
                owner=lambda sid: ("ins_product", sid))
access.register("ins_application", can_view=_visible("applications_visible"), can_attach=lambda u, s: False,
                country=_country("Application"), owner=lambda sid: ("ins_application", sid))
access.register("ins_policy", can_view=_visible("policies_visible"), can_attach=lambda u, s: False,
                country=_country("Policy"), owner=lambda sid: ("ins_policy", sid))
access.register("ins_premium", can_view=_visible("premiums_visible"), can_attach=_visible("premiums_visible"),
                country=_country("Premium"), owner=lambda sid: ("ins_premium", sid))
access.register("ins_claim", can_view=_visible("claims_visible"), can_attach=_claim_attach,
                country=_country("Claim"), owner=lambda sid: ("ins_claim", sid))


@dpr.open_matters
def insurance_open_matters(person):
    from .models import Premium

    return [{"kind": "ins_premium", "id": str(pm.pk), "title": f"Premium for {pm.policy.policy_number}",
             "reason": "The bank is paying a premium to the insurer."}
            for pm in Premium.objects.filter(policy__client=person, status="instructed").select_related("policy")]


@dpr.exporter("insurance")
def export_insurance(person):
    from .models import Application, Claim, Policy

    return {
        "applications": [{"id": str(a.pk), "product": a.product.name, "status": a.status, "answers": a.answers}
                         for a in Application.objects.filter(client=person).select_related("product")],
        "policies": [{"id": str(p.pk), "insurer": p.insurer.name, "policy_number": p.policy_number,
                      "renews_on": p.renews_on.isoformat(), "status": p.status}
                     for p in Policy.objects.filter(client=person).select_related("insurer__partner")],
        "claims": [{"id": str(c.pk), "policy_id": str(c.policy_id), "insurer_status": c.insurer_status,
                    "description": c.description} for c in Claim.objects.filter(policy__client=person)],
    }
