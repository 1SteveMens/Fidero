"""INS demo data through the real services: a licensed insurer partner with its verified payee (escrow's seed),
Tenmina's intermediary licence [TO VERIFY], two products, and applications, policies, premiums and a claim in
several states. Every premium and date is a synthetic figure [TO VERIFY]."""
from datetime import timedelta

from django.utils import timezone


def _doc(gh, by, name):
    from core.ids import uuid7
    from evidence.services import store

    return store(data=b"%PDF-1.4 " + f"Demo document: {name} ".encode() + uuid7().bytes, country=gh, uploaded_by=by,
                 content_type="application/pdf", original_name=f"{name}.pdf", description=name,
                 data_class="insurance")


def run(ctx):
    from administration import flags
    from administration.models import Partner

    from . import services
    from .models import Insurer

    gh, people = ctx["gh"], ctx["people"]
    refs = ctx.setdefault("insurance", {})
    if not flags.enabled("lines.ins", gh):
        return
    existing = Insurer.objects.filter(country=gh).first()
    if existing is not None:
        refs["insurer"] = existing
        return
    partner = Partner.objects.filter(country=gh, kind="insurer", status="active").first()
    payee = (ctx.get("escrow") or {}).get("payees", {}).get("insurer")
    org = (ctx.get("orgs") or {}).get("insurer")
    if partner is None or payee is None:
        return
    admin, cm, client, insurer_user = people["admin"], people["cm"], people["client"], people["insurer"]
    today = timezone.localdate()
    ins = services.create_insurer(admin, country=gh, partner=partner, organisation=org,
                                  licence_body="National Insurance Commission [TO VERIFY]",
                                  licence_number="NIC/DEMO/0001", licence_valid_until=today + timedelta(days=365),
                                  licence_evidence=_doc(gh, admin, "insurer-licence"),
                                  claim_contact="Claims desk +233302000123, claims@insurer.example [demo]",
                                  routes=["client_direct_to_insurer", "held_funds_to_insurer"], payee=payee)
    refs["insurer"] = ins
    services.record_intermediary_licence(admin, country=gh, body="National Insurance Commission [TO VERIFY]",
                                         reference="NIC/INT/DEMO/0007", valid_until=today + timedelta(days=365),
                                         evidence=_doc(gh, admin, "intermediary-licence"))
    health = services.create_product(cm, insurer=ins, kind="health", name="Family Health Cover (demo)",
                                     terms_evidence=_doc(gh, cm, "health-policy-terms"), premium_amount="85.00",
                                     premium_currency="GHS", premium_period="month",
                                     summary="Hospital stays and outpatient care at partner hospitals [TO VERIFY].",
                                     application_questions=[{"key": "date_of_birth", "label": "Date of birth",
                                                             "required": True},
                                                            {"key": "conditions", "label": "Known conditions",
                                                             "required": False}])
    funeral = services.create_product(cm, insurer=ins, kind="funeral", name="Funeral Cover (demo)",
                                      terms_evidence=_doc(gh, cm, "funeral-policy-terms"), premium_amount="30.00",
                                      premium_currency="GHS", premium_period="month",
                                      summary="A lump sum paid by the insurer to the funeral home [TO VERIFY].")
    services.publish_product(health, admin)
    services.publish_product(funeral, admin)
    refs["products"] = {"health": health, "funeral": funeral}
    fams = ctx.get("family_members") or {}
    mother, nephew = fams.get("mother"), fams.get("nephew")
    if mother is None:
        return
    # 1. Accepted health cover, the client pays the insurer directly; renews soon; one claim being assessed.
    a1 = services.apply(client, product=health, family_member=mother,
                        answers={"date_of_birth": "1958-03-14", "conditions": "Hypertension"},
                        premium_route="client_direct_to_insurer")
    services.submit_application(a1, client)
    pol1 = services.record_outcome(a1, insurer_user, outcome="accepted", policy_number="FHC-DEMO-000101",
                                   document_evidence=_doc(gh, insurer_user, "policy-FHC-DEMO-000101"),
                                   starts_on=today - timedelta(days=340), renews_on=today + timedelta(days=25),
                                   note="Accepted with a waiting period of 3 months [demo]")
    c = services.start_claim(pol1, client, description="Admitted to hospital for three nights [demo]",
                             event_date=today - timedelta(days=6))
    services.record_claim_update(c, insurer_user, insurer_status="assessing",
                                 note="We have the discharge summary and are assessing [demo].")
    refs["policy_health"] = pol1
    # 2. Accepted funeral cover, paid by the bank from held funds; the premium waits for approvals.
    if nephew is not None:
        a2 = services.apply(client, product=funeral, family_member=mother, premium_route="held_funds_to_insurer")
        services.submit_application(a2, client)
        pol2 = services.record_outcome(a2, insurer_user, outcome="accepted", policy_number="FUN-DEMO-000202",
                                       document_evidence=_doc(gh, insurer_user, "policy-FUN-DEMO-000202"),
                                       starts_on=today, renews_on=today + timedelta(days=365))
        refs["policy_funeral"] = pol2
        pm = pol2.premiums.first()
        try:
            services.instruct_premium(pm, cm)
        except Exception:  # noqa: BLE001 - demo extras never stop the seed
            import logging

            logging.getLogger("insurance").exception("premium instruction skipped")
    # 3. An application waiting for the insurer.
    a3 = services.apply(people["client2"], product=health,
                        family_member=_member(people["client2"], gh), answers={"date_of_birth": "1950-01-01"})
    services.submit_application(a3, people["client2"])


def _member(client, gh):
    from accounts.models import FamilyMember

    fm = FamilyMember.objects.filter(client=client, status="active").first()
    if fm is None:
        fm = FamilyMember.objects.create(country=gh, client=client, full_name="Esi Boateng", relationship="mother",
                                         phone="+233240000201", address="Kumasi [demo]")
    return fm
