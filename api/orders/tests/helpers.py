"""Helpers shared by the ORD and PAY tests."""
from evidence.services import store
from orders import legal


def site_plan(person, country, data=b"%PDF-1.4 site plan for plot 12"):
    return store(data=data, country=country, uploaded_by=person, content_type="application/pdf",
                 original_name="site-plan.pdf")


def terms(country):
    t = legal.current(country)
    return {"accept_terms": True, "terms_version": t["terms_version"], "scope_version": t["scope_version"]}


def order_body(country, **over):
    body = {"country": country.code, "kind": "verification", "tier": "standard",
            "asset": {"type": "plot", "locality": "Kasoa", "plot_number": "12", "site_plan_ref": "SP-2026-118"},
            "seller": {"name": "Kojo Owusu", "phone": "+233200000001"}, "lead_source": "webinar",
            **terms(country)}
    body.update(over)
    return body


def place_order(client, person, country, **over):
    """POST /v1/orders as `person` with a site plan; returns the response JSON (asserts 201)."""
    ev = site_plan(person, country)
    body = order_body(country, upload_ids=[str(ev.pk)], **over)
    r = client.post("/v1/orders", body, format="json")
    assert r.status_code == 201, r.content
    return r.json()


def start_payment(client, order_id, method="card", **extra):
    r = client.post(f"/v1/orders/{order_id}/payments", {"method": method, **extra}, format="json")
    assert r.status_code == 201, r.content
    return r.json()["payment"]


def checkout(client, payment_id, outcome="success", refundable=True):
    r = client.post(f"/v1/payments/{payment_id}/fake-checkout", {"outcome": outcome, "refundable": refundable},
                    format="json")
    assert r.status_code == 200, r.content
    return r.json()


def pay(client, order_id, method="card", outcome="success", refundable=True):
    p = start_payment(client, order_id, method)
    return checkout(client, p["id"], outcome, refundable)
