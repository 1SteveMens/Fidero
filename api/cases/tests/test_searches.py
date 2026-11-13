"""Official searches from Tenmina's registry account (FR-CASE-016, RUL-30, ADR-25) and fresh searches
(FR-CASE-014, RUL-07)."""
from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from cases import services
from cases.models import Case, SearchRequest
from cases.seed import REGISTRY_ACCOUNT
from cases.tests.helpers import accepted_case, jpeg, pdf, task
from core.models import OutboxEvent


def _lodge(api, people, case, **over):
    body = {"task_id": str(task(case, "searches_lodged").pk), "channel": "online_portal",
            "tenmina_account_ref": REGISTRY_ACCOUNT, "registry_reference": "LC/SRCH/2026/0999", **over}
    return api(people["cm"]).post(f"/v1/cases/{case.pk}/search-requests", body, format="json")


def test_search_lodged_and_received_through_official_channel(seeded, api, people, gh):
    """US-CASE-016 AC1 and AC3, TC-CASE-016-01, TC-RUL-30-01."""
    case = accepted_case(api, people, gh)
    r = _lodge(api, people, case)
    assert r.status_code == 201, r.content
    sr = r.json()
    assert sr["submitted_by"]["id"] == str(people["cm"].pk) and sr["tenmina_account_ref"] == REGISTRY_ACCOUNT
    assert sr["registry"] == "Lands Commission" and sr["status"] == "submitted"
    services.complete_task(task(case, "intake"), people["cm"])
    lodge = task(case, "searches_lodged")
    services.attach_task_evidence(lodge, people["cm"], pdf(people["cm"], gh, "receipt.pdf"), "search_fee_receipt")
    services.complete_task(lodge, people["cm"])
    ev = pdf(people["cm"], gh, "official.pdf")
    r = api(people["cm"]).post(f"/v1/search-requests/{sr['id']}/results",
                               {"evidence_id": str(ev.pk), "registry_result_date": str(timezone.localdate())},
                               format="json")
    assert r.status_code == 200, r.content
    assert r.json()["status"] == "result_received" and r.json()["usable"] is True
    assert r.json()["result_received_by"]["id"] == str(people["cm"].pk)
    assert task(case, "official_search").status == "done"
    assert OutboxEvent.objects.filter(topic="search.result_received").exists()


def test_lodging_needs_reference_and_a_tenmina_account(seeded, api, people, gh):
    """US-CASE-016 AC1, TC-CASE-016-03, TC-RUL-30-03."""
    case = accepted_case(api, people, gh)
    assert _lodge(api, people, case, registry_reference="").status_code == 422
    r = _lodge(api, people, case, tenmina_account_ref="efua.runner.personal")
    assert r.status_code == 422 and r.json()["code"] == "registry-account-invalid"
    assert api(people["runner"]).post(f"/v1/cases/{case.pk}/search-requests", {}, format="json").status_code == 404


def test_result_from_runner_seller_or_client_is_not_evidence(seeded, api, people, gh):
    """US-CASE-016 AC2, TC-CASE-016-02, TC-RUL-30-02: refused as evidence in every path; a copy is kept only
    as unverified, never closes the task, and a different copy opens a fraud review."""
    case = accepted_case(api, people, gh)
    services.complete_task(task(case, "intake"), people["cm"])
    visit = task(case, "site_visit")
    services.record_risk_screen(case, people["cm"], task=visit, outcome="proceed")
    services.assign_task(visit, people["cm"], assignee=people["runner"])
    sr = SearchRequest.objects.get(pk=_lodge(api, people, case).json()["id"])
    rn = api(people["runner"])
    copy = pdf(people["runner"], gh, "search-result-from-runner.pdf")
    r = rn.post(f"/v1/tasks/{visit.pk}/evidence", {"kind": "official_search_result", "evidence_id": str(copy.pk)},
                format="json")
    assert r.status_code == 422 and r.json()["code"] == "evidence-rejected"
    assert r.json()["blocking_reasons"][0]["rule"] == "RUL-30"
    assert rn.post(f"/v1/search-requests/{sr.pk}/results",
                   {"evidence_id": str(copy.pk), "registry_result_date": str(timezone.localdate())},
                   format="json").status_code == 404
    assert rn.post(f"/v1/tasks/{visit.pk}/evidence", {"kind": "search_copy_unverified",
                                                      "evidence_id": str(copy.pk)}, format="json").status_code == 201
    result = task(case, "official_search")
    with pytest.raises(Exception):
        services.complete_task(result, people["cm"])
    from evidence.services import link

    with pytest.raises(Exception):
        link(copy, "search_request", sr.pk, role="official_search_result", by=people["runner"])
    with pytest.raises(IntegrityError), transaction.atomic():
        SearchRequest.objects.create(case=case, country=gh, task=result, registry_partner=sr.registry_partner,
                                     channel="online_portal", tenmina_account_ref=REGISTRY_ACCOUNT,
                                     submitted_by=people["runner"], submitted_at=timezone.now(),
                                     registry_reference="X/1")
    official = pdf(people["cm"], gh, "official-2.pdf")
    services.record_result(sr, people["cm"], evidence=official, registry_result_date=timezone.localdate())
    r = api(people["reviewer"]).post(f"/v1/search-requests/{sr.pk}/copy-comparisons",
                                     {"evidence_id": str(copy.pk), "matches": False, "note": "Different plot no."},
                                     format="json")
    assert r.status_code == 201
    assert OutboxEvent.objects.filter(topic="search.copy_mismatch", aggregate_id=sr.pk).exists()


def test_registry_without_remote_channel_needs_staff_confirmation(seeded, api, people, gh):
    """US-CASE-016 AC4, TC-CASE-016-04, TC-RUL-30-04."""
    from administration.services import create_partner

    p, _ = create_partner(country=gh, kind="registry", name="Testland Registry", by=people["admin"],
                          details={"tenmina_accounts": ["TMN-TL-01"], "channels": ["office"]})
    case = accepted_case(api, people, gh)
    body = {"task_id": str(task(case, "searches_lodged").pk), "channel": "online_portal",
            "tenmina_account_ref": "TMN-TL-01", "registry_reference": "TL/77", "registry_partner_id": str(p.pk)}
    cm = api(people["cm"])
    assert cm.post(f"/v1/cases/{case.pk}/search-requests", body, format="json").json()["code"] == \
        "registry-no-remote-channel"
    r = cm.post(f"/v1/cases/{case.pk}/search-requests", {**body, "channel": "registry_office"}, format="json")
    assert r.status_code == 201
    sid = r.json()["id"]
    ev = pdf(people["cm"], gh, "office-result.pdf")
    base = {"evidence_id": str(ev.pk), "registry_result_date": str(timezone.localdate())}
    r = cm.post(f"/v1/search-requests/{sid}/results", base, format="json")
    assert r.status_code == 422 and r.json()["code"] == "registry-confirmation-required"
    r = cm.post(f"/v1/search-requests/{sid}/results",
                {**base, "confirmed_with": "Mr Mensah, Deputy Registrar", "confirmed_at": timezone.now().isoformat()},
                format="json")
    assert r.status_code == 200 and r.json()["status"] == "confirmed" and r.json()["usable"] is True


def test_fresh_search_only_on_verified_asset(seeded, api, people, gh):
    """US-CASE-014 AC1 and AC2, TC-CASE-014-01/02, TC-CASE-016-05: search and site check only; the result date
    reaches the release check only from the official channel."""
    from cases import selectors

    unverified = accepted_case(api, people, gh)
    r = api(people["cm"]).post(f"/v1/assets/{unverified.asset_id}/fresh-searches", {}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "asset-not-verified"
    # Several seeded land cases are released; Ama's is the one with a released report on a verified plot.
    released = Case.objects.get(order__details__seed="ama_land_card")
    assert released.status == "released"
    Case.objects.filter(asset=released.asset, product_line="fresh_search").update(status="cancelled",
                                                                                   cancel_reason="test",
                                                                                   refund_decision="no_refund")
    r = api(people["cm"]).post(f"/v1/assets/{released.asset_id}/fresh-searches", {"reason": "Escrow release"},
                               format="json")
    assert r.status_code == 201, r.content
    fs = Case.objects.get(pk=r.json()["id"])
    assert set(fs.tasks.values_list("step_key", flat=True)) == {"fresh_search", "site_check"}
    site = task(fs, "site_check")
    services.record_risk_screen(fs, people["cm"], task=site, outcome="proceed")
    site = services.assign_task(site, people["cm"], assignee=people["runner"])
    services.attach_task_evidence(site, people["runner"], jpeg(people["runner"], gh), "site_photo")
    services.complete_task(site, people["runner"])
    assert selectors.latest_fresh_search(released.asset_id) is None or \
        selectors.latest_fresh_search(released.asset_id)["case_id"] != fs.pk
    sr = services.submit_search(fs, people["cm"], task=task(fs, "fresh_search"), channel="online_portal",
                                tenmina_account_ref=REGISTRY_ACCOUNT, registry_reference="LC/FS/1")
    day = timezone.localdate() - timedelta(days=2)
    services.record_result(sr, people["cm"], evidence=pdf(people["cm"], gh, "fs.pdf"), registry_result_date=day)
    fs.refresh_from_db()
    assert fs.status == "completed"
    ev = OutboxEvent.objects.get(topic="fresh_search.completed", aggregate_id=fs.pk)
    assert ev.payload["registry_result_date"] == day.isoformat() and ev.payload["asset_id"] == str(fs.asset_id)
    assert selectors.latest_fresh_search(released.asset_id)["registry_result_date"] == day
