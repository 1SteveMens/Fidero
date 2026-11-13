"""CASE: case lifecycle, tasks, queue, status messages, requests, risk screens, safety, costs, hold and cancel,
messages, parties and line cases (FR-CASE-001 to FR-CASE-015, RUL-17, RUL-20, RUL-31)."""
from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from audit.models import AuditEvent
from cases import services, templates
from cases.models import Case, Task
from cases.tests.helpers import accepted_case, paid_case, pdf, task
from core.errors import DomainError, Invalid
from core.models import OutboxEvent
from notifications.models import Message as Notice


def test_case_created_on_payment_with_template_version(seeded, api, people, gh):
    """US-CASE-001 AC1, TC-CASE-001-01, FR-ORD-004: a paid land order gets a case on the current template
    version; the order and the asset are linked; case.created carries the order id."""
    case = paid_case(api, people, gh)
    assert case.status == "paid" and case.product_line == "land"
    assert case.template_version.state == "published" and case.template_version.product_line == "land"
    assert case.order.case_id == case.pk and case.asset_id and case.order.asset_id == case.asset_id
    ev = OutboxEvent.objects.get(topic="case.created", aggregate_id=case.pk)
    assert ev.payload["order_id"] == str(case.order_id)
    msgs = api(people["client"]).get(f"/v1/cases/{case.pk}").json()["status_messages"]
    assert msgs and "We received your order" in msgs[0]["text"]


def test_template_change_does_not_alter_open_cases(seeded, api, people, gh):
    """US-CASE-001 AC2, TC-CASE-001-03."""
    from administration.services import create_config_version, publish_config_version

    case = paid_case(api, people, gh)
    old = case.template_version_id
    content = {"tasks": templates.LAND_TASKS + [templates._t("extra", "Extra step", "CM", 3)]}
    cv = create_config_version(kind="case_template", content=content, by=people["admin"], country=gh,
                               product_line="land")
    publish_config_version(cv, by=people["admin"])
    case.refresh_from_db()
    assert case.template_version_id == old
    services.accept(case, people["cm"])
    assert not case.tasks.filter(step_key="extra").exists()
    assert paid_case(api, people, gh).template_version_id == cv.pk


def test_missing_or_faulty_template(seeded, api, people, gh):
    """TC-CASE-001-02, TC-CASE-002-02: no template is a clear configuration error; a step with no owner role
    or evidence list is refused."""
    with pytest.raises(DomainError) as e:
        services.template_for("land", seeded["ng"])
    assert e.value.code == "case-template-missing"
    with pytest.raises(Invalid):
        templates.validate({"tasks": [{"key": "a", "title": "A", "due_days": 1, "evidence": []}]})
    with pytest.raises(Invalid):
        templates.validate({"tasks": [{"key": "a", "title": "A", "role": "CM", "due_days": 1}]})


def test_accept_creates_land_tasks_with_due_dates_and_waiting(seeded, api, people, gh):
    """US-CASE-002, TC-CASE-002-01: nine steps in order with owner role, evidence and a due date; a later step
    waits for an earlier one."""
    case = paid_case(api, people, gh)
    r = api(people["cm"]).post(f"/v1/cases/{case.pk}/accept")
    assert r.status_code == 200, r.content
    tasks = r.json()["tasks"]
    assert [t["step_key"] for t in tasks] == ["intake", "searches_lodged", "site_visit", "overlay_check",
                                               "consent_meeting", "official_search", "legal_review", "second_review",
                                               "release"]
    t = {x["step_key"]: x for x in tasks}
    assert t["site_visit"]["owner_role"] == "RN" and t["site_visit"]["required_evidence"] == ["site_photo",
                                                                                              "pillar_photo"]
    assert t["site_visit"]["waiting_for"] == ["intake"] and t["intake"]["waiting_for"] == []
    assert t["legal_review"]["due_at"] > t["intake"]["due_at"]
    assert api(people["client"]).post(f"/v1/cases/{case.pk}/accept").status_code in (403, 404)
    assert r.json()["reports"], "the report draft is built when the case starts"


def test_building_case_has_extra_steps_and_report_sections(seeded, api, people, gh):
    """US-CASE-013, TC-CASE-013-01."""
    case = accepted_case(api, people, gh, asset={"type": "building", "locality": "East Legon",
                                                 "site_plan_ref": "AMA/2019/1"})
    assert case.product_line == "building"
    keys = set(case.tasks.values_list("step_key", flat=True))
    assert {"building_permit_check", "structural_inspection", "occupancy_check", "rates_bills_check"} <= keys
    labels = list(case.reports.get().sections.order_by("position").values_list("label", flat=True))
    assert labels[9:15] == ["10", "10A", "10B", "10C", "10D", "11"]


def test_assign_and_change_due_date(seeded, api, people, gh):
    """US-CASE-003, TC-CASE-003-01, TC-CASE-003-02."""
    case = accepted_case(api, people, gh)
    cm = api(people["cm"])
    legal = task(case, "legal_review")
    r = cm.patch(f"/v1/tasks/{legal.pk}", {"assignee_id": str(people["runner"].pk)}, format="json")
    assert r.status_code == 422 and r.json()["code"] == "wrong-role"
    r = cm.patch(f"/v1/tasks/{legal.pk}", {"assignee_id": str(people["lawyer"].pk)}, format="json")
    assert r.status_code == 200 and r.json()["assignee"]["id"] == str(people["lawyer"].pk)
    assert Notice.objects.filter(person=people["lawyer"], template="task_assigned").exists()
    new = (timezone.now() + timedelta(days=30)).isoformat()
    r = cm.patch(f"/v1/tasks/{legal.pk}", {"due_at": new}, format="json")
    assert r.status_code == 422
    r = cm.patch(f"/v1/tasks/{legal.pk}", {"due_at": new, "reason": "Registry closed for a week"}, format="json")
    assert r.status_code == 200 and r.json()["due_change_reason"] == "Registry closed for a week"
    a = AuditEvent.objects.filter(action="task.due_changed", entity_id=str(legal.pk)).last()
    assert a.data["reason"] == "Registry closed for a week" and a.data["old_due_at"] and a.data["new_due_at"]


def test_licence_needed_to_assign_professional(seeded, api, people, gh):
    """RUL-20: an inspector whose licence is not verified cannot be assigned."""
    case = accepted_case(api, people, gh, asset={"type": "building", "locality": "Tema"})
    t = task(case, "structural_inspection")
    r = api(people["cm"]).patch(f"/v1/tasks/{t.pk}", {"assignee_id": str(people["inspector"].pk)}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "licence-invalid"


def test_task_needs_evidence_then_closes_from_phone(seeded, api, people, gh):
    """US-CASE-004, US-CASE-006, TC-CASE-004-01/02: refused with the missing items named; a receipt
    photographed in the browser is stored as evidence and the task closes."""
    case = accepted_case(api, people, gh)
    services.complete_task(task(case, "intake"), people["cm"])
    visit = task(case, "site_visit")
    services.record_risk_screen(case, people["cm"], task=visit, outcome="proceed")
    services.assign_task(visit, people["cm"], assignee=people["runner"])
    rn = api(people["runner"])
    r = rn.post(f"/v1/tasks/{visit.pk}/complete", {}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "task-incomplete"
    assert "site photo" in r.json()["detail"] and "pillar photo" in r.json()["detail"]
    from django.core.files.uploadedfile import SimpleUploadedFile

    for kind in ("site_photo", "pillar_photo"):
        f = SimpleUploadedFile(f"{kind}.jpg", b"\xff\xd8\xff\xe0 browser photo " + kind.encode(), "image/jpeg")
        r = rn.post(f"/v1/tasks/{visit.pk}/evidence", {"kind": kind, "file": f}, format="multipart")
        assert r.status_code == 201, r.content
    r = rn.post(f"/v1/tasks/{visit.pk}/complete", {}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert any("visited" in m.text for m in case.status_messages.all())


def test_database_refuses_done_without_evidence(seeded, api, people, gh):
    """FR-CASE-004 enforced again in PostgreSQL."""
    case = accepted_case(api, people, gh)
    t = task(case, "overlay_check")
    with pytest.raises(IntegrityError), transaction.atomic():
        Task.objects.filter(pk=t.pk).update(status="done")


def test_professionals_see_only_their_tasks_and_queue_order(seeded, api, people, gh):
    """TC-CASE-006-02, US-CASE-005: another person's task is 404; the queue is by due date, overdue first."""
    case = accepted_case(api, people, gh)
    services.complete_task(task(case, "intake"), people["cm"])
    visit = task(case, "site_visit")
    services.record_risk_screen(case, people["cm"], task=visit, outcome="proceed")
    services.assign_task(visit, people["cm"], assignee=people["runner"])
    assert api(people["surveyor"]).get(f"/v1/tasks/{visit.pk}").status_code == 404
    assert api(people["runner"]).get(f"/v1/tasks/{visit.pk}").status_code == 200
    Task.objects.filter(pk=task(case, "consent_meeting").pk).update(due_at=timezone.now() - timedelta(days=1))
    q = api(people["cm"]).get("/v1/work-queue").json()["items"]
    assert q[0]["is_overdue"] is True
    dues = [x["due_at"] for x in q if not x["is_overdue"]]
    assert dues == sorted(dues)
    mine = api(people["runner"]).get("/v1/work-queue").json()["items"]
    assert str(visit.pk) in {x["id"] for x in mine}
    assert all(x["assignee"]["id"] == str(people["runner"].pk) for x in mine)
    assert services.mark_overdue() >= 1
    assert OutboxEvent.objects.filter(topic="task.overdue").exists()


def test_status_message_has_date_and_next_date(seeded, api, people, gh):
    """US-CASE-007, TC-CASE-007-01/02: a plain message from the step template, with the dates; never blank."""
    case = accepted_case(api, people, gh)
    services.complete_task(task(case, "intake"), people["cm"])
    m = case.status_messages.order_by("-created_at").first()
    assert m.template_key == "intake" and m.next_expected_date and "{" not in m.text
    assert f"{timezone.localdate():%d %B %Y}" in m.text
    t = task(case, "searches_lodged")
    Task.objects.filter(pk=t.pk).update(client_message="")
    t.refresh_from_db()
    msg = services.post_status(case, t, "searches_lodged", t.client_message or None)
    assert msg.text and "{" not in msg.text


def test_document_request_journey(seeded, api, people, gh):
    """US-CASE-008, TC-CASE-008-01/02: in the client's tracker and home as an action; the client's upload
    closes it and the case manager is told; a representative cannot answer."""
    from accounts.models import RepresentativeGrant

    case = accepted_case(api, people, gh)
    r = api(people["cm"]).post(f"/v1/cases/{case.pk}/document-requests", {"title": "Indenture copy"}, format="json")
    assert r.status_code == 201
    rid = r.json()["id"]
    home = api(people["client"]).get("/v1/home").json()
    items = home["items"] if isinstance(home, dict) else home
    assert any(i["kind"] == "document_request" and i["needs_action"] for i in items)
    RepresentativeGrant.objects.create(client=people["client"], representative=people["family"],
                                       invited_email="auntie@example.com", subject_type="case", subject_id=case.pk,
                                       status="active")
    f = pdf(people["family"], gh)
    r = api(people["family"]).post(f"/v1/document-requests/{rid}/responses", {"evidence_id": str(f.pk)},
                                   format="json")
    assert r.status_code == 403
    ev = pdf(people["client"], gh, "indenture.pdf")
    r = api(people["client"]).post(f"/v1/document-requests/{rid}/responses", {"evidence_id": str(ev.pk)},
                                   format="json")
    assert r.status_code == 200 and r.json()["status"] == "received"
    assert Notice.objects.filter(person=people["cm"], subject__contains="Document received").exists()


def test_risk_screen_and_two_people_on_disputed_plot(seeded, api, people, gh):
    """US-CASE-009, RUL-17, TC-RUL-17-01 to 04, TC-CASE-009-01/02."""
    from geo.services import set_disputed

    case = accepted_case(api, people, gh)
    cm = api(people["cm"])
    services.complete_task(task(case, "intake"), people["cm"])
    visit = task(case, "site_visit")
    r = cm.patch(f"/v1/tasks/{visit.pk}", {"assignee_id": str(people["runner"].pk)}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "visit-not-safe"
    set_disputed(case.asset, actor=people["cm"], disputed=True, reason="Two families claim the plot")
    r = cm.post(f"/v1/cases/{case.pk}/risk-screens", {"task_id": str(visit.pk), "outcome": "proceed",
                                                       "people_required": 1}, format="json")
    assert r.status_code == 409
    r = cm.post(f"/v1/cases/{case.pk}/risk-screens", {"task_id": str(visit.pk), "outcome": "proceed_with_two",
                                                       "hazards": "Hostile occupants reported"}, format="json")
    assert r.status_code == 201 and r.json()["people_required"] == 2 and r.json()["task"] == str(visit.pk)
    r = cm.patch(f"/v1/tasks/{visit.pk}", {"assignee_id": str(people["runner"].pk)}, format="json")
    assert r.status_code == 409
    r = cm.patch(f"/v1/tasks/{visit.pk}", {"assignee_id": str(people["runner"].pk),
                                           "second_assignee_id": str(people["surveyor"].pk)}, format="json")
    assert r.status_code == 200, r.content
    r = cm.patch(f"/v1/tasks/{visit.pk}", {"second_assignee_id": None}, format="json")
    assert r.status_code == 409
    with pytest.raises(IntegrityError), transaction.atomic():
        Task.objects.filter(pk=visit.pk).update(second_assignee=None)


def test_dispute_flag_after_assignment_takes_the_visit_back(seeded, api, people, gh):
    """TC-RUL-17-04."""
    from geo.services import set_disputed

    case = accepted_case(api, people, gh)
    services.complete_task(task(case, "intake"), people["cm"])
    visit = task(case, "site_visit")
    services.record_risk_screen(case, people["cm"], task=visit, outcome="proceed")
    services.assign_task(visit, people["cm"], assignee=people["runner"])
    set_disputed(case.asset, actor=people["cm"], disputed=True, reason="Claim lodged")
    visit.refresh_from_db()
    assert visit.assignee_id is None
    assert AuditEvent.objects.filter(action="task.unassigned_for_safety", entity_id=str(visit.pk)).exists()


def test_safety_incident_is_write_only_and_restricted(seeded, api, people, gh):
    """US-CASE-010, TC-CASE-010-01/02: stored in the restricted log, case manager alerted; client and lawyer
    cannot read it; a named safety reader can, and the read is audited."""
    case = accepted_case(api, people, gh)
    services.complete_task(task(case, "intake"), people["cm"])
    visit = task(case, "site_visit")
    services.record_risk_screen(case, people["cm"], task=visit, outcome="proceed")
    services.assign_task(visit, people["cm"], assignee=people["runner"])
    r = api(people["runner"]).post(f"/v1/cases/{case.pk}/safety-incidents",
                                   {"severity": "high", "narrative": "A man with a machete chased us off."},
                                   format="json")
    assert r.status_code == 201 and "narrative" not in r.json()
    assert Notice.objects.filter(person=people["cm"], subject="Safety incident logged").exists()
    assert not AuditEvent.objects.filter(action="safety_incident.logged", data__narrative__isnull=False).exists()
    for who in ("client", "lawyer", "cm"):
        assert api(people[who]).get(f"/v1/safety-incidents?case={case.pk}").status_code == 404
    r = api(people["reviewer2"]).get(f"/v1/safety-incidents?case={case.pk}")
    assert r.status_code == 200 and "machete" in r.json()[0]["narrative"]
    assert AuditEvent.objects.filter(action="safety_incident.read", actor_id=people["reviewer2"].pk).exists()
    assert api(people["client2"]).post(f"/v1/cases/{case.pk}/safety-incidents",
                                       {"severity": "low", "narrative": "x"}, format="json").status_code == 404
    case.refresh_from_db()
    assert case.risk_flag is True


def test_costs_by_item_and_cost_per_report(seeded, api, people, gh):
    """US-CASE-011, TC-CASE-011-01, FR-PRO-010: items with amount, currency and date; PRO entries once."""
    from core.ids import uuid7

    case = accepted_case(api, people, gh)
    cm = api(people["cm"])
    for item, amt in (("lawyer", "400.00"), ("surveyor", "300.00"), ("runner", "60.00"), ("fees", "120.00"),
                      ("travel", "45.50")):
        r = cm.post(f"/v1/cases/{case.pk}/costs", {"item_type": item, "amount": {"amount": amt, "currency": "GHS"}},
                    format="json")
        assert r.status_code == 201
    sid = uuid7()
    a = services.add_cost(case, item_type="lawyer", amount="10", currency="GHS", source="pro_payable", source_id=sid)
    assert services.add_cost(case, item_type="lawyer", amount="10", currency="GHS", source="pro_payable",
                             source_id=sid).pk == a.pk
    r = cm.get(f"/v1/cases/{case.pk}/costs").json()
    assert r["totals"] == {"GHS": "935.50"}
    assert api(people["client"]).get(f"/v1/cases/{case.pk}/costs").status_code == 404
    assert api(people["cm"]).get("/v1/cost-per-report").status_code == 200


def test_hold_resume_and_cancel(seeded, api, people, gh):
    """US-CASE-012, TC-CASE-012-01/02: a reason is required, the client sees on hold, cancellation needs a refund
    decision that goes to PAY's refund (FR-PAY-004), and a released case cannot be cancelled."""
    from orders.tests.helpers import pay, place_order
    from payments.models import Refund

    c = api(people["client"])
    o = place_order(c, people["client"], gh)
    pay(c, o["id"])
    case = Case.objects.get(order_id=o["id"])
    services.accept(case, people["cm"])
    cm = api(people["cm"])
    assert cm.post(f"/v1/cases/{case.pk}/hold", {"reason": ""}, format="json").status_code == 400
    r = cm.post(f"/v1/cases/{case.pk}/hold", {"reason": "Waiting for the seller's documents"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "on_hold"
    assert "on hold" in c.get(f"/v1/cases/{case.pk}").json()["latest_status"]["text"]
    assert cm.post(f"/v1/cases/{case.pk}/resume").json()["status"] == "in_progress"
    r = cm.post(f"/v1/cases/{case.pk}/cancel", {"reason": "Seller withdrew"}, format="json")
    assert r.status_code == 400
    r = cm.post(f"/v1/cases/{case.pk}/cancel", {"reason": "Seller withdrew", "refund_decision": "refund"},
                format="json")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert Refund.objects.filter(payment__order_id=o["id"], status="requested").exists()
    assert not case.tasks.filter(status="open").exists()
    released = Case.objects.filter(status="released").first()
    assert cm.post(f"/v1/cases/{released.pk}/cancel", {"reason": "x", "refund_decision": "no_refund"},
                   format="json").status_code == 409


def test_case_messages_keep_text_out_of_sms(seeded, api, people, gh):
    """US-CASE-015, TC-CASE-015-01: the thread stays with the case; the case manager is told; the client's
    notice on SMS or WhatsApp carries no message text (US-NTF-004)."""
    case = accepted_case(api, people, gh)
    c, cm = api(people["client"]), api(people["cm"])
    assert c.post(f"/v1/cases/{case.pk}/messages", {"body": "Is the road access public?"},
                  format="json").status_code == 201
    assert Notice.objects.filter(person=people["cm"], body__contains="road access").exists()
    assert cm.post(f"/v1/cases/{case.pk}/messages", {"body": "Yes, secret detail 4471."},
                   format="json").status_code == 201
    for n in Notice.objects.filter(person=people["client"], channel__in=["sms", "whatsapp", "push"]):
        assert "4471" not in (n.body or "")
    assert [m["side"] for m in c.get(f"/v1/cases/{case.pk}/messages").json()] == ["client", "tenmina"]
    assert api(people["client2"]).post(f"/v1/cases/{case.pk}/messages", {"body": "x"},
                                       format="json").status_code == 404


def test_parties_need_national_id_checks(seeded, api, people, gh):
    """FR-ACC-013, RUL-31: parties are checked against the national identity system; none or pending blocks."""
    case = accepted_case(api, people, gh)
    r = api(people["cm"]).post(f"/v1/cases/{case.pk}/parties",
                               {"role": "seller", "name": "Kojo Owusu", "id_number": "GHA-733000111-1"},
                               format="json")
    assert r.status_code == 201 and r.json()["check"]["result"] == "match"
    services.add_party(case, people["cm"], role="grantor", name="Nana Ababio")
    services.add_party(case, people["cm"], role="consenting_party", name="Ama Down", id_number="GHA-733000112-9")
    msgs = [b["message"] for b in services.party_blockers(case)]
    assert any("no national identity check" in m for m in msgs) and any("pending" in m for m in msgs)
    assert api(people["runner"]).get(f"/v1/cases/{case.pk}/parties").status_code == 404


def test_line_case_opened_by_another_module_and_decided(seeded, api, people, gh):
    """ADR-21, FR-FEE-001 path: open_case starts in progress; the decision needs every check done."""
    from core.ids import uuid7

    sid = uuid7()
    case = services.open_case("institution_verification", gh, "institution", sid, client=people["client"],
                              actor=people["cm"])
    assert case.status == "in_progress" and case.tasks.count() == 5
    assert services.open_case("institution_verification", gh, "institution", sid).pk == case.pk
    rv = api(people["reviewer"])
    r = rv.post(f"/v1/cases/{case.pk}/decisions", {"outcome": "verified"}, format="json")
    assert r.status_code == 409
    for t in case.tasks.filter(review_step=False):
        if t.site_visit:
            services.record_risk_screen(case, people["cm"], task=t, outcome="proceed")
        for k in t.required_evidence:
            services.attach_task_evidence(t, people["cm"], pdf(people["cm"], gh, k), k)
        services.complete_task(t, people["cm"])
    r = rv.post(f"/v1/cases/{case.pk}/decisions", {"outcome": "verified", "note": "All good"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "completed" and r.json()["outcome"] == "verified"
    ev = OutboxEvent.objects.filter(topic="case.status_changed", aggregate_id=case.pk).last()
    assert ev.payload["outcome"] == "verified" and ev.payload["subject_id"] == str(sid)


def test_field_inbox_and_client_home(seeded, api, people, gh):
    """Registries: the runner's Tenmina Field inbox shows the task with the search notice; the client's home
    shows the case."""
    from mobile import inbox

    case = accepted_case(api, people, gh)
    services.complete_task(task(case, "intake"), people["cm"])
    visit = task(case, "site_visit")
    services.record_risk_screen(case, people["cm"], task=visit, outcome="proceed")
    services.assign_task(visit, people["cm"], assignee=people["runner"])
    it = inbox.find(people["runner"], "task", visit.pk)
    assert it is not None and it.details["notice"] == templates.SEARCH_NOTICE
    assert {r["key"] for r in it.required_evidence} == {"site_photo", "pillar_photo"}
    home = api(people["client"]).get("/v1/home").json()
    items = home["items"] if isinstance(home, dict) else home
    assert any(i["kind"] == "case" and i["id"] == str(case.pk) for i in items)
    assert api(people["client2"]).get(f"/v1/cases/{case.pk}").status_code == 404
    assert api(people["runner"]).get(f"/v1/cases/{case.pk}").json()["tasks"][0]["id"] == str(visit.pk)
