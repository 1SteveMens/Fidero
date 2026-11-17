"""Every id the demo seed writes for another object belongs to a real row, so every screen link opens.

The web audit (scripts/ui-audit) once found an escrow and field inbox items pointing at a report, a task, an
inspection and a care visit that no seed created ("Not found" pages). These tests walk the seeded database."""
import re
import uuid

from django.apps import apps
from django.db import models

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _all_pks() -> set:
    pks = set()
    for m in apps.get_models():
        if isinstance(m._meta.pk, (models.UUIDField, models.OneToOneField, models.ForeignKey)):
            pks.update(m.objects.values_list("pk", flat=True))
    return pks


def _missing(values, pks) -> list:
    return [v for v in values if v is not None and uuid.UUID(str(v)) not in pks]


def test_every_evidence_link_and_owner_resolves(seeded):
    from evidence.models import Evidence, EvidenceLink, IssuedDocument

    pks = _all_pks()
    bad = [(link.subject_type, link.role, str(link.subject_id)) for link in EvidenceLink.objects.all()
           if link.subject_id not in pks]
    assert not bad, f"evidence links to rows that do not exist: {bad[:10]}"
    owners = Evidence.objects.exclude(owner_id=None).values_list("owner_type", "owner_id")
    bad = [(t, str(i)) for t, i in owners if i not in pks]
    assert not bad, f"evidence owned by rows that do not exist: {bad[:10]}"
    bad = [(d.subject_type, str(d.subject_id)) for d in IssuedDocument.objects.all() if d.subject_id not in pks]
    assert not bad, f"issued documents for rows that do not exist: {bad[:10]}"


def test_every_escrow_subject_resolves(seeded):
    from cases.models import Case
    from escrow.models import Escrow, Freeze, Payee
    from geo.models import Asset
    from reports.models import Report

    pks = _all_pks()
    reports = set(Report.objects.values_list("pk", flat=True))
    cases = set(Case.objects.values_list("pk", flat=True))
    assets = set(Asset.objects.values_list("pk", flat=True))
    escrows = list(Escrow.objects.all())
    assert escrows
    for e in escrows:
        where = f"{e.reference} {e.title}"
        assert e.report_id is None or e.report_id in reports, f"{where}: report {e.report_id} does not exist"
        assert e.case_id is None or e.case_id in cases, f"{where}: case {e.case_id} does not exist"
        assert e.fresh_search_case_id is None or e.fresh_search_case_id in cases, \
            f"{where}: fresh search case {e.fresh_search_case_id} does not exist"
        assert e.asset_id is None or e.asset_id in assets, f"{where}: asset {e.asset_id} does not exist"
        assert e.project_id is None or e.project_id in pks, f"{where}: project {e.project_id} does not exist"
    assert Escrow.objects.filter(kind="purchase").exclude(report_id=None).exists()
    bad = _missing(Freeze.objects.values_list("source_id", flat=True), pks)
    assert not bad, f"freezes from sources that do not exist: {bad}"
    bad = _missing(Payee.objects.values_list("subject_id", flat=True), pks)
    assert not bad, f"payees for subjects that do not exist: {bad}"


LINK_FIELDS = ("case_id", "report_id", "asset_id", "project_id", "fresh_search_case_id", "check_case_id",
               "offplan_case_id", "source_condition_id", "subject_id", "source_id")


def test_every_case_report_asset_and_project_id_resolves(seeded):
    """Escrows and their commitments, report snapshots, projects, payables and every other row that names a case,
    report, asset, project or subject by a plain id (not a foreign key) name a real row, so "Open the case" and the
    like never lead to "We could not find this". The phone app audit once found an escrow whose case the seed never
    created."""
    pks = _all_pks()
    checked = 0
    for m in apps.get_models():
        for f in m._meta.get_fields():
            if not isinstance(f, models.UUIDField) or f.primary_key or f.name not in LINK_FIELDS:
                continue
            values = list(m.objects.exclude(**{f.name: None}).values_list(f.name, flat=True))
            checked += len(values)
            bad = _missing(values, pks)
            assert not bad, f"{m._meta.db_table}.{f.name} names rows that do not exist: {bad[:5]}"
    assert checked


def test_every_home_item_link_resolves(seeded):
    from accounts import home
    from accounts.models import Person

    pks = _all_pks()
    seen = 0
    for p in Person.objects.filter(role_grants__role__in=["CL", "FM", "TN"], role_grants__revoked_at=None).distinct():
        for it in home.items_for(p):
            seen += 1
            ids = [it["id"], it.get("family_member_id"), *UUID_RE.findall(it.get("link") or "")]
            bad = _missing(ids, pks)
            assert not bad, f"{p.email}: home item {it['kind']} '{it['title']}' ({it['link']}) names {bad}"
    assert seen


def test_every_inbox_item_resolves(seeded):
    from accounts.models import Person
    from mobile import inbox

    pks = _all_pks()
    seen = 0
    for p in Person.objects.all():
        for it in inbox.items_for(p):
            seen += 1
            ids = [it.subject_id] + [v for k, v in (it.details or {}).items() if k.endswith("_id") and v]
            bad = _missing(ids, pks)
            assert not bad, f"{p.email}: inbox item {it.subject_type} '{it.title}' ({it.source}) names {bad}"
    assert seen


def test_case_subjects_and_case_scoped_rows_resolve(seeded):
    """Rows that name a case or another subject by id: case subjects, representatives, identity checks,
    recorded consents, legal holds, monitoring sources and field captures."""
    from accounts.models import NationalIdCheck, RepresentativeGrant
    from cases.models import Case
    from dataprotection.models import Consent, LegalHold
    from geo.models import MonitoringEnrolment
    from mobile.models import CheckIn, FraudFlag, SignedManifest, Submission

    pks = _all_pks()
    checks = {
        "case subject": Case.objects.values_list("subject_id", flat=True),
        "representative": RepresentativeGrant.objects.values_list("subject_id", flat=True),
        "identity check context": NationalIdCheck.objects.values_list("context_id", flat=True),
        "consent case": Consent.objects.values_list("case_id", flat=True),
        "consent partner client": Consent.objects.values_list("partner_client_id", flat=True),
        "legal hold": LegalHold.objects.values_list("subject_id", flat=True),
        "monitoring source": MonitoringEnrolment.objects.values_list("source_id", flat=True),
        "field capture": SignedManifest.objects.values_list("subject_id", flat=True),
        "field submission": Submission.objects.values_list("subject_id", flat=True),
        "check-in": CheckIn.objects.values_list("subject_id", flat=True),
        "fraud flag": FraudFlag.objects.values_list("subject_id", flat=True),
    }
    for name, values in checks.items():
        bad = _missing(values, pks)
        assert not bad, f"{name}: names rows that do not exist: {bad[:5]}"
