"""ESC API (02 section 7.4). Clients see only their own escrows (or ones they
are a party to); staff are scoped to their country role grants; release
rights (RR) are checked inside the approval component."""
from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from core.errors import Invalid, NotFound
from core.idempotency import idempotent
from core.permissions import has_role, roles
from core.views import require_mfa

from accounts.models import NationalIdCheck, Organisation

from . import selectors, services
from .models import (Party, BankEvent, BankPosition, Condition, Escrow, Freeze, FxConversion, FxQuote, FxRateObservation,
                     Payee, PayeeChange, ProgrammeAccount, ProgrammeRate, ReleaseInstruction, StandingApproval,
                     StatementFile)
from .serializers import (AcceptanceSerializer, AcceptIn, AcceptQuoteIn, BankEventIn, BankEventSerializer,
                          BankPositionIn, BankPositionSerializer, BankRejectionIn, CancellationIn, CheckSerializer,
                          ClientApprovalSerializer, CloseConditionIn, CollectIn, ComparisonSerializer,
                          ConditionIn, ConditionSerializer, ConversionChoiceIn, ConversionIn, EscrowDecisionSerializer,
                          DepositRoutesSerializer, EscrowCreateSerializer, EscrowListSerializer, EscrowSerializer,
                          FreezeSerializer, FreshSearchIn, FundsSerializer, FxAccountIn, FxConversionSerializer,
                          FxQuoteSerializer, HeldFundsIn, HoldIn, IdentityCheckSerializer, InstructionSerializer,
                          NoteEvidenceSerializer, ObservationIn, ObservationSerializer, PartyIn, PartySerializer,
                          PayeeChangeCreateSerializer, PayeeChangeSerializer, PayeeCreateSerializer, PayeeSerializer,
                          PayeeUpdateSerializer, ProgrammeAccountIn, ProgrammeAccountSerializer, ProgrammeRateIn,
                          ProgrammeRateSerializer, QuoteIn, EscrowReasonSerializer, RefundExceptionSerializer,
                          ReleaseRequestIn, StandingApprovalIn, StandingApprovalSerializer, StatementFileSerializer,
                          StatementLineSerializer, StatementSerializer, StatementUploadIn, StopSerializer, TermsVersionIn,
                          VirtualAccountIn)

STAFF = ("CM", "RV", "AD")


def _valid(cls, request, **kw):
    s = cls(data=request.data, context={"request": request}, **kw)
    s.is_valid(raise_exception=True)
    return s.validated_data


def _country(code):
    from countries.models import Country

    c = Country.objects.filter(code=str(code or "").upper()).first()
    if c is None:
        raise Invalid("Unknown country.", code="validation-error")
    return c


def _evidence(pk, required=True):
    from evidence.models import Evidence

    if not pk:
        if required:
            raise Invalid("Attach the evidence.", code="validation-error")
        return None
    ev = Evidence.objects.filter(pk=pk).first()
    if ev is None:
        raise Invalid("Evidence not found.", code="validation-error")
    return ev


def _get(model, pk):
    obj = model.objects.filter(pk=pk).first()
    if obj is None:
        raise NotFound()
    return obj


def _person(pk):
    from accounts.models import Person

    return _get(Person, pk) if pk else None


def _mfa(request, code):
    return None if code else require_mfa(request)


def _is_staff_for(user, country):
    return has_role(user, *STAFF, country=country)


def _can_see_escrow(user, e):
    if _is_staff_for(user, e.country):
        return True
    if e.client_id == user.pk or e.parties.filter(person=user).exists():
        return True
    from accounts.selectors import is_representative

    return is_representative(user, "escrow", e.pk)


def _escrow(request, pk) -> Escrow:
    e = Escrow.objects.filter(pk=pk).select_related("country", "programme_account").first()
    if e is None or not _can_see_escrow(request.user, e):
        raise NotFound()
    return e


def _escrows_visible(user):
    from accounts.selectors import representative_subject_ids, staff_country_codes

    codes = staff_country_codes(user)
    if codes is None:
        return Escrow.objects.all()
    q = Q(client=user) | Q(parties__person=user) | Q(pk__in=representative_subject_ids(user, "escrow"))
    if codes:
        q |= Q(country__code__in=codes)
    return Escrow.objects.filter(q).distinct()


# ----------------------------------------------------------------- escrows

def _P(name):
    from drf_spectacular.types import OpenApiTypes

    return OpenApiParameter(name, OpenApiTypes.UUID, OpenApiParameter.PATH)


class EscrowViewSet(viewsets.GenericViewSet):
    serializer_class = EscrowSerializer
    queryset = Escrow.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Escrow.objects.none()
        qs = _escrows_visible(self.request.user).select_related("country").order_by("-created_at")
        for f in ("status", "kind"):
            v = self.request.query_params.get(f)
            if v:
                qs = qs.filter(**{f: v})
        return qs

    @extend_schema(responses=EscrowListSerializer(many=True),
                   parameters=[OpenApiParameter("status", str), OpenApiParameter("kind", str)])
    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(EscrowListSerializer(page, many=True).data)

    def retrieve(self, request, pk=None):
        e = _escrow(request, pk)
        resp = Response(EscrowSerializer(e).data)
        resp["ETag"] = f'"{e.row_version}"'
        return resp

    @extend_schema(request=EscrowCreateSerializer, responses={201: EscrowSerializer})
    @idempotent
    def create(self, request):
        d = _valid(EscrowCreateSerializer, request)
        country = _country(d["country"])
        client = _person(d.get("client_id")) or request.user
        price = d.get("agreed_price") or {}
        parties = []
        for p in d.get("parties", []):
            parties.append({"role": p["role"], "name": p.get("name", ""), "person": _person(p.get("person_id")),
                            "organisation": _get(Organisation, p["organisation_id"])
                            if p.get("organisation_id") else None,
                            "payee": _get(Payee, p["payee_id"]) if p.get("payee_id") else None,
                            "national_id_check": _get(NationalIdCheck, p["national_id_check_id"])
                            if p.get("national_id_check_id") else None,
                            "must_accept": p.get("must_accept", True)})
        e = services.create_escrow(request.user, kind=d["kind"], client=client, country=country,
                                   agreed_amount=price.get("amount", 0), currency=price.get("currency"),
                                   title=d.get("title", ""), report_id=d.get("report_id"),
                                   asset_id=d.get("asset_id"), project_id=d.get("project_id"),
                                   case_id=d.get("case_id"), parties=parties, conditions=d.get("conditions", []),
                                   held_back_amount=d.get("held_back_amount") or 0,
                                   held_back_condition=d.get("held_back_condition", ""))
        return Response(EscrowSerializer(e).data, status=201)

    @extend_schema(request=AcceptIn, responses=AcceptanceSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def acceptances(self, request, pk=None):
        e = _escrow(request, pk)
        d = _valid(AcceptIn, request)
        party = _get(Party, d["party_id"]) if d.get("party_id") else None
        if party is not None and party.escrow_id != e.pk:
            raise NotFound()
        a = services.accept_terms(e, request.user, party=party, evidence=_evidence(d.get("evidence_id"), False))
        return Response(AcceptanceSerializer(a).data, status=201)

    @extend_schema(request=VirtualAccountIn, responses=EscrowSerializer)
    @action(detail=True, methods=["post"], url_path="virtual-account", permission_classes=[roles("CM", "RV")])
    def virtual_account(self, request, pk=None):
        e = _escrow(request, pk)
        d = _valid(VirtualAccountIn, request)
        pa = _get(ProgrammeAccount, d["programme_account_id"]) if d.get("programme_account_id") else None
        services.record_virtual_account(e, request.user, virtual_account_ref=d["virtual_account_ref"],
                                        programme_account=pa)
        e.refresh_from_db()
        return Response(EscrowSerializer(e).data)

    @extend_schema(request=PartyIn, responses=PartySerializer)
    @action(detail=True, methods=["post"], permission_classes=[roles("CM", "RV")])
    def parties(self, request, pk=None):
        e = _escrow(request, pk)
        d = _valid(PartyIn, request)
        p = services.add_party(e, request.user, role=d["role"], name=d.get("name", ""),
                               person=_person(d.get("person_id")),
                               organisation=_get(Organisation, d["organisation_id"]) if d.get("organisation_id")
                               else None,
                               payee=_get(Payee, d["payee_id"]) if d.get("payee_id") else None,
                               national_id_check=_get(NationalIdCheck, d["national_id_check_id"])
                               if d.get("national_id_check_id") else None, must_accept=d.get("must_accept", True))
        return Response(PartySerializer(p).data, status=201)

    @extend_schema(request=TermsVersionIn, responses=EscrowSerializer)
    @action(detail=True, methods=["post"], url_path="terms-version", permission_classes=[roles("CM", "RV")])
    def terms_version(self, request, pk=None):
        from administration.models import LockedTextVersion

        e = _escrow(request, pk)
        d = _valid(TermsVersionIn, request)
        services.set_terms_version(e, request.user, _get(LockedTextVersion, d["terms_version_id"]))
        e.refresh_from_db()
        return Response(EscrowSerializer(e).data)

    @extend_schema(request=ConditionIn, responses=ConditionSerializer)
    @action(detail=True, methods=["post"], permission_classes=[roles("CM", "RV")])
    def conditions(self, request, pk=None):
        e = _escrow(request, pk)
        d = _valid(ConditionIn, request)
        return Response(ConditionSerializer(services.add_condition(e, request.user, text=d["text"],
                                                                   key=d.get("key", ""))).data, status=201)

    def _condition(self, request, pk, cid):
        e = _escrow(request, pk)
        c = Condition.objects.filter(pk=cid, escrow=e).first()
        if c is None:
            raise NotFound()
        return c

    @extend_schema(request=CloseConditionIn, responses=ConditionSerializer, parameters=[_P("cid")])
    @action(detail=True, methods=["post"], url_path=r"conditions/(?P<cid>[^/.]+)/close",
            permission_classes=[roles("CM", "RV")])
    @idempotent
    def close_condition(self, request, pk=None, cid=None):
        c = self._condition(request, pk, cid)
        d = _valid(CloseConditionIn, request)
        services.close_condition(c, request.user, evidence_ids=d["evidence_ids"], note=d.get("note", ""))
        c.refresh_from_db()
        return Response(ConditionSerializer(c).data)

    @extend_schema(request=EscrowReasonSerializer, responses=ConditionSerializer, parameters=[_P("cid")])
    @action(detail=True, methods=["post"], url_path=r"conditions/(?P<cid>[^/.]+)/reopen",
            permission_classes=[roles("RV")])
    def reopen_condition(self, request, pk=None, cid=None):
        c = self._condition(request, pk, cid)
        services.reopen_condition(c, request.user, reason=_valid(EscrowReasonSerializer, request)["reason"])
        c.refresh_from_db()
        return Response(ConditionSerializer(c).data)

    @extend_schema(request=FreshSearchIn, responses=EscrowSerializer)
    @action(detail=True, methods=["post"], url_path="fresh-search", permission_classes=[roles("CM", "RV")])
    def fresh_search(self, request, pk=None):
        e = _escrow(request, pk)
        d = _valid(FreshSearchIn, request)
        services.record_fresh_search(e, request.user, **d)
        e.refresh_from_db()
        return Response(EscrowSerializer(e).data)

    @extend_schema(request=BankEventIn, responses={201: BankEventSerializer})
    @action(detail=True, methods=["post"], url_path="bank-events", permission_classes=[roles("CM", "RV")])
    @idempotent
    def bank_events(self, request, pk=None):
        from administration.models import Partner

        e = _escrow(request, pk)
        d = _valid(BankEventIn, request)
        ins = _get(ReleaseInstruction, d["instruction_id"]) if d.get("instruction_id") else None
        ev = services.record_bank_event(
            e, kind=d["kind"], amount=d["amount"]["amount"], currency=d["amount"]["currency"],
            bank_reference=d["bank_reference"], occurred_at=d.get("occurred_at"),
            virtual_account_ref=d.get("virtual_account_ref") or None, source="manual", by=request.user,
            proof_evidence=_evidence(d["proof_evidence_id"]), instruction=ins,
            source_bank_name=d.get("source_bank_name", ""), source_account_number=d.get("source_account_number", ""),
            source_account_name=d.get("source_account_name", ""),
            source_account_known=d.get("source_account_known", True), deposit_route=d.get("deposit_route", ""),
            transfer_partner=_get(Partner, d["transfer_partner_id"]) if d.get("transfer_partner_id") else None,
            partner_reference=d.get("partner_reference", ""), applied_rate=d.get("applied_rate"),
            applied_fees=d.get("applied_fees"), misdirected=d.get("misdirected", False), note=d.get("note", ""))
        return Response(BankEventSerializer(ev).data, status=201)

    @extend_schema(request=ReleaseRequestIn, responses={201: InstructionSerializer})
    @action(detail=True, methods=["get", "post"], url_path="release-instructions")
    @idempotent
    def release_instructions(self, request, pk=None):
        e = _escrow(request, pk)
        if request.method == "GET":
            return Response(InstructionSerializer(e.instructions.order_by("-created_at"), many=True).data)
        if not has_role(request.user, "CM", "RV", country=e.country):
            raise NotFound()
        d = _valid(ReleaseRequestIn, request)
        amt = d.get("amount") or {}
        ins = services.request_release(
            e, payee=_get(Payee, d["payee_id"]) if d.get("payee_id") else None, amount=amt.get("amount"),
            currency=amt.get("currency"), subject_type=d.get("subject_type"), subject_id=d.get("subject_id"),
            requested_by=request.user, evidence_ids=d.get("evidence_ids", []), reason=d.get("reason", ""),
            subject_label=d.get("subject_label", ""), family_member_id=d.get("family_member_id"),
            holdback_amount=d.get("holdback_amount") or 0, kind=d.get("kind"), release_part=d["release_part"],
            standing_approval=_get(StandingApproval, d["standing_approval_id"]) if d.get("standing_approval_id")
            else None)
        return Response(InstructionSerializer(ins).data, status=201)

    @extend_schema(request=ConversionIn, responses={201: InstructionSerializer})
    @action(detail=True, methods=["post"], url_path="conversion-instructions", permission_classes=[roles("CM", "RV")])
    @idempotent
    def conversion_instructions(self, request, pk=None):
        e = _escrow(request, pk)
        qt = _get(FxQuote, _valid(ConversionIn, request)["quote_id"])
        return Response(InstructionSerializer(services.prepare_conversion(e, request.user, quote=qt)).data,
                        status=201)

    @extend_schema(request=CancellationIn, responses=EscrowSerializer)
    @action(detail=True, methods=["post"], permission_classes=[roles("CM", "RV")])
    @idempotent
    def cancellation(self, request, pk=None):
        e = _escrow(request, pk)
        services.request_cancellation(e, request.user, reason=_valid(CancellationIn, request)["reason"])
        e.refresh_from_db()
        return Response(EscrowSerializer(e).data)

    @extend_schema(request=EscrowDecisionSerializer, responses=EscrowSerializer)
    @action(detail=True, methods=["post"], url_path="cancellation-approvals", permission_classes=[roles(*STAFF)])
    @idempotent
    def cancellation_approvals(self, request, pk=None):
        e = _escrow(request, pk)
        d = _valid(EscrowDecisionSerializer, request)
        services.decide_cancellation(e, request.user, decision=d["decision"], mfa_at=require_mfa(request),
                                     note=d.get("note", ""))
        e.refresh_from_db()
        return Response(EscrowSerializer(e).data)

    @extend_schema(responses=StatementSerializer, parameters=[OpenApiParameter("family_member", str)])
    @action(detail=True, methods=["get"])
    def statement(self, request, pk=None):
        e = _escrow(request, pk)
        data = selectors.statement(e, request.query_params.get("family_member"))
        return Response(StatementSerializer(data).data)

    @extend_schema(responses=FundsSerializer(many=True))
    @action(detail=True, methods=["get"])
    def funds(self, request, pk=None):
        e = _escrow(request, pk)
        return Response(FundsSerializer(selectors.confirmed_funds(e), many=True).data)

    @extend_schema(request=BankPositionIn, responses={201: BankPositionSerializer})
    @action(detail=True, methods=["post"], url_path="bank-positions", permission_classes=[roles("CM", "RV")])
    def bank_positions(self, request, pk=None):
        e = _escrow(request, pk)
        d = _valid(BankPositionIn, request)
        pos = services.record_bank_position(e, as_of=d["as_of"], reported_held_amount=d["reported_held"]["amount"],
                                            currency=d["reported_held"]["currency"], source="manual",
                                            by=request.user, proof_evidence=_evidence(d["proof_evidence_id"]))
        return Response(BankPositionSerializer(pos).data, status=201)

    @extend_schema(request=HoldIn, responses={201: FreezeSerializer})
    @action(detail=True, methods=["post"], permission_classes=[roles("RV")])
    def holds(self, request, pk=None):
        e = _escrow(request, pk)
        f = services.place_hold(e, request.user, reason=_valid(HoldIn, request)["reason"])
        return Response(FreezeSerializer(f).data, status=201)

    @extend_schema(request=EscrowReasonSerializer, responses=EscrowSerializer, parameters=[_P("hid")])
    @action(detail=True, methods=["post"], url_path=r"holds/(?P<hid>[^/.]+)/lift", permission_classes=[roles("RV")])
    def lift_hold(self, request, pk=None, hid=None):
        e = _escrow(request, pk)
        f = Freeze.objects.filter(pk=hid, escrow=e).first()
        if f is None:
            raise NotFound()
        services.lift_hold(f, request.user, note=_valid(EscrowReasonSerializer, request)["reason"])
        e.refresh_from_db()
        return Response(EscrowSerializer(e).data)

    @extend_schema(request=StandingApprovalIn, responses={201: StandingApprovalSerializer})
    @action(detail=True, methods=["post"], url_path="standing-approvals")
    @idempotent
    def standing_approvals(self, request, pk=None):
        e = _escrow(request, pk)
        d = _valid(StandingApprovalIn, request)
        sa = services.create_standing_approval(e, request.user, subject_kind=d["subject_kind"],
                                               subject_id=d["subject_id"], monthly_max=d["monthly_max"],
                                               mfa_at=_mfa(request, d.get("code")), code=d.get("code") or None)
        return Response(StandingApprovalSerializer(sa).data, status=201)

    @extend_schema(responses=DepositRoutesSerializer,
                   parameters=[OpenApiParameter("currency", str, required=True),
                               OpenApiParameter("amount", str, required=True)])
    @action(detail=True, methods=["get"], url_path="deposit-routes")
    def deposit_routes(self, request, pk=None):
        e = _escrow(request, pk)
        cur, amt = request.query_params.get("currency"), request.query_params.get("amount")
        if not cur or not amt:
            raise Invalid("Give currency and amount.", code="validation-error")
        return Response(DepositRoutesSerializer(services.deposit_routes(e, request.user, currency=cur,
                                                                        amount=amt)).data)

    @extend_schema(request=QuoteIn, responses={201: FxQuoteSerializer})
    @action(detail=True, methods=["post"], url_path="fx-quotes")
    @idempotent
    def fx_quotes(self, request, pk=None):
        from administration.models import Partner

        e = _escrow(request, pk)
        d = _valid(QuoteIn, request)
        qt = services.issue_quote(e, request.user, purpose=d["purpose"], route=d["route"],
                                  from_currency=d["amount"]["currency"], from_amount=d["amount"]["amount"],
                                  provider_partner=_get(Partner, d["provider_partner_id"])
                                  if d.get("provider_partner_id") else None, client_rate=d.get("client_rate"))
        return Response(FxQuoteSerializer(qt).data, status=201)

    @extend_schema(request=ConversionChoiceIn, responses=EscrowSerializer)
    @action(detail=True, methods=["put"], url_path="conversion-choice")
    def conversion_choice(self, request, pk=None):
        e = _escrow(request, pk)
        d = _valid(ConversionChoiceIn, request)
        services.set_conversion_choice(e, request.user, choice=d["conversion_choice"],
                                       mfa_at=_mfa(request, d.get("code")), code=d.get("code") or None)
        e.refresh_from_db()
        return Response(EscrowSerializer(e).data)

    @extend_schema(responses=FxConversionSerializer(many=True))
    @action(detail=True, methods=["get"])
    def conversions(self, request, pk=None):
        e = _escrow(request, pk)
        return Response(FxConversionSerializer(e.fx_conversions.order_by("-created_at"), many=True).data)

    @extend_schema(request=FxAccountIn, responses={201: EscrowSerializer})
    @action(detail=True, methods=["post"], url_path="fx-accounts", permission_classes=[roles("CM", "RV")])
    def fx_accounts(self, request, pk=None):
        e = _escrow(request, pk)
        d = _valid(FxAccountIn, request)
        services.record_fx_account(e, request.user, currency=d["currency"],
                                   virtual_account_ref=d["virtual_account_ref"])
        return Response(EscrowSerializer(e).data, status=201)

    @extend_schema(request=RefundExceptionSerializer, responses={201: PayeeChangeSerializer},
                   parameters=[_P("event_id")])
    @action(detail=True, methods=["post"], url_path=r"deposits/(?P<event_id>[^/.]+)/refund-exceptions")
    @idempotent
    def refund_exceptions(self, request, pk=None, event_id=None):
        e = _escrow(request, pk)
        dep = BankEvent.objects.filter(pk=event_id, escrow=e).first()
        if dep is None:
            raise NotFound()
        d = _valid(RefundExceptionSerializer, request)
        ch = services.request_change(request.user, kind="refund_destination", reason=d["reason"],
                                     request_source="client_signed_in" if request.user.pk == e.client_id
                                     else "staff_in_person", escrow=e, deposit_event=dep, bank_name=d["bank_name"],
                                     account_number=d["account_number"], account_name=d.get("account_name", ""),
                                     account_name_source=d["account_name_source"],
                                     account_name_evidence=_evidence(d.get("account_name_evidence_id"), False))
        return Response(PayeeChangeSerializer(ch).data, status=201)


# ----------------------------------------------------------------- held funds (FR-ESC-014)

class HeldFundsViewSet(viewsets.GenericViewSet):
    serializer_class = EscrowSerializer
    queryset = Escrow.objects.none()

    @extend_schema(responses=EscrowSerializer(many=True))
    def list(self, request):
        qs = Escrow.objects.filter(client=request.user, kind="held_funds").order_by("-created_at")
        return Response(EscrowSerializer(qs, many=True).data)

    @extend_schema(request=HeldFundsIn, responses={201: EscrowSerializer})
    @idempotent
    def create(self, request):
        d = _valid(HeldFundsIn, request)
        e = services.open_held_funds(request.user, _country(d["country"]), d.get("currency"), by=request.user)
        return Response(EscrowSerializer(e).data, status=201)


# ----------------------------------------------------------------- release instructions

class ReleaseInstructionViewSet(viewsets.GenericViewSet):
    serializer_class = InstructionSerializer
    queryset = ReleaseInstruction.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ReleaseInstruction.objects.none()
        return ReleaseInstruction.objects.filter(escrow__in=_escrows_visible(self.request.user)) \
            .select_related("escrow", "payee", "approval_request").order_by("-created_at")

    def _obj(self, request, pk) -> ReleaseInstruction:
        ins = self.get_queryset().filter(pk=pk).first()
        if ins is None:
            raise NotFound()
        return ins

    @extend_schema(responses=InstructionSerializer(many=True), parameters=[
        OpenApiParameter("clock", str, enum=["due_today", "send_overdue", "bank_overdue", "in_progress"]),
        OpenApiParameter("status", str)])
    def list(self, request):
        from .common import local_today

        qs = self.get_queryset()
        if not has_role(request.user, *STAFF):
            qs = qs.filter(escrow__client=request.user)
        clock = request.query_params.get("clock")
        if clock:
            if not has_role(request.user, "CM", "RV", "AD"):
                raise NotFound()
            out = []
            for ins in qs.filter(status__in=["awaiting_client", "pending_approval", "approved", "sent"]):
                today = local_today(ins.country)
                if clock == "due_today" and ins.status == "approved" and ins.send_due_on == today:
                    out.append(ins)
                elif clock == "send_overdue" and ins.status == "approved" and ins.send_due_on and \
                        today > ins.send_due_on:
                    out.append(ins)
                elif clock == "bank_overdue" and ins.status == "sent" and ins.bank_pay_due_on and \
                        today > ins.bank_pay_due_on:
                    out.append(ins)
                elif clock == "in_progress":
                    out.append(ins)
            return Response({"items": InstructionSerializer(out, many=True).data, "next_cursor": None})
        st = request.query_params.get("status")
        if st:
            qs = qs.filter(status=st)
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(InstructionSerializer(page, many=True).data)

    def retrieve(self, request, pk=None):
        ins = self._obj(request, pk)
        resp = Response(InstructionSerializer(ins).data)
        resp["ETag"] = f'"{ins.row_version}"'
        return resp

    @extend_schema(request=ClientApprovalSerializer, responses=InstructionSerializer)
    @action(detail=True, methods=["post"], url_path="client-approval")
    @idempotent
    def client_approval(self, request, pk=None):
        ins = self._obj(request, pk)
        d = _valid(ClientApprovalSerializer, request)
        if d["approve"]:
            services.client_approve(ins, request.user, _mfa(request, d.get("code")), code=d.get("code") or None)
        else:
            services.client_decline(ins, request.user, d.get("reason", ""))
        ins.refresh_from_db()
        return Response(InstructionSerializer(ins).data)

    @extend_schema(request=EscrowDecisionSerializer, responses=InstructionSerializer)
    @action(detail=True, methods=["post"], permission_classes=[roles(*STAFF)])
    @idempotent
    def approvals(self, request, pk=None):
        ins = self._obj(request, pk)
        im = request.headers.get("If-Match")
        if im and im.strip('"') != str(ins.row_version):
            from rest_framework.exceptions import APIException

            exc = APIException("The instruction changed since you loaded it. Reload and try again.")
            exc.status_code = 412
            raise exc
        d = _valid(EscrowDecisionSerializer, request)
        services.staff_approve(ins, request.user, mfa_at=require_mfa(request), decision=d["decision"],
                               confirm_amount=d.get("confirm_amount"), note=d.get("note", ""))
        ins.refresh_from_db()
        data = InstructionSerializer(ins).data
        data["dispatch"] = {"status": ins.status if ins.status in ("sent", "confirmed") else (
            "queued" if ins.status == "approved" else "waiting")}
        return Response(data)

    @extend_schema(request=EscrowReasonSerializer, responses=InstructionSerializer)
    @action(detail=True, methods=["post"], permission_classes=[roles("CM", "RV")])
    def withdraw(self, request, pk=None):
        ins = self._obj(request, pk)
        services.withdraw_instruction(ins, request.user, reason=_valid(EscrowReasonSerializer, request)["reason"])
        ins.refresh_from_db()
        return Response(InstructionSerializer(ins).data)

    @extend_schema(request=None, responses=InstructionSerializer)
    @action(detail=True, methods=["post"], permission_classes=[roles("CM", "RV")])
    @idempotent
    def send(self, request, pk=None):
        """Retry sending an approved instruction (never sent twice)."""
        ins = self._obj(request, pk)
        services.dispatch(ins)
        ins.refresh_from_db()
        return Response(InstructionSerializer(ins).data)

    @extend_schema(request=BankRejectionIn, responses=InstructionSerializer)
    @action(detail=True, methods=["post"], url_path="bank-rejection", permission_classes=[roles("CM", "RV")])
    def bank_rejection(self, request, pk=None):
        ins = self._obj(request, pk)
        d = _valid(BankRejectionIn, request)
        services.record_bank_rejection(ins, request.user, reason=d["reason"],
                                       proof_evidence=_evidence(d["proof_evidence_id"]),
                                       source_cannot_receive=d["source_cannot_receive"])
        ins.refresh_from_db()
        return Response(InstructionSerializer(ins).data)


class StandingApprovalViewSet(viewsets.GenericViewSet):
    serializer_class = StandingApprovalSerializer
    queryset = StandingApproval.objects.none()

    @extend_schema(request=None, responses=StandingApprovalSerializer)
    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        sa = StandingApproval.objects.filter(pk=pk, client=request.user).first()
        if sa is None:
            raise NotFound()
        return Response(StandingApprovalSerializer(services.withdraw_standing_approval(sa, request.user)).data)


# ----------------------------------------------------------------- bank events and positions

class BankEventViewSet(viewsets.GenericViewSet):
    serializer_class = BankEventSerializer
    queryset = BankEvent.objects.none()
    permission_classes = [roles("CM", "RV", "AD")]

    def _obj(self, request, pk):
        ev = BankEvent.objects.filter(pk=pk).select_related("escrow").first()
        if ev is None or not _is_staff_for(request.user, ev.country):
            raise NotFound()
        return ev

    @extend_schema(responses=BankEventSerializer(many=True), parameters=[OpenApiParameter("status", str)])
    def list(self, request):
        from accounts.selectors import scope_to_staff_countries

        qs = scope_to_staff_countries(BankEvent.objects.order_by("-created_at"), request.user)
        st = request.query_params.get("status")
        if st:
            qs = qs.filter(status=st)
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(BankEventSerializer(page, many=True).data)

    def retrieve(self, request, pk=None):
        return Response(BankEventSerializer(self._obj(request, pk)).data)

    @extend_schema(request=CheckSerializer, responses=BankEventSerializer)
    @action(detail=True, methods=["post"], permission_classes=[roles("CM", "RV")])
    @idempotent
    def check(self, request, pk=None):
        ev = self._obj(request, pk)
        d = _valid(CheckSerializer, request)
        services.check_bank_event(ev, request.user, confirm=d["confirm"], reason=d.get("reason", ""))
        ev.refresh_from_db()
        return Response(BankEventSerializer(ev).data)


class BankPositionViewSet(viewsets.GenericViewSet):
    serializer_class = BankPositionSerializer
    queryset = BankPosition.objects.none()
    permission_classes = [roles("CM", "RV", "AD")]

    def _obj(self, request, pk):
        pos = BankPosition.objects.filter(pk=pk).first()
        if pos is None or not _is_staff_for(request.user, pos.country):
            raise NotFound()
        return pos

    @extend_schema(responses=BankPositionSerializer(many=True), parameters=[OpenApiParameter("status", str)])
    def list(self, request):
        from accounts.selectors import scope_to_staff_countries

        qs = scope_to_staff_countries(BankPosition.objects.order_by("-as_of"), request.user)
        st = request.query_params.get("status")
        if st:
            qs = qs.filter(status=st)
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(BankPositionSerializer(page, many=True).data)

    @extend_schema(request=None, responses=BankPositionSerializer)
    @action(detail=True, methods=["post"])
    def check(self, request, pk=None):
        return Response(BankPositionSerializer(services.check_bank_position(self._obj(request, pk),
                                                                            request.user)).data)

    @extend_schema(request=NoteEvidenceSerializer, responses=BankPositionSerializer)
    @action(detail=True, methods=["post"], permission_classes=[roles("RV")])
    def resolve(self, request, pk=None):
        d = _valid(NoteEvidenceSerializer, request)
        pos = services.resolve_position(self._obj(request, pk), request.user, note=d["note"],
                                        evidence=_evidence(d["evidence_id"]))
        return Response(BankPositionSerializer(pos).data)

    @extend_schema(request=None, responses=BankPositionSerializer)
    @action(detail=True, methods=["post"], url_path="resolution-check")
    def resolution_check(self, request, pk=None):
        return Response(BankPositionSerializer(services.check_resolution(self._obj(request, pk),
                                                                         request.user)).data)


class StatementViewSet(viewsets.GenericViewSet):
    serializer_class = StatementFileSerializer
    queryset = StatementFile.objects.none()
    permission_classes = [roles("CM", "RV")]

    @extend_schema(responses=StatementFileSerializer(many=True))
    def list(self, request):
        from accounts.selectors import scope_to_staff_countries

        qs = scope_to_staff_countries(StatementFile.objects.order_by("-created_at"), request.user)
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(StatementFileSerializer(page, many=True).data)

    @extend_schema(request=StatementUploadIn, responses={201: StatementFileSerializer})
    @idempotent
    def create(self, request):
        d = _valid(StatementUploadIn, request)
        sf = services.import_statement(request.user, country=_country(d["country"]), data=d["content"].encode(),
                                       original_name=d["original_name"], account_kind=d["account_kind"])
        return Response(StatementFileSerializer(sf).data, status=201)

    @extend_schema(responses=StatementLineSerializer(many=True))
    @action(detail=True, methods=["get"])
    def unmatched(self, request, pk=None):
        sf = StatementFile.objects.filter(pk=pk).first()
        if sf is None or not _is_staff_for(request.user, sf.country):
            raise NotFound()
        return Response(StatementLineSerializer(services.unmatched_lines(sf), many=True).data)


# ----------------------------------------------------------------- payees

class PayeeViewSet(viewsets.GenericViewSet):
    serializer_class = PayeeSerializer
    queryset = Payee.objects.none()
    permission_classes = [roles("CM", "RV", "AD")]

    def get_queryset(self):
        from accounts.selectors import scope_to_staff_countries

        if getattr(self, "swagger_fake_view", False):
            return Payee.objects.none()
        qs = scope_to_staff_countries(Payee.objects.order_by("legal_name"), self.request.user)
        for f in ("kind", "verification_status"):
            v = self.request.query_params.get(f)
            if v:
                qs = qs.filter(**{f: v})
        return qs

    def _obj(self, pk):
        p = self.get_queryset().filter(pk=pk).first()
        if p is None:
            raise NotFound()
        return p

    @extend_schema(responses=PayeeSerializer(many=True),
                   parameters=[OpenApiParameter("kind", str), OpenApiParameter("verification_status", str)])
    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(PayeeSerializer(page, many=True).data)

    def retrieve(self, request, pk=None):
        return Response(PayeeSerializer(self._obj(pk)).data)

    @extend_schema(request=PayeeCreateSerializer, responses={201: PayeeSerializer})
    @idempotent
    def create(self, request):
        d = _valid(PayeeCreateSerializer, request)
        p = services.create_payee(
            request.user, country=_country(d["country"]), kind=d["kind"], subject_type=d["subject_type"],
            subject_id=d["subject_id"], legal_name=d["legal_name"],
            legal_name_evidence=_evidence(d["legal_name_evidence_id"]), bank_name=d["bank_name"],
            account_number=d["account_number"], account_name=d.get("account_name", ""),
            account_name_source=d["account_name_source"],
            account_name_evidence=_evidence(d.get("account_name_evidence_id"), False),
            person=_person(d.get("person_id")),
            organisation=_get(Organisation, d["organisation_id"]) if d.get("organisation_id") else None,
            national_id_check=_get(NationalIdCheck, d["national_id_check_id"]) if d.get("national_id_check_id")
            else None, contact_email=d.get("contact_email", ""), contact_phone=d.get("contact_phone", ""))
        return Response(PayeeSerializer(p).data, status=201)

    @extend_schema(request=PayeeUpdateSerializer, responses=PayeeSerializer)
    def partial_update(self, request, pk=None):
        from accounts.models import NationalIdCheck

        p = self._obj(pk)
        d = dict(_valid(PayeeUpdateSerializer, request))
        for k in ("legal_name_evidence", "account_name_evidence"):
            if d.get(f"{k}_id"):
                d[k] = _evidence(d.pop(f"{k}_id"))
        if d.get("national_id_check_id"):
            d["national_id_check"] = _get(NationalIdCheck, d.pop("national_id_check_id"))
        return Response(PayeeSerializer(services.update_payee(p, request.user, d)).data)

    @extend_schema(request=None, responses=PayeeSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def verifications(self, request, pk=None):
        return Response(PayeeSerializer(services.prepare_verification(self._obj(pk), request.user)).data)

    @extend_schema(request=EscrowDecisionSerializer, responses=PayeeSerializer)
    @action(detail=True, methods=["post"], url_path="verification-approvals")
    @idempotent
    def verification_approvals(self, request, pk=None):
        p = self._obj(pk)
        d = _valid(EscrowDecisionSerializer, request)
        services.decide_verification(p, request.user, decision=d["decision"], mfa_at=require_mfa(request),
                                     note=d.get("note", ""))
        p.refresh_from_db()
        return Response(PayeeSerializer(p).data)

    @extend_schema(request=EscrowReasonSerializer, responses=PayeeSerializer)
    @action(detail=True, methods=["post"], permission_classes=[roles("RV")])
    def suspensions(self, request, pk=None):
        p = services.suspend_payee(self._obj(pk), request.user, _valid(EscrowReasonSerializer, request)["reason"])
        return Response(PayeeSerializer(p).data)

    @extend_schema(request=None, responses=PayeeSerializer)
    @action(detail=True, methods=["post"], permission_classes=[roles("RV")])
    def reinstatements(self, request, pk=None):
        return Response(PayeeSerializer(services.reinstate_payee(self._obj(pk), request.user)).data)


class PayeeChangeRequestView(viewsets.GenericViewSet):
    """POST /v1/payees/{id}/changes: also open to the payee signed in (SE, DV, IC own)."""

    serializer_class = PayeeChangeSerializer
    queryset = Payee.objects.none()

    @extend_schema(request=PayeeChangeCreateSerializer, responses={201: PayeeChangeSerializer})
    @idempotent
    def create(self, request, payee_pk=None):
        p = Payee.objects.filter(pk=payee_pk).first()
        if p is None:
            raise NotFound()
        d = _valid(PayeeChangeCreateSerializer, request)
        if d["kind"] == "new_payee":
            ch = services.request_change(request.user, kind="new_payee", reason=d["reason"],
                                         request_source=d["request_source"],
                                         payee=_get(Payee, d.get("new_payee_id")),
                                         replaces_payee=p, escrow=_get(Escrow, d.get("escrow_id")))
        else:
            ch = services.request_change(
                request.user, kind="new_account", reason=d["reason"], request_source=d["request_source"], payee=p,
                escrow=_get(Escrow, d["escrow_id"]) if d.get("escrow_id") else None, bank_name=d["bank_name"],
                account_number=d["account_number"], account_name=d.get("account_name", ""),
                account_name_source=d["account_name_source"],
                account_name_evidence=_evidence(d.get("account_name_evidence_id"), False))
        return Response(PayeeChangeSerializer(ch).data, status=201)


class PayeeChangeViewSet(viewsets.GenericViewSet):
    serializer_class = PayeeChangeSerializer
    queryset = PayeeChange.objects.none()

    def _obj(self, request, pk) -> PayeeChange:
        ch = PayeeChange.objects.filter(pk=pk).select_related("escrow", "payee").first()
        if ch is None:
            raise NotFound()
        u = request.user
        if _is_staff_for(u, ch.country) or ch.requested_by_id == u.pk:
            return ch
        if ch.escrow_id and ch.escrow.client_id == u.pk:
            return ch
        if ch.payee_id and any(e.client_id == u.pk for e in selectors.escrows_paying(ch.payee)):
            return ch
        raise NotFound()

    @extend_schema(responses=PayeeChangeSerializer(many=True), parameters=[OpenApiParameter("status", str)])
    def list(self, request):
        from accounts.selectors import scope_to_staff_countries

        u = request.user
        if has_role(u, *STAFF):
            qs = scope_to_staff_countries(PayeeChange.objects.all(), u)
        else:
            qs = PayeeChange.objects.filter(Q(escrow__client=u) | Q(requested_by=u))
        st = request.query_params.get("status")
        if st:
            qs = qs.filter(status=st)
        page = self.paginate_queryset(qs.order_by("-created_at"))
        return self.get_paginated_response(PayeeChangeSerializer(page, many=True).data)

    def retrieve(self, request, pk=None):
        return Response(PayeeChangeSerializer(self._obj(request, pk)).data)

    @extend_schema(request=None, responses=PayeeChangeSerializer)
    @action(detail=True, methods=["post"], url_path="account-check", permission_classes=[roles(*STAFF)])
    def account_check(self, request, pk=None):
        return Response(PayeeChangeSerializer(services.check_change_account(self._obj(request, pk),
                                                                            request.user)).data)

    @extend_schema(request=IdentityCheckSerializer, responses=PayeeChangeSerializer)
    @action(detail=True, methods=["post"], url_path="identity-check", permission_classes=[roles("CM", "RV")])
    def identity_check(self, request, pk=None):
        d = _valid(IdentityCheckSerializer, request)
        ch = services.change_identity_check(self._obj(request, pk), request.user, id_number=d.get("id_number", ""),
                                            subject_name=d.get("subject_name", ""),
                                            national_id_check=d.get("national_id_check_id"))
        return Response(PayeeChangeSerializer(ch).data)

    @extend_schema(request=ClientApprovalSerializer, responses=PayeeChangeSerializer)
    @action(detail=True, methods=["post"], url_path="client-approval")
    @idempotent
    def client_approval(self, request, pk=None):
        ch = self._obj(request, pk)
        d = _valid(ClientApprovalSerializer, request)
        services.client_approve_change(ch, request.user, mfa_at=_mfa(request, d.get("code")),
                                       code=d.get("code") or None, approve=d["approve"])
        ch.refresh_from_db()
        return Response(PayeeChangeSerializer(ch).data)

    @extend_schema(request=EscrowDecisionSerializer, responses=PayeeChangeSerializer)
    @action(detail=True, methods=["post"], permission_classes=[roles(*STAFF)])
    @idempotent
    def approvals(self, request, pk=None):
        ch = self._obj(request, pk)
        d = _valid(EscrowDecisionSerializer, request)
        services.decide_change(ch, request.user, decision=d["decision"], mfa_at=require_mfa(request),
                               note=d.get("note", ""))
        ch.refresh_from_db()
        return Response(PayeeChangeSerializer(ch).data)

    @extend_schema(request=StopSerializer, responses=PayeeChangeSerializer)
    @action(detail=True, methods=["post"])
    def stop(self, request, pk=None):
        ch = self._obj(request, pk)
        d = _valid(StopSerializer, request)
        mfa_at = None
        if not has_role(request.user, "RV", country=ch.country) and not d.get("code"):
            mfa_at = require_mfa(request)
        services.stop_change(ch, request.user, token=d.get("token", ""), mfa_at=mfa_at, code=d.get("code") or None,
                             reason=d.get("reason", ""))
        ch.refresh_from_db()
        return Response(PayeeChangeSerializer(ch).data)

    @extend_schema(request=None, responses=PayeeChangeSerializer)
    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        return Response(PayeeChangeSerializer(services.withdraw_change(self._obj(request, pk), request.user)).data)


# ----------------------------------------------------------------- administration of bank accounts and rates

class ProgrammeAccountViewSet(viewsets.GenericViewSet):
    serializer_class = ProgrammeAccountSerializer
    queryset = ProgrammeAccount.objects.none()
    permission_classes = [roles("AD")]

    @extend_schema(responses=ProgrammeAccountSerializer(many=True))
    def list(self, request):
        from accounts.selectors import scope_to_staff_countries

        qs = scope_to_staff_countries(ProgrammeAccount.objects.order_by("-created_at"), request.user)
        return Response(ProgrammeAccountSerializer(qs, many=True).data)

    @extend_schema(request=ProgrammeAccountIn, responses={201: ProgrammeAccountSerializer})
    @idempotent
    def create(self, request):
        from administration.models import Partner

        d = _valid(ProgrammeAccountIn, request)
        pa = services.create_programme_account(
            request.user, country=_country(d["country"]), bank_partner=_get(Partner, d["bank_partner_id"]),
            currency=d["currency"].upper(), kind=d["kind"], account_number=d["account_number"],
            account_name=d["account_name"], agreement_evidence=_evidence(d["agreement_evidence_id"]))
        return Response(ProgrammeAccountSerializer(pa).data, status=201)

    @extend_schema(request=EscrowDecisionSerializer, responses=ProgrammeAccountSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def approvals(self, request, pk=None):
        pa = _get(ProgrammeAccount, pk)
        d = _valid(EscrowDecisionSerializer, request)
        services.decide_programme_account(pa, request.user, decision=d["decision"], mfa_at=require_mfa(request),
                                          note=d.get("note", ""))
        pa.refresh_from_db()
        return Response(ProgrammeAccountSerializer(pa).data)


class ProgrammeRateViewSet(viewsets.GenericViewSet):
    serializer_class = ProgrammeRateSerializer
    queryset = ProgrammeRate.objects.none()
    permission_classes = [roles("AD", "CM", "RV")]

    @extend_schema(responses=ProgrammeRateSerializer(many=True))
    def list(self, request):
        from accounts.selectors import scope_to_staff_countries

        qs = scope_to_staff_countries(ProgrammeRate.objects.order_by("-valid_from"), request.user)
        return Response(ProgrammeRateSerializer(qs, many=True).data)

    @extend_schema(request=ProgrammeRateIn, responses={201: ProgrammeRateSerializer})
    @idempotent
    def create(self, request):
        from administration.models import Partner

        d = _valid(ProgrammeRateIn, request)
        pr = services.create_programme_rate(
            request.user, country=_country(d["country"]), bank_partner=_get(Partner, d["bank_partner_id"]),
            from_currency=d["from_currency"], to_currency=d["to_currency"], margin_pct=d["margin_pct"],
            fee_schedule=d["fee_schedule"], reference_source=_get(Partner, d["reference_source_id"]),
            valid_from=d["valid_from"], valid_to=d.get("valid_to"),
            agreement_evidence=_evidence(d["agreement_evidence_id"]), band_from=d.get("band_from") or 0,
            band_to=d.get("band_to"), tolerance_pct=d.get("tolerance_pct") or 0)
        return Response(ProgrammeRateSerializer(pr).data, status=201)

    @extend_schema(request=EscrowDecisionSerializer, responses=ProgrammeRateSerializer)
    @action(detail=True, methods=["post"], permission_classes=[roles("AD")])
    @idempotent
    def approvals(self, request, pk=None):
        pr = _get(ProgrammeRate, pk)
        d = _valid(EscrowDecisionSerializer, request)
        services.decide_programme_rate(pr, request.user, decision=d["decision"], mfa_at=require_mfa(request),
                                       note=d.get("note", ""))
        pr.refresh_from_db()
        return Response(ProgrammeRateSerializer(pr).data)


# ----------------------------------------------------------------- exchange

class FxQuoteViewSet(viewsets.GenericViewSet):
    serializer_class = FxQuoteSerializer
    queryset = FxQuote.objects.none()

    def _obj(self, request, pk):
        qt = FxQuote.objects.filter(pk=pk).select_related("escrow").first()
        if qt is None or not _can_see_escrow(request.user, qt.escrow):
            raise NotFound()
        return qt

    def retrieve(self, request, pk=None):
        return Response(FxQuoteSerializer(self._obj(request, pk)).data)

    @extend_schema(request=AcceptQuoteIn, responses=FxQuoteSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def accept(self, request, pk=None):
        qt = self._obj(request, pk)
        d = _valid(AcceptQuoteIn, request)
        services.accept_quote(qt, request.user, mfa_at=_mfa(request, d.get("code")), code=d.get("code") or None,
                              shown_sha256=d["shown_sha256"])
        qt.refresh_from_db()
        return Response(FxQuoteSerializer(qt).data)


class FxConversionViewSet(viewsets.GenericViewSet):
    serializer_class = FxConversionSerializer
    queryset = FxConversion.objects.none()
    permission_classes = [roles("CM", "RV", "AD")]

    def _obj(self, request, pk):
        c = FxConversion.objects.filter(pk=pk).first()
        if c is None or not _is_staff_for(request.user, c.country):
            raise NotFound()
        return c

    @extend_schema(request=NoteEvidenceSerializer, responses=FxConversionSerializer)
    @action(detail=True, methods=["post"], permission_classes=[roles("RV")])
    def resolve(self, request, pk=None):
        d = _valid(NoteEvidenceSerializer, request)
        c = services.resolve_conversion(self._obj(request, pk), request.user, note=d["note"],
                                        evidence=_evidence(d["evidence_id"]), claim_amount=d.get("claim_amount"),
                                        claim_reference=d.get("claim_reference", ""))
        return Response(FxConversionSerializer(c).data)

    @extend_schema(request=None, responses=FxConversionSerializer)
    @action(detail=True, methods=["post"], url_path="resolution-check")
    def resolution_check(self, request, pk=None):
        return Response(FxConversionSerializer(services.check_conversion_resolution(self._obj(request, pk),
                                                                                    request.user)).data)


@extend_schema(responses=ComparisonSerializer(many=True), parameters=[
    OpenApiParameter("country", str, required=True), OpenApiParameter("from", str), OpenApiParameter("amount", str)])
@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def fx_comparison(request):
    """FR-ESC-024: the day's comparison with each source, its time and stale marks."""
    country = _country(request.query_params.get("country"))
    data = services.comparison_for(country, from_currency=request.query_params.get("from"),
                                   amount=request.query_params.get("amount"))
    return Response(ComparisonSerializer(data, many=True).data)


class ObservationViewSet(viewsets.GenericViewSet):
    serializer_class = ObservationSerializer
    queryset = FxRateObservation.objects.none()
    permission_classes = [roles("CM", "AD", "RV")]

    @extend_schema(request=ObservationIn, responses={201: ObservationSerializer})
    def create(self, request):
        from administration.models import Partner

        d = _valid(ObservationIn, request)
        obs = services.enter_observation(
            request.user, country=_country(d["country"]), source_partner=_get(Partner, d["source_partner_id"]),
            kind=d["kind"], from_currency=d["from_currency"], to_currency=d["to_currency"], rate=d["rate"],
            proof_evidence=_evidence(d["proof_evidence_id"]), send_amount=d.get("send_amount"),
            fees_total=d.get("fees_total"), delivered_amount=d.get("delivered_amount"))
        return Response(ObservationSerializer(obs).data, status=201)

    @extend_schema(request=None, responses=ObservationSerializer)
    @action(detail=True, methods=["post"])
    def check(self, request, pk=None):
        return Response(ObservationSerializer(services.check_observation(_get(FxRateObservation, pk),
                                                                         request.user)).data)


@extend_schema(request=CollectIn, responses=ComparisonSerializer(many=True))
@api_view(["POST"])
@permission_classes([roles("AD", "CM")])
def fx_collect(request):
    """Run today's rate collection now (normally the daily job)."""
    from .fx import comparison_payload

    d = _valid(CollectIn, request)
    runs = services.collect_rates(_country(d["country"]), by=request.user)
    return Response(ComparisonSerializer([comparison_payload(r) for r in runs], many=True).data)
