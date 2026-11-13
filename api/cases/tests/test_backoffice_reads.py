"""Read-only endpoints the back office screens need: task candidates (W-13), re-check candidates (SCR-BO-45),
one approval request, and the list of exchange conversions (FR-ESC-023)."""
from datetime import date

from cases import services
from cases.tests.helpers import accepted_case, licensed, task
from reports import services as rpt
from reports.models import RecheckCandidate
from reports.seed import release_demo_case


def test_task_candidates_show_role_licence_and_visit_rule(seeded, api, people, gh):
    """W-13: the main person holds the step's role; a field professional can be second; an unverified licence
    is shown with its reason; the visit rule asks for a risk screen first."""
    case = accepted_case(api, people, gh)
    services.complete_task(task(case, "intake"), people["cm"])
    visit = task(case, "site_visit")
    r = api(people["cm"]).get(f"/v1/tasks/{visit.pk}/candidates")
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["owner_role"] == "RN" and body["site_visit"] is True
    assert body["visit_blockers"] and body["visit_blockers"][0]["rule"] == "RUL-17"
    by_name = {p["name"]: p for p in body["people"]}
    assert by_name["Efua Runner"]["can_be_main"] is True
    assert by_name["Kojo Surveyor"]["can_be_second"] is True and by_name["Kojo Surveyor"]["can_be_main"] is False
    # clients and other outsiders are never listed
    assert "Ama Mensah" not in by_name
    # a professional cannot read the candidates
    services.record_risk_screen(case, people["cm"], task=visit, outcome="proceed")
    services.assign_task(visit, people["cm"], assignee=people["runner"])
    assert api(people["runner"]).get(f"/v1/tasks/{visit.pk}/candidates").status_code == 404


def test_task_candidates_flag_an_invalid_licence(seeded, api, people, gh):
    case = accepted_case(api, people, gh, asset={"type": "building", "locality": "Tema"})
    t = task(case, "structural_inspection")
    body = api(people["cm"]).get(f"/v1/tasks/{t.pk}/candidates").json()
    insp = next(p for p in body["people"] if p["name"] == "Kwesi Inspector")
    assert insp["licence"]["valid"] is False and insp["can_be_main"] is False and insp["licence"]["message"]


def test_recheck_candidates_exclude_linked_people(seeded, api, people, gh):
    """SCR-BO-45, RUL-32: the case's own lawyer and surveyor are not offered; an unlinked licensed lawyer is."""
    case = accepted_case(api, people, gh)
    report = release_demo_case(case, gh, people)
    month = date(2031, 2, 1)
    RecheckCandidate.objects.filter(subject_id=report.pk).update(sample_month=month)
    d = rpt.draw(gh, month, by=people["reviewer2"])
    rc = d.rechecks.get()
    outsider = licensed(gh, "LW", "outside.lawyer@example.com", "Outside Lawyer")
    r = api(people["reviewer2"]).get(f"/v1/rechecks/{rc.pk}/candidates")
    assert r.status_code == 200, r.content
    ids = {p["id"] for p in r.json()}
    assert str(outsider.pk) in ids
    assert str(people["lawyer"].pk) not in ids and str(people["surveyor"].pk) not in ids
    assert api(people["cm"]).get(f"/v1/rechecks/{rc.pk}/candidates").status_code == 404


def test_one_approval_request_for_staff_only(seeded, api, people, gh):
    from core.models import ApprovalRequest

    req = ApprovalRequest.objects.filter(status="open").first()
    r = api(people["reviewer"]).get(f"/v1/approvals/{req.pk}")
    assert r.status_code == 200 and r.json()["id"] == str(req.pk) and "dedicated" in r.json()
    assert api(people["client"]).get(f"/v1/approvals/{req.pk}").status_code == 404


def test_conversion_list_for_staff(seeded, api, people, gh):
    r = api(people["cm"]).get("/v1/fx-conversions")
    assert r.status_code == 200 and "items" in r.json()
    r = api(people["cm"]).get("/v1/fx-conversions", {"status": "outside"})
    assert r.status_code == 200 and all(c["status"] == "outside" for c in r.json()["items"])
    assert api(people["client"]).get("/v1/fx-conversions").status_code == 403
