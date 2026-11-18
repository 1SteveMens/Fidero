"""CASE demo data (Ghana). Idempotent; runs after ORD, PAY and GEO.

- Publishes the case templates for every line (and RPT's report templates, so reports can be built).
- Names Tenmina's own registry account on the Lands Commission partner (RUL-30) [demo value, TO VERIFY].
- Opens cases for the orders PAY's seed paid, then walks them into several states:
  Kofi's land case in progress (searches lodged, a site visit screened and assigned, a document request,
  messages, costs, a safety incident) and a checked plot waiting to be accepted. RPT's seed takes Ama's land
  case to a released report. Institution verifications and contractor checks are opened by FEE's and BLD's seeds
  on their real institutions and panel members, so every case's subject is a real row.
- Late (`run_late`): gives the lawyer and the surveyor their field steps on Kofi's case and on BLD's off-plan
  check, so they have work in Tenmina Field.
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


def refresh_country_refs(gh, admin):
    """Point the country configuration at the templates now in force (FR-CTY-001).

    The administration seed publishes placeholder case and report templates and
    names them in the configuration; the CASE and RPT seeds replace them with
    templates in their own format, which retires the placeholders. A configuration
    naming a retired version could never be republished (publication_blockers),
    so name the replacements, as an administrator would."""
    import copy

    from administration.models import ConfigVersion
    from countries.services import seed_publish

    current = gh.configs.filter(status="published").order_by("-version").first()
    if current is None:
        return
    data = copy.deepcopy(current.data)
    versions = data.setdefault("refs", {}).setdefault("config_versions", {})
    changed = False
    for key, pk in list(versions.items()):
        cv = ConfigVersion.objects.filter(pk=pk).first()
        if cv is None or cv.state == "published":
            continue
        new = ConfigVersion.objects.filter(kind=cv.kind, country=gh, product_line=cv.product_line,
                                           state="published").order_by("-version").first()
        if new is not None:
            versions[key], changed = str(new.pk), True
    # Every case and report template in force, one reference per product line ("case_template:building"), so
    # the configuration names exactly what new work uses (FR-CTY-001, ADR-11). The plain kind keys stay for land.
    for cv in ConfigVersion.objects.filter(kind__in=("case_template", "report_template"), country=gh,
                                           state="published").order_by("kind", "product_line", "-version"):
        key = f"{cv.kind}:{cv.product_line}"
        newest = ConfigVersion.objects.filter(kind=cv.kind, country=gh, product_line=cv.product_line,
                                              state="published").order_by("-version").first()
        if versions.get(key) != str(newest.pk):
            versions[key], changed = str(newest.pk), True
    if changed:
        seed_publish(gh, data, by=admin)


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

    from core import samples

    data, kind, filename = samples.file_for(name, kind)
    return store(data=data, country=gh, uploaded_by=person, content_type=kind, original_name=filename)


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
    refresh_country_refs(gh, admin)
    ensure_registry_account(gh, admin)
    # Work goes only to a professional with an active agreement and a verified pay account (US-PRO-001 AC1):
    # PRO's agreements for the seeded professionals exist before any task is assigned below.
    from profpay.seed import ensure_agreements

    ensure_agreements(ctx)
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


def run_late(ctx):
    """Field work for the lawyer and the surveyor, on real case steps, assigned by the case manager (FR-CASE-003).
    Late, because BLD's seed opens the off-plan check:

    - Kofi's land case: the consent meeting goes to the lawyer; the boundary and overlay check to the surveyor,
      who also notes the access road Kofi asked about. It waits for the runner's site visit.
    - The off-plan check of Sunrise Homes: the lawyer checks title to the estate land (open) and the building
      permits, photographed at the assembly in Tenmina Field and sent (done)."""
    from .models import Case

    people = ctx["people"]
    cm, lawyer, surveyor = people["cm"], people.get("lawyer"), people.get("surveyor")
    if lawyer is None or surveyor is None:
        return
    kofi = (ctx.get("cases") or {}).get("kofi_land_offline_paid")
    if kofi is not None:
        kofi.refresh_from_db()
        if kofi.status == "in_progress":
            _assign(kofi, "consent_meeting", cm, lawyer)
            _assign(kofi, "overlay_check", cm, surveyor)
    offplan = Case.objects.filter(product_line="offplan_check", status="in_progress").order_by("created_at").first()
    if offplan is not None:
        _assign(offplan, "land_title_check", cm, lawyer)
        permit = _assign(offplan, "permit_check", cm, lawyer)
        if permit is not None and permit.status in ("open", "in_progress") and permit.assignee_id == lawyer.pk:
            _field_done(permit, lawyer, "permit_copy", "document", "Building permit, stamped by the assembly")


def _assign(case, step_key, cm, person):
    from . import services

    t = case.tasks.filter(step_key=step_key).first()
    if t is None or t.status not in ("open", "in_progress"):
        return t
    if t.assignee_id != person.pk:
        try:
            t = services.assign_task(t, cm, assignee=person)
        except DomainError as exc:
            log.info("seed: %s on %s not assigned: %s", step_key, case.reference, exc.detail)
    return t


def _field_done(task, person, key, scene, caption):
    """The professional photographs the evidence in Tenmina Field and sends it; CASE closes the step when the
    submission is clean (FR-CASE-006). The photo is signed by the phone and stored tamper-evident."""
    import uuid

    from core import samples
    from mobile.seed import _item, _phone
    from mobile.services import submit

    ns = uuid.UUID("9e0f6a52-3c1b-4f7e-8a2d-6b5c4d3e2f10")
    phone = _phone(person, f"case-{person.email}", platform="ios")
    m = _item(phone, str(uuid.uuid5(ns, f"{task.pk}-{key}")), "task", task.pk,
              samples.photo(scene, f"case-{task.pk}-{key}", caption=caption[:58], model=phone.model, make="Apple"),
              requirement_key=key, captured_at=timezone.now() - timedelta(hours=2))
    submit(person, client_submission_id=str(uuid.uuid5(ns, f"sub-{task.pk}")), subject_type="task",
           subject_id=task.pk, items=[{"requirement_key": key, "evidence_id": str(m.evidence_id)}],
           note="Permit seen at the assembly. Copy photographed.")
