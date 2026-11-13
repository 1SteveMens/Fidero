"""API journeys and object scoping (02 7.4, 7.6): J-02 end to end, held funds, payees, exchange."""
import uuid

from core.events import publish
from escrow.models import BankEvent, Escrow, ReleaseInstruction


def _money(amount, currency="GHS"):
    return {"amount": amount, "currency": currency}


def test_j02_buy_through_escrow_over_the_api(b, api, mfa):
    """J-02, US-ESC-001 to 009: proposed, agreed, funded, conditions, client and two staff, sent, released."""
    cm, client, seller = api(b.cm), api(b.client), api(b.p["seller"])
    report_id = uuid.uuid4()
    publish("report.released", report_id, {"report_id": str(report_id), "country": "GH", "verdict": "amber",
                                           "client_id": str(b.client.pk), "asset_id": str(uuid.uuid4()),
                                           "conditions": [{"id": str(uuid.uuid4()), "text": "Family consent"}]})
    seller_payee = b.payee("seller")
    r = cm.post("/v1/escrows", {"kind": "purchase", "country": "GH", "client_id": str(b.client.pk),
                                "agreed_price": _money("250000.00"), "report_id": str(report_id),
                                "parties": [{"role": "seller", "person_id": str(b.p["seller"].pk),
                                             "payee_id": str(seller_payee.pk),
                                             "national_id_check_id": str(seller_payee.national_id_check_id)}]},
                format="json")
    assert r.status_code == 201, r.content
    eid = r.json()["id"]
    assert r.json()["conditions"][0]["text"] == "Family consent"
    assert client.post(f"/v1/escrows/{eid}/acceptances", {}, format="json").status_code == 201
    assert seller.post(f"/v1/escrows/{eid}/acceptances", {}, format="json").status_code == 201
    assert cm.post(f"/v1/escrows/{eid}/acceptances", {}, format="json").status_code == 201
    r = cm.post(f"/v1/escrows/{eid}/virtual-account", {"virtual_account_ref": f"VA-API-{eid[:8]}"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "agreed", r.content
    r = client.get(f"/v1/escrows/{eid}")
    assert r.json()["payment_instructions"]["available"] is True
    proof = b.ev("credit-advice")
    r = cm.post(f"/v1/escrows/{eid}/bank-events", {
        "kind": "deposit", "amount": _money("250000.00"), "bank_reference": "API-DEP-1",
        "proof_evidence_id": str(proof.pk), "source_bank_name": "NatWest", "source_account_number": "GB11",
        "source_account_name": "AMA MENSAH"}, format="json")
    assert r.status_code == 201 and r.json()["status"] == "pending_check", r.content
    rv = api(b.rv)
    assert cm.post(f"/v1/bank-events/{r.json()['id']}/check", {}, format="json").status_code == 403
    r = rv.post(f"/v1/bank-events/{r.json()['id']}/check", {}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "confirmed"
    e = Escrow.objects.get(pk=eid)
    for c in e.conditions.all():
        r = cm.post(f"/v1/escrows/{eid}/conditions/{c.pk}/close", {"evidence_ids": [str(b.ev("consent").pk)]},
                    format="json")
        assert r.status_code == 200, r.content
    today = str(b.now().date())
    r = cm.post(f"/v1/escrows/{eid}/fresh-search", {"case_id": str(uuid.uuid4()), "registry_result_date": today,
                                                   "site_check_date": today}, format="json")
    assert r.json()["status"] == "ready_to_release"
    r = cm.post(f"/v1/escrows/{eid}/release-instructions", {}, format="json")
    assert r.status_code == 201, r.content
    iid = r.json()["id"]
    other = api(b.new_client())
    assert other.get(f"/v1/escrows/{eid}").status_code == 404
    assert other.get(f"/v1/release-instructions/{iid}").status_code == 404
    assert client.post(f"/v1/release-instructions/{iid}/client-approval", {}, format="json").status_code == 401
    mfa(client, b.client)
    r = client.post(f"/v1/release-instructions/{iid}/client-approval", {"gesture": "press_and_hold"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "pending_approval", r.content
    for person in (b.rv, b.rv2):
        c = api(person)
        mfa(c, person)
        r = c.post(f"/v1/release-instructions/{iid}/approvals",
                   {"decision": "approve", "confirm_amount": _money("250000.00")}, format="json",
                   HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
        assert r.status_code == 200, r.content
    assert r.json()["status"] == "sent" and r.json()["dispatch"]["status"] == "sent"
    assert len(r.json()["approvals"]) == 2
    r = cm.post(f"/v1/escrows/{eid}/bank-events", {
        "kind": "release_confirmed", "amount": _money("250000.00"), "bank_reference": "API-PAY-1",
        "proof_evidence_id": str(b.ev("debit").pk), "instruction_id": iid}, format="json")
    assert r.status_code == 201, r.content
    rv.post(f"/v1/bank-events/{r.json()['id']}/check", {}, format="json")
    assert client.get(f"/v1/escrows/{eid}").json()["status"] == "released"
    r = client.get(f"/v1/escrows/{eid}/funds")
    assert r.status_code == 200 and r.json()[0]["held_at_bank"] == "0.00"
    assert client.get(f"/v1/escrows/{eid}/statement").status_code == 200


def test_release_blocked_problem_response(b, api):
    """7.2: 409 release-blocked with every blocking reason."""
    e = b.agree(b.purchase())
    b.deposit(e, "100000.00")
    r = api(b.cm).post(f"/v1/escrows/{e.pk}/release-instructions", {}, format="json")
    assert r.status_code == 409
    body = r.json()
    assert body["code"] == "release-blocked"
    assert {x["code"] for x in body["blocking_reasons"]} >= {"condition-open", "fresh-search-missing"}


def test_client_cannot_act_as_staff(b, api):
    """10.4: a client cannot record bank events, close conditions or prepare releases."""
    e = b.agree(b.purchase())
    c = api(b.client)
    assert c.post(f"/v1/escrows/{e.pk}/bank-events", {}, format="json").status_code == 403
    cid = e.conditions.first().pk
    assert c.post(f"/v1/escrows/{e.pk}/conditions/{cid}/close", {"evidence_ids": []}, format="json") \
        .status_code == 403
    assert c.post(f"/v1/escrows/{e.pk}/release-instructions", {}, format="json").status_code == 404


def test_held_funds_over_the_api(b, api, mfa):
    """FR-ESC-014, FR-ACC-012: a client opens held funds; an approval waiting shows on the home screen."""
    person = b.new_client()
    c = api(person)
    r = c.post("/v1/held-funds", {"country": "GH"}, format="json")
    assert r.status_code == 201, r.content
    hf = Escrow.objects.get(pk=r.json()["id"])
    assert hf.kind == "held_funds" and hf.acceptances.exists()
    from escrow import services

    services.record_virtual_account(hf, b.cm, virtual_account_ref=f"VA-HF-API-{hf.reference}")
    b.deposit(Escrow.objects.get(pk=hf.pk), "900.00")
    ins = services.request_release(Escrow.objects.get(pk=hf.pk), requested_by=b.cm, payee=b.payee("school"),
                                   amount="300.00", subject_type="fee_invoice", subject_id=uuid.uuid4(),
                                   subject_label="Term 2 fees")
    home = c.get("/v1/home").json()
    items = home if isinstance(home, list) else home.get("items", [])
    assert any(i["kind"] == "release_approval" and i["needs_action"] for i in items)
    assert c.get("/v1/held-funds").json()[0]["id"] == str(hf.pk)
    mfa(c, person)
    assert c.post(f"/v1/release-instructions/{ins.pk}/client-approval", {}, format="json").status_code == 200
    r = c.get(f"/v1/escrows/{hf.pk}/statement")
    assert any(line["subject_label"] == "Term 2 fees" for line in r.json()["lines"])


def test_payee_bank_details_cannot_be_edited_over_the_api(b, api):
    """RUL-28, TC-ESC-016-02: the API refuses a direct edit and any change from a message."""
    p = b.payee("seller")
    r = api(b.cm).patch(f"/v1/payees/{p.pk}", {"account_number": "5550001112223"}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "payee-locked"
    r = api(b.cm).patch(f"/v1/payees/{p.pk}", {"contact_phone": "+233200009999"}, format="json")
    assert r.status_code == 200
    r = api(b.p["seller"]).post(f"/v1/payees/{p.pk}/changes", {
        "kind": "new_account", "reason": "Sent by WhatsApp", "request_source": "whatsapp",
        "account_number": "5550001112223", "account_name_source": "bank_name_check"}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "payee-change-source"
    assert api(b.client).get("/v1/payees").status_code == 403


def test_exchange_endpoints(b, api):
    """FR-ESC-021, FR-ESC-024: routes for the client; the comparison is public."""
    from escrow import services

    e = b.agree(b.purchase())
    services.collect_rates(b.gh)
    r = api(b.client).get(f"/v1/escrows/{e.pk}/deposit-routes?currency=USD&amount=2000")
    assert r.status_code == 200 and r.json()["routes"]
    r = api().get("/v1/fx/comparison?country=GH&from=USD")
    assert r.status_code == 200 and r.json()
    r = api(b.client).post(f"/v1/escrows/{e.pk}/fx-quotes", {"route": "escrow_local_account",
                                                             "amount": _money("100.00", "USD")}, format="json")
    assert r.status_code == 201 and r.json()["tenmina_margin"] == "0.00"


def test_release_clock_queue(b, api):
    """FR-ESC-018: case managers see releases in progress."""
    from escrow import services

    e = b.ready_purchase()
    services.request_release(e, requested_by=b.cm)
    r = api(b.cm).get("/v1/release-instructions?clock=in_progress")
    assert r.status_code == 200 and r.json()["items"]
    assert api(b.client).get("/v1/release-instructions?clock=in_progress").status_code == 404


def test_programme_account_admin(b, api, mfa):
    """RUL-34, FR-ADM-003: an administrator records the account; a second administrator approves."""
    from administration.models import Partner

    bank = Partner.objects.filter(country=b.gh, kind="escrow_bank").first()
    a = api(b.p["admin"])
    r = a.post("/v1/admin/programme-accounts", {
        "country": "GH", "bank_partner_id": str(bank.pk), "currency": "EUR", "account_number": "9040009999999",
        "account_name": "Partner Bank Escrow EUR", "agreement_evidence_id": str(b.ev("agreement").pk)},
        format="json")
    assert r.status_code == 201 and r.json()["status"] == "pending", r.content
    a2 = api(b.p["admin2"])
    mfa(a2, b.p["admin2"])
    r = a2.post(f"/v1/admin/programme-accounts/{r.json()['id']}/approvals", {"decision": "approve"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "active"
    assert api(b.cm).get("/v1/admin/programme-accounts").status_code == 403


def test_no_bank_event_without_instruction(b):
    """FR-ESC-009 AC2: nothing is marked released without a sent instruction."""
    assert not BankEvent.objects.filter(kind="release_confirmed", instruction__isnull=True).exists()
    assert not ReleaseInstruction.objects.filter(status="confirmed", bank_confirmation_event__isnull=True) \
        .exclude(kind="conversion").exists()
