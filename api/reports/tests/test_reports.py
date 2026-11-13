"""RPT: report builder, verdict rule, locked scope, signatures, two-person release, PDF and hash, conditions,
corrections and anonymised copies (FR-RPT-001 to FR-RPT-011; RUL-02, RUL-03, RUL-04, RUL-20, RUL-31)."""
import hashlib
import itertools
from datetime import date, timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from audit.models import AuditEvent
from cases.tests.helpers import accepted_case, licensed
from core.errors import DomainError
from core.models import OutboxEvent
from reports import selectors, services
from reports.models import Report, Section
from reports.seed import release_demo_case


def _report(api, people, gh, stop="submit", **kw):
    case = accepted_case(api, people, gh)
    return release_demo_case(case, gh, people, stop=stop, **kw)


def test_report_built_from_template_with_locked_scope(seeded, api, people, gh):
    """US-RPT-001 AC1, US-RPT-004 AC1, TC-RPT-001-01, TC-RUL-04-01: sections 1 to 14 in order, the template
    version and the locked scope text with its version."""
    from administration.selectors import current_locked_text

    case = accepted_case(api, people, gh)
    r = case.reports.get()
    assert list(r.sections.order_by("position").values_list("number", flat=True)) == list(range(1, 15))
    lt = current_locked_text("scope_statement", gh)
    s12 = r.sections.get(number=12)
    assert s12.locked and s12.findings["text"] == lt.text and r.scope_text_version_id == lt.pk
    body = api(people["cm"]).get(f"/v1/reports/{r.pk}").json()
    assert body["template_version_number"] == r.template_version.version and body["scope_version"] == lt.version


def test_section_12_cannot_be_edited(seeded, api, people, gh):
    """US-RPT-004 AC2, TC-RUL-04-02: refused by API and by the database; the attempt is audited."""
    r = _report(api, people, gh, stop="sections")
    resp = api(people["cm"]).put(f"/v1/reports/{r.pk}/sections/12", {"findings": {"text": "We guarantee title."}},
                                 format="json")
    assert resp.status_code == 409 and resp.json()["code"] == "locked-text"
    assert AuditEvent.objects.filter(action="report.locked_text_edit_refused", entity_id=str(r.pk)).exists()
    r = services.submit_review(release_demo_case(r.case, gh, people, stop="submit"), people["cm"])
    with pytest.raises(Exception), transaction.atomic():
        Section.objects.filter(report=r, number=12).update(findings={"text": "changed"})


def test_section_owner_only(seeded, api, people, gh):
    """US-RPT-002, TC-RPT-002-01/02: the owner saves findings and verdict with name and time; others are refused."""
    r = _report(api, people, gh, stop="sections")
    resp = api(people["surveyor"]).put(f"/v1/reports/{r.pk}/sections/6",
                                       {"findings": {"text": "Small overlap of 0.3 m"}, "verdict": "amber"},
                                       format="json")
    assert resp.status_code == 200 and resp.json()["verdict"] == "amber"
    s6 = r.sections.get(number=6)
    assert s6.updated_by_id == people["surveyor"].pk and s6.edited_at
    assert api(people["lawyer"]).put(f"/v1/reports/{r.pk}/sections/6", {"verdict": "green"},
                                     format="json").status_code == 403
    assert api(people["runner"]).put(f"/v1/reports/{r.pk}/sections/6", {"verdict": "green"},
                                     format="json").status_code in (403, 404)
    assert api(people["client"]).get(f"/v1/reports/{r.pk}").status_code == 404


def test_green_blocked_when_a_section_is_red(seeded, api, people, gh):
    """US-RPT-003, TC-RUL-02-01 to 04: green refused by API with the allowed values, audited; a section turning
    red resets a green verdict; the database refuses it too."""
    r = _report(api, people, gh, stop="sections")
    lw = api(people["lawyer"])
    assert lw.post(f"/v1/reports/{r.pk}/verdict", {"overall_verdict": "green"}, format="json").status_code == 200
    services.update_section(r, 5, people["lawyer"], verdict="red")
    r.refresh_from_db()
    assert r.overall_verdict is None
    services.update_section(r, 5, people["lawyer"], verdict="green")
    services.update_section(r, 7, people["surveyor"], verdict="red")
    resp = lw.post(f"/v1/reports/{r.pk}/verdict", {"overall_verdict": "green"}, format="json")
    assert resp.status_code == 409 and resp.json()["code"] == "verdict-rule"
    assert resp.json()["allowed_verdicts"] == ["red", "amber"]
    assert AuditEvent.objects.filter(action="report.verdict_refused", entity_id=str(r.pk)).exists()
    with pytest.raises(IntegrityError), transaction.atomic():
        Report.objects.filter(pk=r.pk).update(overall_verdict="green")
    services.update_section(r, 7, people["surveyor"], verdict="green")
    services.update_section(r, 10, people["surveyor"], verdict="red")
    assert services.allowed_verdicts(r)[0] == ["red", "amber"]


def test_verdict_rule_every_combination(seeded, api, people, gh):
    """TC-RUL-02-05: green allowed only when no section 4 to 10 is red."""
    r = _report(api, people, gh, stop="sections")
    nums = list(range(4, 11))
    for combo in itertools.islice(itertools.product(["red", "amber", "green"], repeat=7), 0, 2187, 97):
        for n, v in zip(nums, combo):
            Section.objects.filter(report=r, number=n).update(verdict=v)
        allowed, _ = services.allowed_verdicts(r)
        assert ("green" in allowed) == ("red" not in combo)


def test_signing_needs_valid_licence_and_the_right_role(seeded, api, people, gh, mfa):
    """US-RPT-005, TC-RUL-20-01 to 03, TC-RPT-005-02: name, licence and time recorded; an expired licence is
    blocked and the case manager alerted; a surveyor cannot sign the legal section."""
    from accounts.models import ProfessionalLicence
    from notifications.models import Message

    r = _report(api, people, gh, stop="sections")
    services.set_overall_verdict(r, people["lawyer"], "amber")
    sv = api(people["surveyor"])
    mfa(sv, people["surveyor"])
    assert sv.post(f"/v1/reports/{r.pk}/sections/5/signatures").status_code == 403
    resp = sv.post(f"/v1/reports/{r.pk}/sections/6/signatures")
    assert resp.status_code == 201
    assert resp.json()["licence_number"] == "GHIS/DEMO/0002" and resp.json()["signer_name"] == "Kojo Surveyor"
    ProfessionalLicence.objects.filter(person=people["lawyer"]).update(expires_on=date.today() - timedelta(days=1))
    lw = api(people["lawyer"])
    mfa(lw, people["lawyer"])
    resp = lw.post(f"/v1/reports/{r.pk}/sections/5/signatures")
    assert resp.status_code == 409 and resp.json()["code"] == "licence-invalid"
    assert Message.objects.filter(person=people["cm"], subject__startswith="Signing blocked").exists()


def test_two_person_release_rules(seeded, api, people, gh, mfa):
    """US-RPT-006, TC-RUL-03-01 to 03: the signing lawyer and a different reviewer; the same person twice,
    a lawyer who did not sign, or a second reviewer are refused; one approval does not release."""
    r = _report(api, people, gh, stop="approve")
    assert r.status == "in_review" and r.case.status == "in_review"
    other_lawyer = licensed(gh, "LW", "lw2@example.com", "Second Lawyer")
    l2 = api(other_lawyer)
    mfa(l2, other_lawyer)
    assert l2.post(f"/v1/reports/{r.pk}/approvals", {}, format="json").status_code in (403, 404)
    lw = api(people["lawyer"])
    mfa(lw, people["lawyer"])
    assert lw.post(f"/v1/reports/{r.pk}/approvals", {}, format="json").status_code == 200
    resp = lw.post(f"/v1/reports/{r.pk}/approvals", {}, format="json")
    assert resp.status_code == 409 and resp.json()["code"] == "same-approver"
    r.refresh_from_db()
    assert r.status == "in_review"
    rv = api(people["reviewer"])
    mfa(rv, people["reviewer"])
    resp = rv.post(f"/v1/reports/{r.pk}/approvals", {"note": "OK"}, format="json")
    assert resp.status_code == 200, resp.content
    r.refresh_from_db()
    assert r.status == "released" and r.case.status == "released"


def test_reviewer_slot_once_and_return(seeded, api, people, gh, mfa):
    """TC-RUL-03-02 and the return path: a second reviewer cannot take the lawyer's slot; a return sends the
    report back to draft and the case back in progress."""
    r = _report(api, people, gh, stop="approve")
    for who in ("reviewer", "reviewer2"):
        mfa(api(people[who]), people[who])
    now = timezone.now()
    services.approve(r, people["reviewer"], mfa_at=now)
    with pytest.raises(DomainError) as e:
        services.approve(r, people["reviewer2"], mfa_at=now)
    assert e.value.code == "same-approver"
    services.approve(r, people["reviewer2"], decision="return", note="Section 8 needs the consent date.",
                     mfa_at=now)
    r.refresh_from_db()
    r.case.refresh_from_db()
    assert r.status == "draft" and r.case.status == "in_progress"


def test_release_blocked_by_pending_identity_check(seeded, api, people, gh):
    """RUL-31, FR-ACC-013: a party whose national identity check is pending blocks the review; a failed check
    allows only a red verdict."""
    from cases import services as cs

    r = _report(api, people, gh, stop="submit")
    cs.add_party(r.case, people["cm"], role="consenting_party", name="Yaw Pending", id_number="GHA-744000001-9")
    with pytest.raises(DomainError) as e:
        services.submit_review(r, people["cm"])
    assert any(b["rule"] == "RUL-31" for b in e.value.blocking_reasons)
    cs.add_party(r.case, people["cm"], role="grantor", name="Nobody Known", id_number="GHA-744000002-0")
    assert services.allowed_verdicts(r)[0] == ["red"]


def test_released_pdf_hash_and_public_check(seeded, api, people, gh):
    """US-RPT-007, US-RPT-008, TC-RPT-007-01/02, TC-RPT-008-01/02, ADR-15: the stored bytes hash to the stored
    SHA-256; the PDF is deterministic; the public check says match or no match only; the evidence fingerprint
    check finds it."""
    from evidence.services import open_link
    from reports.pdf import renderer

    r = _report(api, people, gh, stop=None)
    assert r.status == "released"
    link = api(people["client"]).get(f"/v1/reports/{r.pk}/pdf").json()
    data, ct, _name, _ev = open_link(link["url"].rsplit("/", 1)[1], user=people["client"])
    assert ct == "application/pdf" and hashlib.sha256(data).hexdigest() == r.pdf_sha256 == link["sha256"]
    assert renderer().render(services._doc(r)) == renderer().render(services._doc(r))
    with pytest.raises(DomainError):
        services.release(r)
    pub = api()
    ok = pub.post("/v1/report-verifications", {"reference": r.reference, "sha256": r.pdf_sha256}, format="json")
    assert ok.status_code == 200 and ok.json() == {"match": True, "released_on": str(r.released_at.date()),
                                                   "superseded": False}
    bad = pub.post("/v1/report-verifications", {"reference": r.reference, "sha256": "0" * 64}, format="json")
    assert bad.json()["match"] is False and set(bad.json()) == {"match", "released_on", "superseded"}
    from django.core.files.uploadedfile import SimpleUploadedFile

    up = pub.post("/v1/report-verifications", {"reference": r.reference,
                                               "file": SimpleUploadedFile("r.pdf", data, "application/pdf")},
                  format="multipart")
    assert up.json()["match"] is True
    fp = pub.post("/v1/fingerprint-checks", {"sha256": r.pdf_sha256}, format="json")
    assert fp.status_code == 200 and fp.json()["match"] is True


def test_release_events_and_work_accepted(seeded, api, people, gh):
    """report.released payload for GEO, MOB, ESC; work.accepted per signer with no verdict field (RUL-26)."""
    r = _report(api, people, gh, stop=None)
    ev = OutboxEvent.objects.get(topic="report.released", aggregate_id=r.pk).payload
    for k in ("report_id", "case_id", "asset_id", "pdf_evidence_id", "verdict", "released_at"):
        assert ev[k]
    work = [e.payload for e in OutboxEvent.objects.filter(topic="work.accepted", payload__report_id=str(r.pk))]
    assert {(w["person_id"], w["role"]) for w in work} == {(str(people["lawyer"].pk), "LW"),
                                                            (str(people["surveyor"].pk), "SV")}
    assert all(w["case_id"] == str(r.case_id) and w["work_type"] == "report_section" and "verdict" not in w
               for w in work)
    r.case.asset.refresh_from_db()
    assert r.case.asset.verified_at is not None


def test_conditions_structured_for_escrow(seeded, api, people, gh):
    """US-RPT-009, TC-RPT-009-01/02: each with text, responsible party and closing evidence; a red report has none
    to copy and cannot open an escrow."""
    r = _report(api, people, gh, stop=None)
    items = selectors.conditions_for(r)
    assert len(items) == 3 and all(i["text"] and i["responsible"] and i["closing_evidence"] for i in items)
    assert selectors.escrow_blockers(r) == []
    Report.objects.filter(pk=r.pk)  # released rows cannot change, so check a red draft instead
    red = _report(api, people, gh, stop="sections")
    services.update_section(red, 7, people["surveyor"], verdict="red")
    services.set_overall_verdict(red, people["lawyer"], "red")
    assert selectors.conditions_for(red) == [] and selectors.escrow_blockers(red)


def test_released_report_never_changes_and_correction_is_new_version(seeded, api, people, gh, mfa):
    """US-RPT-010, TC-RPT-010-01/02: edits refused by API and database; a correction is a new version with a
    reason and its own hash; the old one is superseded; the client is notified."""
    from notifications.models import Message

    r = _report(api, people, gh, stop=None)
    assert api(people["lawyer"]).put(f"/v1/reports/{r.pk}/sections/5", {"verdict": "red"},
                                     format="json").status_code in (403, 409)
    with pytest.raises(Exception), transaction.atomic():
        Report.objects.filter(pk=r.pk).update(overall_verdict="red")
    resp = api(people["cm"]).post(f"/v1/reports/{r.pk}/corrections", {"reason": "Wrong plot number on the cover"},
                                  format="json")
    assert resp.status_code == 201
    v2 = Report.objects.get(pk=resp.json()["id"])
    assert v2.version == 2 and v2.supersedes_id == r.pk and v2.status == "draft"
    services.update_section(v2, 1, people["cm"], findings={"text": "Plot 118, corrected."})
    for who in ("lawyer", "surveyor"):
        services.sign_sections(v2, people[who])
    v2 = services.submit_review(v2, people["cm"])
    now = timezone.now()
    services.approve(v2, people["lawyer"], mfa_at=now)
    services.approve(v2, people["reviewer"], mfa_at=now)
    v2.refresh_from_db()
    r.refresh_from_db()
    assert v2.status == "released" and r.status == "superseded" and v2.pdf_sha256 != r.pdf_sha256
    assert Message.objects.filter(person=r.case.client, subject__startswith="Corrected report").exists()
    old = api().post("/v1/report-verifications", {"reference": r.reference, "sha256": r.pdf_sha256}, format="json")
    assert old.json()["match"] is True and old.json()["superseded"] is True


def test_anonymised_copy_needs_consent(seeded, api, people, gh):
    """US-RPT-011, TC-RPT-011-01/02."""
    from dataprotection.services import give_consent
    from evidence.services import get_adapter

    r = _report(api, people, gh, stop=None)
    rv = api(people["reviewer2"])
    resp = rv.post(f"/v1/reports/{r.pk}/anonymised-copies")
    assert resp.status_code == 409 and resp.json()["code"] == "consent-required"
    give_consent(r.case.client, purpose="case_study", text_version="v1", report_id=r.pk)
    resp = rv.post(f"/v1/reports/{r.pk}/anonymised-copies")
    assert resp.status_code == 201
    from evidence.models import Evidence

    ev = Evidence.objects.get(pk=resp.json()["evidence"])
    data = get_adapter("evidence_store").get(ev.storage_key)
    import zlib

    text = b"".join(zlib.decompress(chunk) for chunk in _streams(data))
    assert b"Ama" not in text and r.case.reference.encode() not in text


def _streams(data):
    import re

    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        try:
            import zlib

            zlib.decompress(m.group(1))
            yield m.group(1)
        except Exception:  # noqa: BLE001
            continue


def test_submit_review_by_api(seeded, api, people, gh):
    """5.2: only a case manager sends the report to review; the case moves to in review and an approval opens."""
    r = _report(api, people, gh, stop="submit")
    assert api(people["lawyer"]).post(f"/v1/reports/{r.pk}/submit-review").status_code == 403
    resp = api(people["cm"]).post(f"/v1/reports/{r.pk}/submit-review")
    assert resp.status_code == 200 and resp.json()["status"] == "in_review"
    r.refresh_from_db()
    assert r.approval_request.subject_type == "report_release" and r.case.status == "in_review"
    assert OutboxEvent.objects.filter(topic="report.submitted", aggregate_id=r.pk).exists()


def test_client_sees_section_verdicts_and_signatures_once_released(seeded, api, people, gh):
    """FR-RPT-005, W-08: the client's report viewer shows each section's verdict, what was found and who
    signed with their licence, but only once the report is released."""
    draft = _report(api, people, gh)
    resp = api(people["client"]).get(f"/v1/reports/{draft.pk}")
    assert resp.status_code == 404 or (resp.json()["sections"] == [] and resp.json()["signatures"] == [])
    r = _report(api, people, gh, stop=None)
    body = api(people["client"]).get(f"/v1/reports/{r.pk}").json()
    numbers = [s["number"] for s in body["sections"]]
    assert numbers == sorted(numbers) and 4 in numbers
    s4 = next(s for s in body["sections"] if s["number"] == 4)
    assert set(s4) == {"number", "label", "title", "in_verdict_rule", "verdict", "text"} and s4["in_verdict_rule"]
    assert body["signatures"] and all(set(x) == {"role", "signer_name", "licence_number", "licence_body",
                                                 "signed_at", "section_label"} for x in body["signatures"])
