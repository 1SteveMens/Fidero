"""PRO test helpers. Seeds load once per session (api/conftest.py); fetch objects
fresh by primary key rather than relying on an instance another test changed."""
import itertools
import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

_seq = itertools.count(1)


class Pro:
    def __init__(self, ctx):
        from profpay.models import Agreement

        self.ctx = ctx
        self.gh = ctx["gh"]
        self.p = ctx["people"]
        self.cm, self.rv, self.rv2 = self.p["cm"], self.p["reviewer"], self.p["reviewer2"]
        self.admin, self.admin2 = self.p["admin"], self.p["admin2"]
        self.lawyer, self.surveyor, self.runner = self.p["lawyer"], self.p["surveyor"], self.p["runner"]
        self.agr = {k: Agreement.objects.get(pk=ctx["pro"][k].pk) for k in ("lawyer", "surveyor", "runner",
                                                                           "inspector")}

    def ev(self, name="doc", by=None, data=None):
        from evidence.services import store

        n = next(_seq)
        return store(data=data or f"Evidence {name} {n} {uuid.uuid4()}".encode(), country=self.gh,
                     uploaded_by=by or self.cm, content_type="text/plain", original_name=f"{name}-{n}.txt",
                     data_class="payables")

    def work(self, person, role, kind="recheck", *, ref=None, days_ago=1, assigned_days_ago=5, case=None,
             country="GH", **extra):
        from profpay import services

        now = timezone.now()
        payload = {"work_kind": kind, "work_ref": str(ref or uuid.uuid4()), "person_id": str(person.pk),
                   "role": role, "country": country, "quantity": 1,
                   "assigned_at": (now - timedelta(days=assigned_days_ago)).isoformat(),
                   "accepted_at": (now - timedelta(days=days_ago)).isoformat(), **extra}
        if case is not None:
            payload["case_id"] = str(case.pk)
        return services.record_work_accepted(payload, event_id=uuid.uuid4())

    def clear_pending_runs(self):
        """Withdraw the seeded run waiting for approval so its items can join a new run."""
        from profpay import services
        from profpay.models import PaymentRun

        for r in PaymentRun.objects.filter(status__in=["draft", "pending_approval"]):
            services.withdraw_run(r, self.cm, reason="test")

    def approve_run(self, run, approver=None):
        from core import approvals

        run.refresh_from_db()
        approvals.decide(run.approval_request, approver or self.rv, mfa_at=timezone.now())
        run.refresh_from_db()
        return run


@pytest.fixture
def pro(seeded):
    return Pro(seeded)
