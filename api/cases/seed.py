"""CASE demo data (Ghana). Idempotent; runs after ORD, PAY and GEO.

- Publishes the case templates for every line (and RPT's report templates, so reports can be built).
- Names Tenmina's own registry account on the Lands Commission partner (RUL-30) [demo value, TO VERIFY].
- Opens cases for the orders PAY's seed paid, then walks them into several states:
  Kofi's land case in progress (searches lodged, a site visit screened and assigned, a document request,
  messages, costs, a safety incident), a checked plot waiting to be accepted, an institution verification
  in progress and a contractor check finished. RPT's seed takes Ama's land case to a released report.
"""
import logging
from datetime import timedelta

from django.utils import timezone

from core.errors import DomainError

log = logging.getLogger(__name__)
REGISTRY_ACCOUNT = "TMN-LC-PORTAL-01"  # Tenmina's own Lands Commission portal account [demo value, TO VERIFY]


def ensure_case_templates(gh, admin):
    from administration.models import ConfigVersion
    from administration.services import create_config_version, publish_config_version

    from . import templates

    for line, content in templates.DEFAULT_TEMPLATES.items():
        cur = ConfigVersion.objects.filter(kind="case_template", country=gh, product_line=line,
                                           state="published").order_by("-version").first()
        ok = False
        if cur is not None:
            try:
                templates.validate(cur.content)
                ok = True
            except DomainError:
                ok = False
        if not ok:
            cv = create_config_version(kind="case_template", content=content, by=admin, country=gh, product_line=line,
                                       name=f"Ghana {templates.LINES[line]['name'].lower()} template")
            publish_config_version(cv, by=admin)


def ensure_registry_account(gh, admin):
    from administration.services import update_partner

    from .services import registry_partner

    p = registry_partner(gh)
    d = dict(p.details or {})
    if REGISTRY_ACCOUNT not in (d.get("tenmina_accounts") or []):
        d["tenmina_accounts"] = list(d.get("tenmina_accounts") or []) + [REGISTRY_ACCOUNT]
        d.setdefault("channels", ["online", "office"])
        update_partner(p, by=admin, details=d)
    return p


def _file(person, gh, name, kind="image/jpeg"):
    from evidence.services import store

    data = (b"\xff\xd8\xff\xe0" + f"demo {name}".encode()) if kind == "image/jpeg" else f"%PDF-1.4 {name}".encode()
    return store(data=data, country=gh, uploaded_by=person, content_type=kind, original_name=name)


def attach(task, person, gh, kind):
    from . import services

    ct = "image/jpeg" if services.PHOTO_KINDS.search(kind) else "application/pdf"
    services.attach_task_evidence(task, person, _file(person, gh, f"{task.case.reference}-{kind}", ct), kind)


def lodge_and_receive(case, cm, gh, *, receive=True, ref="LC/SRCH/2026/0001"):
    from . import services

    lodge = case.tasks.filter(search_kind="lodge").first()
    result = case.tasks.filter(search_kind="result").first()
    if not case.search_requests.exists():
        services.submit_search(case, cm, task=lodge or result, channel="online_portal",
                               tenmina_account_ref=REGISTRY_ACCOUNT, registry_reference=ref,
                               search_on="Plot and the seller's name")
    if lodge and lodge.status != "done":
        attach(lodge, cm, gh, "search_fee_receipt")
        services.complete_task(lodge, cm)
    sr = case.search_requests.first()
    if receive and sr.status == "submitted":
        ev = _file(cm, gh, f"{case.reference}-official-search-result.pdf", "application/pdf")
        services.record_result(sr, cm, evidence=ev, registry_result_date=timezone.localdate() - timedelta(days=1),
                               summary="No registered interest other than the vendor's. No caveat.")
    return sr


def run(ctx):
    from orders.models import Order

    from . import services
    from .models import Case

    gh, people = ctx["gh"], ctx["people"]
    admin, cm = people["admin"], people["cm"]
    ensure_case_templates(gh, admin)
    from reports.seed import ensure_report_templates

    ensure_report_templates(gh, admin)
    ensure_registry_account(gh, admin)
    services.grant_safety_read(admin, people["reviewer2"], reason="Safety lead for Ghana (demo)")

    # Cases for the orders PAY's seed paid while the templates were not yet published.
    for o in Order.objects.filter(status="paid", case_id__isnull=True, kind__in=["verification", "fresh_search",
                                                                                 "listing_verification"]):
        try:
            services.create_from_order(o.pk, actor=cm)
        except DomainError as exc:
            log.info("seed: order %s has no case yet: %s", o.reference, exc.detail)
    orders = ctx.get("orders", {})
    seeded = ctx.setdefault("cases", {})
    for key, o in orders.items():
        c = Case.objects.filter(order_id=o.pk).first()
        if c:
            seeded[key] = c

    kofi = seeded.get("kofi_land_offline_paid")
    if kofi is not None and kofi.status == "paid":
        _kofi_in_progress(kofi, gh, people)
    if kofi is not None:
        seeded["kofi_land_offline_paid"] = Case.objects.get(pk=kofi.pk)

    _line_cases(gh, people, seeded)


def _kofi_in_progress(case, gh, people):
    from . import services

    cm, runner, client = people["cm"], people["runner"], people["client2"]
    services.accept(case, cm)
    case.refresh_from_db()
    intake = case.tasks.get(step_key="intake")
    services.complete_task(intake, cm)
    lodge_and_receive(case, cm, gh, receive=False, ref="LC/SRCH/2026/0417")
    visit = case.tasks.get(step_key="site_visit")
    services.record_risk_screen(case, cm, task=visit, outcome="proceed", hazards="Busy road at the entrance.",
                                people_required=1)
    services.assign_task(visit, cm, assignee=runner)
    services.add_party(case, cm, role="seller", name="Esther Lartey", id_number="GHA-711000201-3")
    services.request_document(case, cm, title="Copy of the indenture from the seller",
                              description="A clear photo of every page is enough.",
                              due_on=timezone.localdate() + timedelta(days=5))
    services.post_message(case, client, "Hello. Can the surveyor also check where the access road will be?")
    services.post_message(case, cm, "Yes. The surveyor will note the access road in the survey section.")
    services.add_cost(case, actor=cm, item_type="fees", amount="120.00", currency="GHS",
                      description="Lands Commission search fee [demo]")
    services.add_cost(case, actor=cm, item_type="travel", amount="85.00", currency="GHS",
                      description="Runner transport to Dawhenya [demo]")
    services.log_safety_incident(actor=cm, country=gh, case=case, occurred_at=timezone.now() - timedelta(hours=3),
                                 severity="medium", narrative="Two men at the plot asked the runner to leave and "
                                                              "said the land is family land. No one was hurt.",
                                 location_note="Plot entrance")


def _line_cases(gh, people, seeded):
    from core.ids import uuid7

    from . import services
    from .models import Case

    cm, reviewer, client = people["cm"], people["reviewer"], people["client"]
    inst = Case.objects.filter(product_line="institution_verification", title__contains="Accra Academy").first()
    if inst is None:
        inst = services.open_case("institution_verification", gh, "institution", uuid7(), client=client, actor=cm,
                                  title="Institution verification: Accra Academy (demo)", case_manager=cm)
        t = inst.tasks.get(step_key="registration_check")
        attach(t, cm, gh, "registration_certificate")
        services.complete_task(t, cm)
    seeded["institution"] = inst
    con = Case.objects.filter(product_line="contractor_check", title__contains="Kobby Builders").first()
    if con is None:
        con = services.open_case("contractor_check", gh, "contractor", uuid7(), actor=cm, case_manager=cm,
                                 title="Contractor check: Kobby Builders (demo)")
        for t in con.tasks.filter(review_step=False).order_by("position"):
            if t.owner_role == "CM":
                for k in t.required_evidence:
                    attach(t, cm, gh, k)
                services.complete_task(t, cm)
            else:
                t.refresh_from_db()
                if t.site_visit:
                    services.record_risk_screen(con, cm, task=t, outcome="proceed", people_required=1)
                for k in t.required_evidence:
                    attach(t, cm, gh, k)
                services.complete_task(t, cm)
        services.decide_verification(con, reviewer, outcome="verified",
                                     note="Registered class D1K1 [demo]; past work seen.")
    seeded["contractor"] = con
