"""PRO API (02 section 7.4). A professional sees only their own agreement,
jobs, payables, expenses and statements ("My pay"); staff are scoped to their
country role grants; payment rights (PY) are checked inside the approval
component. No response carries a verdict or outcome (RUL-26)."""
import base64
import binascii
from datetime import date

from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from core.errors import Forbidden, Invalid, NotFound
from core.idempotency import idempotent
from core.permissions import PROFESSIONAL_ROLES, has_role
from core.views import require_mfa

from . import selectors, services
from .models import Agreement, Document, ExpenseClaim, Payable, PaymentLine, PaymentRun, RateCard, Scope
from .serializers import (ProAgreementIn, ProAgreementSerializer, ProAgreementUpdate, ProConfirmationIn,
                          ProCostRow, ProCountIn, ProDecisionIn, ProDocumentSerializer, ProEndIn, ProExpenseIn,
                          ProExpenseSerializer, ProHoldIn, ProJobSerializer, ProLetterCheckIn, ProLineSerializer,
                          ProMyAgreementSerializer, ProNoteIn, ProPayableSerializer, ProRateCardIn,
                          ProRateCardSerializer, ProRateCardUpdate, ProReasonIn, ProResolutionIn,
                          ProRunDetailSerializer, ProRunIn, ProRunSerializer, ProScopeSerializer, ProStatementsIn)

STAFF = ("CM", "RV", "AD")


def _valid(cls, request, partial=False):
    s = cls(data=request.data, partial=partial, context={"request": request})
    s.is_valid(raise_exception=True)
    return s.validated_data


def _country(code):
    from countries.models import Country

    c = Country.objects.filter(code=str(code or "").upper()).first()
    if c is None:
        raise Invalid("Unknown country.", code="validation-error")
    return c


def _get(model, pk, **filters):
    obj = model.objects.filter(pk=pk, **filters).first() if pk else None
    if obj is None:
        raise NotFound()
    return obj


def _evidence(pk, required=True):
    from evidence.models import Evidence

    if not pk:
        if required:
            raise Invalid("Attach the document.", code="validation-error")
        return None
    return _get(Evidence, pk)


def _scope(qs, user, roles=STAFF):
    from accounts.selectors import scope_to_staff_countries

    if not has_role(user, *roles):
        return qs.none()
    return scope_to_staff_countries(qs, user, roles=roles)


def _require_professional(user):
    if not getattr(user, "is_authenticated", False) or not has_role(user, *PROFESSIONAL_ROLES):
        raise Forbidden("My pay is for professionals Tenmina contracts.")


# =========================================================================== My pay (PR own)

@extend_schema(tags=["pro"], responses=ProMyAgreementSerializer(many=True))
@api_view(["GET"])
def my_agreement(request):
    """My agreement, current rate card and verified payee account (last four digits)."""
    _require_professional(request.user)
    qs = selectors.agreements_of(request.user).exclude(status="draft")
    return Response(ProMyAgreementSerializer(qs, many=True).data)


@extend_schema(tags=["pro"], responses=ProJobSerializer(many=True))
@api_view(["GET"])
def my_jobs(request):
    """My accepted and pending work with the rate that applies; never the verdict or outcome (RUL-26)."""
    _require_professional(request.user)
    return Response(selectors.my_jobs(request.user))


class MyPayableViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ProPayableSerializer
    queryset = Payable.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Payable.objects.none()
        _require_professional(self.request.user)
        return selectors.payables_of(self.request.user).select_related("country", "case", "country_config")


class MyExpenseViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ProExpenseSerializer
    queryset = ExpenseClaim.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ExpenseClaim.objects.none()
        _require_professional(self.request.user)
        return selectors.claims_of(self.request.user).select_related("country", "claimant")

    @extend_schema(request=ProExpenseIn, responses={201: ProExpenseSerializer})
    @idempotent
    def create(self, request):
        """Claim an expense with a receipt photo (US-PRO-004)."""
        from cases.models import Case

        _require_professional(request.user)
        d = _valid(ProExpenseIn, request)
        agreement = _get(Agreement, d["agreement_id"], professional=request.user) if d.get("agreement_id") else None
        case = _get(Case, d["case_id"]) if d.get("case_id") else None
        c = services.submit_claim(
            request.user, kind=d["kind"], description=d["description"], amount=d["amount"],
            incurred_on=d["incurred_on"], receipt_evidence=_evidence(d.get("receipt_evidence_id"), required=False),
            case=case, project_id=d.get("project_id"), errand_id=d.get("errand_id"), agreement=agreement,
            currency=d.get("currency"))
        return Response(ProExpenseSerializer(c).data, status=201)

    @extend_schema(request=None, responses=ProExpenseSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        c = services.cancel_claim(self.get_object(), request.user)
        return Response(ProExpenseSerializer(c).data)


class MyStatementViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ProDocumentSerializer
    queryset = Document.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Document.objects.none()
        _require_professional(self.request.user)
        return Document.objects.filter(agreement__professional=self.request.user).select_related(
            "evidence", "payment_line")

    @extend_schema(responses={(200, "application/pdf"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"])
    def pdf(self, request, pk=None):
        doc = self.get_object()
        resp = HttpResponse(services.document_bytes(doc), content_type="application/pdf")
        resp["Content-Disposition"] = f'attachment; filename="{doc.evidence.original_name}"'
        resp["X-Content-SHA256"] = doc.evidence.sha256
        return resp


# =========================================================================== agreements (AD, CM)

class AgreementViewSet(viewsets.GenericViewSet):
    serializer_class = ProAgreementSerializer
    queryset = Agreement.objects.none()

    def get_queryset(self):
        qs = _scope(Agreement.objects.select_related("country", "professional", "payee", "bank_account"),
                    self.request.user, ("AD", "CM", "RV"))
        p = self.request.query_params
        for f in ("role", "status"):
            if p.get(f):
                qs = qs.filter(**{f: p[f]})
        if p.get("professional"):
            qs = qs.filter(professional_id=p["professional"])
        return qs

    @extend_schema(parameters=[OpenApiParameter("role", str), OpenApiParameter("status", str),
                               OpenApiParameter("professional", str)])
    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(ProAgreementSerializer(page, many=True).data)

    def retrieve(self, request, pk=None):
        return Response(ProAgreementSerializer(self.get_object()).data)

    def _refs(self, d):
        from accounts.models import BankAccount, Organisation, Person
        from escrow.models import Payee

        out = {}
        if "professional_id" in d:
            out["professional"] = _get(Person, d["professional_id"])
        if d.get("organisation_id"):
            out["organisation"] = _get(Organisation, d["organisation_id"])
        if "payee_id" in d:
            out["payee"] = _get(Payee, d["payee_id"]) if d["payee_id"] else None
        if "bank_account_id" in d:
            out["bank_account"] = _get(BankAccount, d["bank_account_id"]) if d["bank_account_id"] else None
        return out

    @extend_schema(request=ProAgreementIn, responses={201: ProAgreementSerializer})
    @idempotent
    def create(self, request):
        d = _valid(ProAgreementIn, request)
        refs = self._refs(d)
        a = services.create_agreement(
            request.user, country=_country(d["country"]), professional=refs["professional"], role=d["role"],
            agreement_evidence=_evidence(d["agreement_evidence_id"]), contracting_party=d["contracting_party"],
            organisation=refs.get("organisation"), tax_status=d["tax_status"], tax_id=d.get("tax_id", ""),
            payee=refs.get("payee"), bank_account=refs.get("bank_account"), valid_from=d.get("valid_from"),
            valid_to=d.get("valid_to"))
        return Response(ProAgreementSerializer(a).data, status=201)

    @extend_schema(request=ProAgreementUpdate, responses=ProAgreementSerializer)
    def partial_update(self, request, pk=None):
        d = _valid(ProAgreementUpdate, request)
        data = {k: v for k, v in d.items() if k not in ("payee_id", "bank_account_id")}
        data.update(self._refs(d))
        a = services.update_agreement(self.get_object(), request.user, data)
        return Response(ProAgreementSerializer(a).data)

    @extend_schema(request=None, responses=ProAgreementSerializer)
    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        return Response(ProAgreementSerializer(services.activate_agreement(self.get_object(), request.user)).data)

    @extend_schema(request=ProReasonIn, responses=ProAgreementSerializer)
    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        d = _valid(ProReasonIn, request)
        return Response(ProAgreementSerializer(services.suspend_agreement(self.get_object(), request.user,
                                                                          d["reason"])).data)

    @extend_schema(request=None, responses=ProAgreementSerializer)
    @action(detail=True, methods=["post"])
    def reinstate(self, request, pk=None):
        return Response(ProAgreementSerializer(services.reinstate_agreement(self.get_object(), request.user)).data)

    @extend_schema(request=ProEndIn, responses=ProAgreementSerializer)
    @action(detail=True, methods=["post"])
    def end(self, request, pk=None):
        d = _valid(ProEndIn, request)
        return Response(ProAgreementSerializer(services.end_agreement(
            self.get_object(), request.user, reason=d["reason"], valid_to=d.get("valid_to"))).data)


# =========================================================================== rate cards (AD)

class RateCardViewSet(viewsets.GenericViewSet):
    serializer_class = ProRateCardSerializer
    queryset = RateCard.objects.none()

    def get_queryset(self):
        qs = _scope(RateCard.objects.select_related("country"), self.request.user, ("AD", "CM", "RV"))
        p = self.request.query_params
        for f in ("role", "unit", "state"):
            if p.get(f):
                qs = qs.filter(**{f: p[f]})
        return qs

    @extend_schema(parameters=[OpenApiParameter("role", str), OpenApiParameter("unit", str),
                               OpenApiParameter("state", str)])
    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(ProRateCardSerializer(page, many=True).data)

    def retrieve(self, request, pk=None):
        return Response(ProRateCardSerializer(self.get_object()).data)

    @extend_schema(request=ProRateCardIn, responses={201: ProRateCardSerializer})
    @idempotent
    def create(self, request):
        d = _valid(ProRateCardIn, request)
        agreement = _get(Agreement, d["agreement_id"]) if d.get("agreement_id") else None
        card = services.draft_rate_card(request.user, country=_country(d["country"]), role=d["role"],
                                        unit=d["unit"], rate=d["rate"], valid_from=d["valid_from"],
                                        scope_key=d.get("scope_key") or "standard", agreement=agreement,
                                        currency=d.get("currency"))
        return Response(ProRateCardSerializer(card).data, status=201)

    @extend_schema(request=ProRateCardUpdate, responses=ProRateCardSerializer)
    def partial_update(self, request, pk=None):
        d = _valid(ProRateCardUpdate, request)
        card = services.update_rate_card(self.get_object(), request.user, rate=d.get("rate"),
                                         valid_from=d.get("valid_from"))
        return Response(ProRateCardSerializer(card).data)

    @extend_schema(request=ProDecisionIn, responses=ProRateCardSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def approvals(self, request, pk=None):
        """A second administrator approves the version, with MFA (US-PRO-001 AC2)."""
        d = _valid(ProDecisionIn, request)
        card = self.get_object()
        services.decide_rate_card(card, request.user, decision=d["decision"], mfa_at=require_mfa(request),
                                  note=d.get("note", ""))
        card.refresh_from_db()
        return Response(ProRateCardSerializer(card).data)

    @extend_schema(request=None, responses=ProRateCardSerializer)
    @action(detail=True, methods=["post"])
    def retire(self, request, pk=None):
        return Response(ProRateCardSerializer(services.retire_rate_card(self.get_object(), request.user)).data)


@extend_schema(tags=["pro"], responses=ProScopeSerializer(many=True))
@api_view(["GET"])
def scopes(request):
    """The fixed scope keys a rate may vary by: all known at assignment (RUL-26)."""
    if not has_role(request.user, *STAFF):
        raise Forbidden()
    return Response(ProScopeSerializer(Scope.objects.order_by("key"), many=True).data)


# =========================================================================== runner months (CM)

@extend_schema(tags=["pro"], request=None, responses={201: ProPayableSerializer})
@api_view(["POST"])
def close_runner_month(request, agreement_id, month):
    """Close a runner's month; creates the month's payable (FR-PRO-002 AC4). `month` is YYYY-MM."""
    try:
        m = date.fromisoformat(f"{month}-01")
    except ValueError as exc:
        raise Invalid("Give the month as YYYY-MM.", code="validation-error") from exc
    a = _get(Agreement, agreement_id)
    rm = services.close_runner_month(a, m, request.user)
    p = Payable.objects.filter(work_kind="runner_month", work_ref=a.pk, work_period=rm.month).first()
    if p is None:
        return Response({"runner_month_id": str(rm.pk), "payable": None,
                         "detail": "The month is closed. No approved monthly rate was in force, so operations "
                                   "was alerted."}, status=201)
    return Response(ProPayableSerializer(p).data, status=201)


# =========================================================================== payables queue (CM, RV, PY)

class PayableViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ProPayableSerializer

    def get_queryset(self):
        from django.utils import timezone

        qs = _scope(Payable.objects.select_related("country", "case", "agreement__professional", "country_config",
                                                   "payment_line__run"),
                    self.request.user, ("CM", "RV", "AD", "PY"))
        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("overdue") in ("1", "true", "yes"):
            qs = qs.filter(status__in=["approved", "held", "in_run"], due_by__lt=timezone.localdate())
        if p.get("case"):
            qs = qs.filter(case_id=p["case"])
        return qs.order_by("due_by", "created_at")

    @extend_schema(parameters=[OpenApiParameter("status", str), OpenApiParameter("overdue", bool),
                               OpenApiParameter("case", str)])
    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(ProPayableSerializer(page, many=True).data)

    @extend_schema(request=ProHoldIn, responses=ProPayableSerializer)
    @action(detail=True, methods=["post"])
    def holds(self, request, pk=None):
        """Hold for a fraud or misconduct review only; never for a result (RUL-26)."""
        d = _valid(ProHoldIn, request)
        p = services.hold_payable(self.get_object(), request.user, reason=d["reason"], note=d.get("note", ""))
        return Response(ProPayableSerializer(p).data)

    @extend_schema(request=ProNoteIn, responses=ProPayableSerializer)
    @action(detail=True, methods=["post"], url_path="hold-releases")
    def hold_releases(self, request, pk=None):
        d = _valid(ProNoteIn, request)
        return Response(ProPayableSerializer(services.release_hold(self.get_object(), request.user,
                                                                   note=d.get("note", ""))).data)

    @extend_schema(request=ProReasonIn, responses=ProPayableSerializer)
    @action(detail=True, methods=["post"])
    def cancellations(self, request, pk=None):
        d = _valid(ProReasonIn, request)
        return Response(ProPayableSerializer(services.cancel_payable(self.get_object(), request.user,
                                                                     reason=d["reason"])).data)


# =========================================================================== expense decisions (CM, RV)

class ExpenseViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ProExpenseSerializer

    def get_queryset(self):
        qs = _scope(ExpenseClaim.objects.select_related("country", "claimant"), self.request.user, ("CM", "RV"))
        if self.request.query_params.get("status"):
            qs = qs.filter(status=self.request.query_params["status"])
        return qs

    @extend_schema(parameters=[OpenApiParameter("status", str)])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=ProDecisionIn, responses=ProExpenseSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def decisions(self, request, pk=None):
        d = _valid(ProDecisionIn, request)
        c = services.decide_claim(self.get_object(), request.user, decision=d["decision"], note=d.get("note", ""))
        return Response(ProExpenseSerializer(c).data)

    @extend_schema(request=ProDecisionIn, responses=ProExpenseSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def approvals(self, request, pk=None):
        """Second staff approval of an exception claim, with MFA (US-PRO-004 AC2)."""
        d = _valid(ProDecisionIn, request)
        c = self.get_object()
        services.decide_exception(c, request.user, decision=d["decision"], mfa_at=require_mfa(request),
                                  note=d.get("note", ""))
        c.refresh_from_db()
        return Response(ProExpenseSerializer(c).data)


# =========================================================================== payment runs

class PaymentRunViewSet(viewsets.GenericViewSet):
    serializer_class = ProRunSerializer
    queryset = PaymentRun.objects.none()

    def get_queryset(self):
        qs = _scope(PaymentRun.objects.select_related("country", "operating_account"), self.request.user,
                    ("CM", "RV", "AD", "PY"))
        if self.request.query_params.get("status"):
            qs = qs.filter(status=self.request.query_params["status"])
        return qs

    @extend_schema(parameters=[OpenApiParameter("status", str)])
    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(ProRunSerializer(page, many=True).data)

    @extend_schema(responses=ProRunDetailSerializer)
    def retrieve(self, request, pk=None):
        return Response(ProRunDetailSerializer(self.get_object()).data)

    @extend_schema(request=ProRunIn, responses={201: ProRunDetailSerializer})
    @idempotent
    def create(self, request):
        """Prepare a run to a cut-off: lines per professional, totals, and items left out with reasons."""
        d = _valid(ProRunIn, request)
        run = services.prepare_run(request.user, country=_country(d["country"]),
                                   operating_account_id=d.get("operating_account_id"), cut_off_at=d.get("cut_off_at"))
        return Response(ProRunDetailSerializer(run).data, status=201)

    @extend_schema(request=None, responses=ProRunDetailSerializer)
    @action(detail=True, methods=["post"])
    def refresh(self, request, pk=None):
        return Response(ProRunDetailSerializer(services.refresh_run(self.get_object(), request.user)).data)

    @extend_schema(request=None, responses=ProRunDetailSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def submit(self, request, pk=None):
        return Response(ProRunDetailSerializer(services.submit_run(self.get_object(), request.user)).data)

    @extend_schema(request=ProDecisionIn, responses=ProRunDetailSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def approvals(self, request, pk=None):
        """Approve the run: payment rights, not the preparer, MFA (US-PRO-005 AC2, AC4)."""
        d = _valid(ProDecisionIn, request)
        run = self.get_object()
        services.decide_run(run, request.user, decision=d["decision"], mfa_at=require_mfa(request),
                            note=d.get("note", ""))
        run.refresh_from_db()
        return Response(ProRunDetailSerializer(run).data)

    @extend_schema(request=ProNoteIn, responses=ProRunDetailSerializer)
    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        d = _valid(ProNoteIn, request)
        return Response(ProRunDetailSerializer(services.withdraw_run(self.get_object(), request.user,
                                                                     reason=d.get("note", ""))).data)

    @extend_schema(responses={(200, "text/csv"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"])
    def file(self, request, pk=None):
        """The bulk payment file; every download logged; an altered file is never served."""
        data, ctype, name = services.download_file(self.get_object(), request.user)
        resp = HttpResponse(data, content_type=ctype)
        resp["Content-Disposition"] = f'attachment; filename="{name}"'
        resp["X-Content-SHA256"] = self.get_object().file_sha256
        return resp

    @extend_schema(request=None, responses=ProRunSerializer)
    @action(detail=True, methods=["post"])
    def uploads(self, request, pk=None):
        """Record who uploaded the file in the operating bank's portal."""
        return Response(ProRunSerializer(services.mark_uploaded(self.get_object(), request.user)).data)

    @extend_schema(request=ProConfirmationIn, responses=ProRunDetailSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def confirmations(self, request, pk=None):
        """Import the bank's or provider's confirmation and match it to lines (US-PRO-009)."""
        d = _valid(ProConfirmationIn, request)
        if d.get("content_base64"):
            try:
                data = base64.b64decode(d["content_base64"], validate=True)
            except (binascii.Error, ValueError) as exc:
                raise Invalid("The file is not valid base64.", code="validation-error") from exc
        elif d.get("content"):
            data = d["content"].encode()
        else:
            raise Invalid("Send the confirmation file.", code="validation-error")
        run = services.import_confirmation(self.get_object(), request.user, data=data,
                                           content_type=d.get("content_type") or "text/csv",
                                           name=d.get("filename") or "confirmation.csv")
        return Response(ProRunDetailSerializer(run).data)


class PaymentLineViewSet(viewsets.GenericViewSet):
    serializer_class = ProLineSerializer
    queryset = PaymentLine.objects.none()

    def get_queryset(self):
        from accounts.selectors import scope_to_staff_countries

        if not has_role(self.request.user, "CM", "RV", "AD"):
            return PaymentLine.objects.none()
        return scope_to_staff_countries(PaymentLine.objects.select_related("run", "agreement__professional"),
                                        self.request.user, field="run__country", roles=("CM", "RV", "AD"))

    def retrieve(self, request, pk=None):
        return Response(ProLineSerializer(self.get_object()).data)

    @extend_schema(request=ProReasonIn, responses=ProRunDetailSerializer)
    @action(detail=True, methods=["post"])
    def removals(self, request, pk=None):
        """Remove a line; an approved run returns to draft and its approval is withdrawn (US-PRO-005 AC3)."""
        d = _valid(ProReasonIn, request)
        run = services.remove_line(self.get_object(), request.user, reason=d["reason"])
        return Response(ProRunDetailSerializer(run).data)

    @extend_schema(request=ProResolutionIn, responses=ProLineSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def resolutions(self, request, pk=None):
        d = _valid(ProResolutionIn, request)
        line = services.resolve_line(self.get_object(), request.user, resolution=d["resolution"],
                                     note=d.get("note", ""),
                                     letter_evidence=_evidence(d.get("letter_evidence_id"), required=False))
        return Response(ProLineSerializer(line).data)

    @extend_schema(request=ProLetterCheckIn, responses=ProLineSerializer)
    @action(detail=True, methods=["post"], url_path="letter-checks")
    @idempotent
    def letter_checks(self, request, pk=None):
        """A second staff member checks the bank letter before the line is confirmed (US-PRO-009 AC3)."""
        d = _valid(ProLetterCheckIn, request)
        line = services.check_bank_letter(self.get_object(), request.user, accept=d["accept"],
                                          note=d.get("note", ""))
        return Response(ProLineSerializer(line).data)


# =========================================================================== reports and jobs

@extend_schema(tags=["pro"], parameters=[OpenApiParameter("country", str)], responses=ProCostRow(many=True))
@api_view(["GET"])
def cost_per_case(request):
    """Cost per case from accepted payables and approved expenses (FR-PRO-010)."""
    if not has_role(request.user, "CM", "RV", "AD"):
        raise Forbidden()
    from accounts.selectors import in_staff_scope

    country = _country(request.query_params["country"]) if request.query_params.get("country") else None
    if country is not None and not in_staff_scope(request.user, country, roles=("CM", "RV", "AD")):
        raise Forbidden()
    rows = services.cost_per_case(country)
    if country is None:
        from accounts.selectors import staff_country_codes

        codes = staff_country_codes(request.user, ("CM", "RV", "AD"))
        if codes is not None:
            ids = set(Payable.objects.filter(country__code__in=codes).values_list("case_id", flat=True)) | set(
                ExpenseClaim.objects.filter(country__code__in=codes).values_list("case_id", flat=True))
            rows = [r for r in rows if r["case_id"] in {str(i) for i in ids}]
    return Response(rows)


@extend_schema(tags=["pro"], request=ProStatementsIn, responses={201: ProDocumentSerializer(many=True)})
@api_view(["POST"])
def generate_statements(request):
    """Yearly statements for a tax year; each adds up to the professional's remittance advices."""
    d = _valid(ProStatementsIn, request)
    docs = services.generate_statements(_country(d["country"]), d["tax_year"], by=request.user)
    return Response(ProDocumentSerializer(docs, many=True).data, status=201)


@extend_schema(tags=["pro"], request=ProCountIn, responses={200: OpenApiTypes.OBJECT})
@api_view(["POST"])
def overdue_check(request):
    """Run the daily overdue check now (FR-PRO-008); it also runs as a scheduled job."""
    if not has_role(request.user, "CM", "RV"):
        raise Forbidden()
    return Response({"alerted": services.check_overdue()})
