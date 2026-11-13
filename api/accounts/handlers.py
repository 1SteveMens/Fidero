"""ACC event subscribers. Idempotent: each acts only on objects still waiting."""
from core.events import subscribe

from . import services
from .models import BankAccount, RightsRequest

RIGHTS_SUBJECTS = ("release_rights_grant", "payment_rights_grant")


@subscribe("approval.approved", "approval.rejected")
def on_approval_closed(ev):
    st = ev.payload.get("subject_type")
    sid = ev.payload.get("subject_id")
    approved = ev.topic == "approval.approved"
    if st in RIGHTS_SUBJECTS:
        rr = RightsRequest.objects.filter(pk=sid, status="pending").first()
        if rr is None:
            return
        if approved:
            services.apply_rights(rr)
        else:
            from core import state

            state.transition(rr, "rights_request", "rejected")
    elif st == "bank_account_verification":
        acct = BankAccount.objects.filter(pk=sid, verification_status="pending").first()
        if acct is not None and str(acct.approval_request_id) == str(ev.payload.get("request_id")):
            services.apply_bank_verification(acct, approved)


@subscribe("person.registered")
def on_person_registered(ev):
    from .models import Person

    p = Person.objects.filter(pk=ev.payload.get("person_id")).first()
    if p is not None:
        services.link_pending_representatives(p)
