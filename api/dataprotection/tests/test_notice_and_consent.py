"""Privacy notice and consents (US-DPR-001, US-DPR-002, RUL-16;
TC-DPR-001, TC-DPR-002)."""
import uuid

import pytest

from accounts import services as acc
from core.errors import RuleBlocked
from core.models import OutboxEvent
from dataprotection import selectors, services
from dataprotection.models import Consent, PrivacyAcceptance


def _ev(gh, by, name="video.mp4"):
    from evidence.services import store

    return store(data=name.encode() + uuid.uuid4().bytes, country=gh, uploaded_by=by, content_type="video/mp4",
                 original_name=name)


def test_signup_stores_notice_version_and_time(seeded):
    """US-DPR-001 AC1, TC-DPR-001-01."""
    p = acc.register(email="n@example.com", password="a-long-password-1", full_name="New Person",
                     phone="+447700900777", privacy_notice_version="1.0")
    a = PrivacyAcceptance.objects.get(person=p)
    assert a.version == "1.0" and a.accepted_at and a.source == "signup"
    assert selectors.pending_notice_version(p) is None


def test_new_version_is_asked_for_at_next_sign_in(seeded, api, people):
    """US-DPR-001 AC2, TC-DPR-001-02."""
    admin = people["admin"]
    r = api(admin).post("/v1/dpr/privacy-notices", {"version": "2.0", "text": "Updated notice."}, format="json")
    assert r.status_code == 201 and r.json()["status"] == "published"
    assert api(people["client"]).post("/v1/dpr/privacy-notices", {"version": "3", "text": "x"},
                                      format="json").status_code == 403
    r = api().post("/v1/auth/login", {"identifier": "ama@example.com", "password": "tenmina-dev-123"})
    assert r.json()["privacy_notice_pending"] == "2.0"
    assert api().get("/v1/privacy-notices/current").json()["version"] == "2.0"
    c = api(people["client"])
    home = c.get("/v1/home").json()
    assert any(i["kind"] == "privacy_notice" and i["needs_action"] for i in home["items"])
    assert c.post("/v1/me/privacy-acceptances", {"version": "1.0"}, format="json").status_code == 422
    assert c.post("/v1/me/privacy-acceptances", {"version": "2.0"}, format="json").status_code == 201
    assert c.get("/v1/me").json()["privacy_notice_pending"] is None


def test_partner_consent_given_and_withdrawn(seeded, api, people):
    """RUL-16, FR-PTR-002: consent names the partner; withdrawal publishes consent.changed."""
    c = api(people["client2"])
    partner = uuid.uuid4()
    r = c.post("/v1/consents", {"purpose": "partner_status"}, format="json")
    assert r.status_code == 422
    r = c.post("/v1/consents", {"purpose": "partner_status", "partner_client_id": str(partner)}, format="json")
    assert r.status_code == 201
    assert selectors.has_consent(people["client2"], "partner_status", partner_client_id=partner)
    assert not selectors.has_consent(people["client2"], "partner_status", partner_client_id=uuid.uuid4())
    assert api(people["client"]).delete(f"/v1/consents/{r.json()['id']}").status_code == 404
    r = c.delete(f"/v1/consents/{r.json()['id']}")
    assert r.status_code == 200 and r.json()["withdrawn_at"]
    assert not selectors.has_consent(people["client2"], "partner_status", partner_client_id=partner)
    ev = OutboxEvent.objects.filter(topic="consent.changed").latest("created_at")
    assert ev.payload["status"] == "withdrawn" and ev.payload["partner_client_id"] == str(partner)


def test_full_report_consent_names_the_report(seeded, people):
    with pytest.raises(Exception):
        services.give_consent(people["client"], purpose="partner_full_report", text_version="1",
                              partner_client_id=uuid.uuid4())


def test_video_consent_links_person_purpose_and_version(seeded, api, people, gh):
    """US-DPR-002 AC2, TC-DPR-002-01: each person's consent linked to the recording."""
    lw = people["lawyer"]
    video = _ev(gh, lw)
    case = uuid.uuid4()
    for name in ("Nana Asare", "Abena Asare", "Kwasi Witness"):
        r = api(lw).post("/v1/consents/video", {"subject_name": name, "recording_evidence": str(video.pk),
                                                "text_version": "consent-v1", "case_id": str(case),
                                                "role_in_recording": "family"}, format="json")
        assert r.status_code == 201, r.content
    cs = Consent.objects.filter(recording_evidence=video)
    assert cs.count() == 3 and {c.text_version for c in cs} == {"consent-v1"}
    assert api(people["client"]).post("/v1/consents/video", {}, format="json").status_code == 403


def test_video_without_consent_cannot_be_attached(seeded, api, people, gh):
    """US-DPR-002 AC1, TC-DPR-002-02."""
    lw = people["lawyer"]
    video = _ev(gh, lw, "no-consent.mp4")
    case = uuid.uuid4()
    r = api(lw).post("/v1/consents/recording-links", {"evidence": str(video.pk), "case_id": str(case)},
                     format="json")
    assert r.status_code == 409 and r.json()["blocking_reasons"][0]["rule"] == "FR-DPR-002"
    services.record_video_consent(lw, subject_name="Seller", recording_evidence=video, text_version="1")
    r = api(lw).post("/v1/consents/recording-links", {"evidence": str(video.pk), "case_id": str(case)},
                     format="json")
    assert r.status_code == 201 and r.json()["role"] == "consent_video"


def test_withdrawn_video_consent_blocks_attachment(seeded, people, gh):
    lw = people["lawyer"]
    video = _ev(gh, lw, "w.mp4")
    c = services.record_video_consent(lw, subject_name="Seller", recording_evidence=video, text_version="1")
    services.withdraw_consent(c, lw)
    with pytest.raises(RuleBlocked):
        services.attach_recording(lw, evidence=video, case_id=uuid.uuid4())
