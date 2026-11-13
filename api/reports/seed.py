"""RPT demo data (Ghana). Idempotent; runs after CASE's seed.

- Report templates for land and building (published from CASE's seed so reports can be built at once).
- Ama's land case taken through the whole of sequence 5.2: tasks done with evidence, the official search
  received from Tenmina's registry account, parties checked, sections written and signed, an amber verdict
  with three conditions, review, approval by the signing lawyer and a different reviewer, and release with a
  stored PDF and its SHA-256.
- A fresh search started on that plot, and this month's re-check draw.
"""
import logging

from django.utils import timezone

from core.errors import DomainError

log = logging.getLogger(__name__)


def ensure_report_templates(gh, admin):
    from administration.models import ConfigVersion
    from administration.services import create_config_version, publish_config_version

    from . import templates

    for line, content in templates.DEFAULT_TEMPLATES.items():
        cur = ConfigVersion.objects.filter(kind="report_template", country=gh, product_line=line,
                                           state="published").order_by("-version").first()
        ok = False
        if cur is not None:
            try:
                templates.layout(cur.content)
                ok = True
            except DomainError:
                ok = False
        if not ok:
            cv = create_config_version(kind="report_template", content=content, by=admin, country=gh,
                                       product_line=line, name=f"Ghana {line} report template (sections 1 to 14)")
            publish_config_version(cv, by=admin)


FINDINGS = {
    2: ("The plot can be bought once the three conditions in section 11 are met.", "amber"),
    3: ("Searches on the plot and the seller, a site visit, a survey and overlay checks, and the consent "
        "meeting.", None),
    4: ("The pillars found on site match the site plan within 0.5 m.", "green"),
    5: ("The official search from Tenmina's registry account shows no registered interest other than the "
        "vendor's and no caveat.", "green"),
    6: ("No overlap with neighbouring plots on the cadastral extract.", "green"),
    7: ("Clear of the road reserve, wetland and acquisition layers checked.", "green"),
    8: ("The family head confirmed the vendor may sell. Consent is promised and not yet signed by all heads.",
        "amber"),
    9: ("The chain from the family allocation to the vendor is complete.", "green"),
    10: ("Vacant. No structure. Access by an untarred road.", "green"),
    11: ("Proceed only through escrow, with the conditions below.", None),
    14: ("Appendices A to G are in the case evidence folder.", None),
}
CONDITIONS = [
    ("family_consent", "Signed consent of every family head recorded on video", "seller",
     "Consent form and video reference"),
    ("fresh_search", "Fresh official search within the window before release", "tenmina",
     "Official search result from Tenmina's registry account"),
    ("indenture_signed", "Indenture signed by the vendor and witnessed", "lawyer", "Signed indenture copy"),
]


def release_demo_case(case, gh, people, stop=None, parties=True):
    """Sequence 5.2 end to end with services. Used by the seed and by tests.
    stop="sections" returns the draft before verdict and signatures; stop="submit" the signed draft;
    stop="approve" the report in review."""
    from cases import services as cs
    from cases.seed import attach, lodge_and_receive

    from . import services
    from .models import Report

    cm, lawyer, surveyor, runner = people["cm"], people["lawyer"], people["surveyor"], people["runner"]
    reviewer = people["reviewer"]
    if case.status == "paid":
        cs.accept(case, cm)
    case.refresh_from_db()
    t = {x.step_key: x for x in case.tasks.all()}
    if t["intake"].status != "done":
        cs.complete_task(t["intake"], cm)
    lodge_and_receive(case, cm, gh)
    visit = t["site_visit"]
    if visit.status != "done":
        cs.record_risk_screen(case, cm, task=visit, outcome="proceed", people_required=1)
        visit = cs.assign_task(visit, cm, assignee=runner)
        for k in visit.required_evidence:
            attach(visit, runner, gh, k)
        cs.complete_task(visit, runner)
    for key, who in (("overlay_check", surveyor), ("consent_meeting", lawyer), ("legal_review", lawyer)):
        task = case.tasks.get(step_key=key)
        if task.status == "done":
            continue
        if task.assignee_id is None:
            task = cs.assign_task(task, cm, assignee=who)
        for k in task.required_evidence:
            attach(task, who, gh, k)
        cs.complete_task(task, who)
    for n, name in ((1, "seller"), (2, "grantor")) if parties else ():
        if not case.parties.filter(role=name).exists():
            number = f"GHA-720{case.reference[-5:]}{n}-{n}"
            cs.add_party(case, cm, role=name, name=f"Demo {name.capitalize()} {case.reference[-3:]}",
                         id_number=number)
    report = Report.objects.filter(case=case).order_by("-version").first()
    if report.status == "draft":
        for n, (text, verdict) in FINDINGS.items():
            s = report.sections.get(number=n)
            who = {"CM": cm, "LW": lawyer, "SV": surveyor}[s.owner_role]
            services.update_section(report, n, who, findings={"text": text},
                                    verdict=verdict if s.in_verdict_rule else ...)
        s1 = report.sections.get(number=1)
        services.update_section(report, 1, cm, findings={**s1.findings, "verdict_note": "Amber"})
        if stop == "sections":
            return report
        services.set_overall_verdict(report, lawyer, "amber")
        if not report.conditions.exists():
            for key, text, resp, ev in CONDITIONS:
                services.add_condition(report, lawyer, key=key, text=text, responsible=resp, closing_evidence=ev)
        services.sign_sections(report, surveyor)
        services.sign_sections(report, lawyer)
        if stop == "submit":
            return report
        report = services.submit_review(report, cm)
    if stop == "approve":
        return report
    if report.status == "in_review":
        now = timezone.now()
        services.approve(report, lawyer, mfa_at=now, note="Legal sections reviewed.")
        services.approve(report, reviewer, mfa_at=now, note="Second review done.")
    report.refresh_from_db()
    return report


def run(ctx):
    from cases import services as cs
    from cases.models import Case

    gh, people = ctx["gh"], ctx["people"]
    seeded = ctx.setdefault("cases", {})
    ama = seeded.get("ama_land_card") or Case.objects.filter(order__details__seed="ama_land_card").first()
    if ama is not None and ama.status in ("paid", "in_progress", "in_review"):
        for p in ("lawyer", "surveyor"):
            people[p].refresh_from_db()
        try:
            report = release_demo_case(ama, gh, people)
            ctx["report"] = report
        except DomainError as exc:
            log.warning("seed: Ama's report not released: %s %s", exc.detail, getattr(exc, "blocking_reasons", ""))
    ama = Case.objects.filter(pk=ama.pk).first() if ama else None
    if ama is not None and ama.status == "released":
        from .models import Report

        ctx["report"] = Report.objects.filter(case=ama, status="released").first()
        if not Case.objects.filter(asset=ama.asset, product_line="fresh_search").exists():
            fs = cs.open_fresh_search(ama.asset, actor=people["cm"], reason="Escrow release coming up (demo)")
            seeded["fresh_search"] = fs
    from . import services
    from .models import RecheckDraw

    month = timezone.localdate().replace(day=1)
    if not RecheckDraw.objects.filter(country=gh, sample_month=month).exists():
        services.draw(gh, month, by=people["reviewer2"])
