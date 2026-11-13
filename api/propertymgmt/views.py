"""PMG API (02 section 7.4). Owners see their own properties; tenants their own tenancy, rent record and the
repairs they reported; inspectors the inspections assigned to them; staff their countries."""
from django.db.models import Q
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from core.errors import Forbidden, Invalid, NotFound
from core.idempotency import idempotent
from core.permissions import has_role
from core.views import ETagMixin, require_mfa

from . import serializers as S
from . import services
from .models import Inspection, ManagedProperty, RentPeriod, Repair, RepairQuote, StatementMandate, Tenancy

UUID_RE = r"[0-9a-fA-F-]{36}"


def _valid(cls, request):
    s = cls(data=request.data, context={"request": request})
    s.is_valid(raise_exception=True)
    return s.validated_data


def _country(code):
    from countries.models import Country

    c = Country.objects.filter(code=str(code or "").upper()).first()
    if c is None:
        raise Invalid("Unknown country.", code="validation-error")
    return c


def _person(pk):
    from accounts.models import Person

    p = Person.objects.filter(pk=pk).first() if pk else None
    if p is None:
        raise Invalid("Person not found.", code="validation-error")
    return p


def _scoped(qs, user):
    from accounts.selectors import scope_to_staff_countries

    return scope_to_staff_countries(qs, user)


class Base(ETagMixin, viewsets.GenericViewSet):
    permission_classes = [permissions.IsAuthenticated]
    lookup_value_regex = UUID_RE


class PropertyViewSet(Base, mixins.ListModelMixin, mixins.RetrieveModelMixin):
    """Managed properties (FR-PMG-001, FR-PMG-002, FR-PMG-003, FR-PMG-006)."""

    serializer_class = S.PropertySerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.serializer_class.Meta.model.objects.none()
        return services.properties_for(self.request.user).order_by("-created_at")

    def _out(self, request, prop, status=200):
        prop.refresh_from_db()
        return Response(S.PropertySerializer(prop, context={"request": request}).data, status=status)

    @extend_schema(request=S.PropertyCreate, responses={201: S.PropertySerializer})
    @idempotent
    def create(self, request):
        """Register a property; the onboarding case opens with a condition inspection (FR-PMG-001)."""
        d = _valid(S.PropertyCreate, request)
        owner = _person(d["owner_id"]) if d.get("owner_id") else request.user
        prop = services.register_property(
            request.user, owner=owner, country=_country(d["country"]), title=d["title"], locality=d["locality"],
            address=d["address"], region=d["region"], district=d["district"], ghana_post_gps=d["ghana_post_gps"],
            location=d.get("location"), asset_id=d.get("asset_id"),
            ownership_evidence_ids=d["ownership_evidence_ids"],
            inspection_interval_months=d.get("inspection_interval_months"))
        return self._out(request, prop, 201)

    @extend_schema(request=S.RentAccountIn, responses=S.PropertySerializer)
    @action(detail=True, methods=["put"], url_path="rent-account")
    def rent_account(self, request, pk=None):
        """Set the owner's own verified account as the rent destination (RUL-24)."""
        d = _valid(S.RentAccountIn, request)
        return self._out(request, services.set_rent_account(self.get_object(), request.user,
                                                            d["bank_account_id"]))

    @extend_schema(request=S.MandateIn, responses={201: S.MandateSerializer})
    @action(detail=True, methods=["post"], url_path="statement-mandates")
    @idempotent
    def statement_mandates(self, request, pk=None):
        """The owner's written mandate letting the bank share the rent account's statement lines."""
        d = _valid(S.MandateIn, request)
        m = services.record_mandate(self.get_object(), request.user, mandate_evidence_id=d["mandate_evidence_id"],
                                    valid_from=d.get("valid_from"), valid_to=d.get("valid_to"),
                                    bank_acknowledgement_evidence_id=d.get("bank_acknowledgement_evidence_id"),
                                    statement_ref=d.get("statement_ref", ""))
        return Response(S.MandateSerializer(m).data, status=201)

    @extend_schema(request=S.StatementUploadIn, responses={201: S.StatementImportSerializer})
    @action(detail=True, methods=["post"], url_path="rent-statements")
    @idempotent
    def rent_statements(self, request, pk=None):
        """Import the bank's statement for the rent account only (9.3). Lines for other accounts are refused."""
        d = _valid(S.StatementUploadIn, request)
        imp = services.import_rent_statement(self.get_object(), request.user, data=d["content"].encode(),
                                             original_name=d["original_name"], source=d["source"],
                                             owner_confirmed=d["owner_confirmed"])
        return Response(S.StatementImportSerializer(imp).data, status=201)

    @extend_schema(responses=S.StatementLineSerializer(many=True))
    @action(detail=True, methods=["get"], url_path="unmatched-lines")
    def unmatched_lines(self, request, pk=None):
        prop = self.get_object()
        return Response([{"id": str(ln.pk), "booked_on": ln.booked_on,
                          "amount": {"amount": f"{ln.amount:.2f}", "currency": ln.currency},
                          "bank_reference": ln.bank_reference, "counterparty_name": ln.counterparty_name,
                          "narrative": ln.narrative} for ln in services.unmatched_lines(prop)])

    @extend_schema(request=S.TenancyCreate, responses={201: S.TenancySerializer})
    @action(detail=True, methods=["post"])
    @idempotent
    def tenancies(self, request, pk=None):
        """Record the tenant, the agreement, the rent and the due day (FR-PMG-002)."""
        d = _valid(S.TenancyCreate, request)
        t = services.record_tenancy(self.get_object(), request.user, tenant_email=d["tenant_email"],
                                    tenant_name=d["tenant_name"], tenant_phone=d["tenant_phone"],
                                    tenant_id_number=d["tenant_id_number"],
                                    agreement_evidence_id=d.get("agreement_evidence_id"), rent=d["rent"],
                                    period=d["period"], due_day=d["due_day"], starts_on=d["starts_on"],
                                    ends_on=d.get("ends_on"), tenant_reference=d["tenant_reference"])
        return Response(S.TenancySerializer(t, context={"request": request}).data, status=201)

    @extend_schema(responses=S.RentPeriodSerializer(many=True))
    @action(detail=True, methods=["get"], url_path="rent-periods")
    def rent_periods(self, request, pk=None):
        """Rent due and received from statement matching (FR-PMG-003)."""
        prop = self.get_object()
        qs = RentPeriod.objects.filter(tenancy__property=prop).select_related("tenancy", "tenancy__property") \
            .order_by("period_start")
        return Response(S.RentPeriodSerializer(qs, many=True).data)

    @extend_schema(methods=["GET"], responses=S.InspectionSerializer(many=True))
    @extend_schema(methods=["POST"], request=S.InspectionCreate, responses={201: S.InspectionSerializer})
    @action(detail=True, methods=["get", "post"])
    def inspections(self, request, pk=None):
        """Periodic inspections (FR-PMG-006); staff schedule and assign."""
        prop = self.get_object()
        if request.method == "GET":
            return Response(S.InspectionSerializer(prop.inspections.order_by("-scheduled_for"), many=True).data)
        d = _valid(S.InspectionCreate, request)
        insp = services.schedule_inspection(prop, request.user, kind=d["kind"], scheduled_for=d.get("scheduled_for"),
                                            inspector=_person(d["inspector_id"]) if d.get("inspector_id") else None)
        return Response(S.InspectionSerializer(insp).data, status=201)

    @extend_schema(responses=S.TimelineItem(many=True))
    @action(detail=True, methods=["get"])
    def timeline(self, request, pk=None):
        """Rent, repairs and inspections in date order with photo previews (FR-PMG-006)."""
        return Response(services.timeline(self.get_object()))

    @extend_schema(request=S.ReasonIn, responses=S.PropertySerializer)
    @action(detail=True, methods=["post"])
    def pause(self, request, pk=None):
        return self._out(request, services.pause_property(self.get_object(), request.user,
                                                          _valid(S.ReasonIn, request)["reason"]))

    @extend_schema(request=None, responses=S.PropertySerializer)
    @action(detail=True, methods=["post"])
    def resume(self, request, pk=None):
        return self._out(request, services.resume_property(self.get_object(), request.user))

    @extend_schema(request=S.ReasonIn, responses=S.PropertySerializer)
    @action(detail=True, methods=["post"])
    def end(self, request, pk=None):
        return self._out(request, services.end_management(self.get_object(), request.user,
                                                          _valid(S.ReasonIn, request)["reason"]))


class MandateViewSet(Base, mixins.RetrieveModelMixin):
    serializer_class = S.MandateSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.serializer_class.Meta.model.objects.none()
        u = self.request.user
        qs = StatementMandate.objects.select_related("bank_account", "property")
        if services.is_staff(u):
            return _scoped(qs, u)
        return qs.filter(owner=u)

    @extend_schema(request=S.AcknowledgementIn, responses=S.MandateSerializer)
    @action(detail=True, methods=["post"])
    def acknowledgements(self, request, pk=None):
        """The bank's acknowledgement of the mandate; matching starts (FR-PMG-003)."""
        d = _valid(S.AcknowledgementIn, request)
        m = services.acknowledge_mandate(self.get_object(), request.user, evidence_id=d["evidence_id"],
                                         statement_ref=d["statement_ref"])
        return Response(S.MandateSerializer(m).data)

    @extend_schema(request=S.ReasonIn, responses=S.MandateSerializer)
    @action(detail=True, methods=["post"])
    def revocations(self, request, pk=None):
        m = services.revoke_mandate(self.get_object(), request.user, _valid(S.ReasonIn, request)["reason"])
        return Response(S.MandateSerializer(m).data)


class TenancyViewSet(Base, mixins.ListModelMixin, mixins.RetrieveModelMixin):
    """Agreement and rent record: the tenant's own, the owner's, or staff (FR-PMG-002, TC-RUL-24-04)."""

    serializer_class = S.TenancySerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.serializer_class.Meta.model.objects.none()
        u = self.request.user
        qs = Tenancy.objects.select_related("property", "property__owner", "property__rent_account", "tenant")
        if services.is_staff(u):
            return _scoped(qs, u).order_by("-created_at")
        return qs.filter(Q(tenant=u) | Q(property__owner=u)).order_by("-created_at")

    @extend_schema(request=S.EndTenancyIn, responses=S.TenancySerializer)
    @action(detail=True, methods=["post"])
    def end(self, request, pk=None):
        d = _valid(S.EndTenancyIn, request)
        t = services.end_tenancy(self.get_object(), request.user, reason=d["reason"], terminated=d["terminated"])
        return Response(S.TenancySerializer(t, context={"request": request}).data)


class RentPeriodViewSet(Base, mixins.RetrieveModelMixin):
    serializer_class = S.RentPeriodSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.serializer_class.Meta.model.objects.none()
        u = self.request.user
        qs = RentPeriod.objects.select_related("tenancy", "tenancy__property")
        if services.is_staff(u):
            from accounts.selectors import scope_to_staff_countries

            return scope_to_staff_countries(qs, u, field="tenancy__country")
        return qs.filter(Q(tenancy__property__owner=u) | Q(tenancy__tenant=u))

    @extend_schema(request=S.ManualMatchIn, responses=S.RentPeriodSerializer)
    @action(detail=True, methods=["post"], url_path="manual-matches")
    def manual_matches(self, request, pk=None):
        """Match an unmatched credit by hand; a second staff member checks it (US-PMG-003 AC3)."""
        d = _valid(S.ManualMatchIn, request)
        p = services.propose_manual_match(self.get_object(), request.user, line_id=d["statement_line_id"])
        return Response(S.RentPeriodSerializer(p).data)

    @extend_schema(request=S.MatchCheckIn, responses=S.RentPeriodSerializer)
    @action(detail=True, methods=["post"], url_path="manual-match-checks")
    def manual_match_checks(self, request, pk=None):
        d = _valid(S.MatchCheckIn, request)
        p = services.check_manual_match(self.get_object(), request.user, agree=d["agree"], note=d["note"])
        p.refresh_from_db()
        return Response(S.RentPeriodSerializer(p).data)

    @extend_schema(request=S.ReasonIn, responses=S.RentPeriodSerializer)
    @action(detail=True, methods=["post"], url_path="write-offs")
    def write_offs(self, request, pk=None):
        p = services.write_off(self.get_object(), request.user, _valid(S.ReasonIn, request)["reason"])
        return Response(S.RentPeriodSerializer(p).data)


class InspectionViewSet(Base, mixins.ListModelMixin, mixins.RetrieveModelMixin):
    """Property inspections: the inspector's own (IN asg), the owner's, staff."""

    serializer_class = S.InspectionSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.serializer_class.Meta.model.objects.none()
        u = self.request.user
        qs = Inspection.objects.select_related("property", "inspector", "repair")
        if services.is_staff(u):
            return _scoped(qs, u).order_by("-scheduled_for")
        return qs.filter(Q(inspector=u) | Q(property__owner=u)).order_by("-scheduled_for")

    @extend_schema(request=S.AssignIn, responses=S.InspectionSerializer)
    @action(detail=True, methods=["post"])
    def assignments(self, request, pk=None):
        insp = services.assign_inspector(self.get_object(), request.user,
                                         _person(_valid(S.AssignIn, request)["inspector_id"]))
        return Response(S.InspectionSerializer(insp).data)

    @extend_schema(request=S.InspectionResultIn, responses=S.InspectionSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def results(self, request, pk=None):
        """Record the visit: outcome, condition, rooms with photos taken in Tenmina Field."""
        insp = self.get_object()
        if services.is_owner(request.user, insp.property) and not services.is_staff(request.user, insp.country):
            raise NotFound()
        d = _valid(S.InspectionResultIn, request)
        insp = services.record_inspection(insp, request.user, outcome=d["outcome"],
                                          condition_rating=d.get("condition_rating", ""),
                                          rooms=[{**r, "evidence_ids": [str(x) for x in r["evidence_ids"]]}
                                                 for r in d.get("rooms", [])],
                                          photo_ids=[str(x) for x in d["photo_ids"]], checklist=d["checklist"],
                                          defects=d["defects"], notes=d["notes"])
        return Response(S.InspectionSerializer(insp).data)

    @extend_schema(request=S.ReasonIn, responses=S.InspectionSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        insp = services.cancel_inspection(self.get_object(), request.user, _valid(S.ReasonIn, request)["reason"])
        return Response(S.InspectionSerializer(insp).data)


class RepairViewSet(Base, mixins.ListModelMixin, mixins.RetrieveModelMixin):
    """Repairs (FR-PMG-004, FR-PMG-005)."""

    serializer_class = S.RepairSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.serializer_class.Meta.model.objects.none()
        return services.repairs_for(self.request.user).order_by("-created_at")

    def _out(self, request, r, status=200):
        r.refresh_from_db()
        return Response(S.RepairSerializer(r, context={"request": request}).data, status=status)

    @extend_schema(request=S.RepairCreate, responses={201: S.RepairSerializer})
    @idempotent
    def create(self, request):
        """A tenant, the owner, an assigned inspector or staff report a repair with photos."""
        d = _valid(S.RepairCreate, request)
        prop = ManagedProperty.objects.filter(pk=d["property_id"]).first()
        if prop is None:
            raise NotFound("Property not found.")
        r = services.report_repair(request.user, prop, title=d["title"], description=d["description"],
                                   photo_ids=[str(x) for x in d["photo_ids"]], urgent=d["urgent"])
        return self._out(request, r, 201)

    @extend_schema(request=S.QuoteIn, responses={201: S.QuoteSerializer})
    @action(detail=True, methods=["post"])
    @idempotent
    def quotes(self, request, pk=None):
        """Add a quote from a vetted panel contractor with a verified payee (CM)."""
        from escrow.models import Payee

        d = _valid(S.QuoteIn, request)
        payee = Payee.objects.filter(pk=d["payee_id"]).first()
        if payee is None:
            raise Invalid("Payee not found.", code="validation-error")
        qt = services.add_quote(self.get_object(), request.user, contractor=_person(d["contractor_id"]), payee=payee,
                                amount=d["amount"], evidence_id=d["evidence_id"], valid_until=d.get("valid_until"),
                                description=d["description"])
        return Response(S.QuoteSerializer(qt).data, status=201)

    @extend_schema(request=S.ReasonIn, responses=S.RepairSerializer)
    @action(detail=True, methods=["post"], url_path="single-quote-exceptions")
    def single_quote_exceptions(self, request, pk=None):
        """A reviewer records an exception with a reason to proceed with one quote (US-PMG-004 AC2)."""
        return self._out(request, services.single_quote_exception(self.get_object(), request.user,
                                                                  _valid(S.ReasonIn, request)["reason"]))

    @extend_schema(request=S.QuoteApprovalIn, responses={201: S.QuoteApprovalResult})
    @action(detail=True, methods=["post"], url_path="quote-approvals")
    @idempotent
    def quote_approvals(self, request, pk=None):
        """7.11: the owner approves one quote with an MFA step-up; a repair escrow is proposed (RUL-11)."""
        from escrow.services import payment_instructions

        r = self.get_object()
        if not services.is_owner(request.user, r.property):
            raise NotFound()
        d = _valid(S.QuoteApprovalIn, request)
        mfa_at = require_mfa(request)
        r = services.approve_quote(r, request.user, quote_id=d["quote_id"], confirm_amount=d["confirm_amount"],
                                   mfa_at=mfa_at)
        qt, e = r.approved_quote, r.escrow
        done = RepairQuote.objects.filter(contractor=qt.contractor, repair__status="paid").count()
        body = {"repair_id": str(r.pk), "status": r.status,
                "approved_quote": {"id": str(qt.pk), "contractor": {"name": qt.payee.legal_name,
                                                                    "track_record": {"completed": done,
                                                                                     "disputes": 0},
                                                                    "payee_status": qt.payee.verification_status},
                                   "amount": {"amount": f"{qt.quote_amount:.2f}", "currency": qt.quote_currency}},
                "quotes_considered": r.quotes.exclude(status="withdrawn").count(),
                "escrow": {"id": str(e.pk), "reference": e.reference, "status": e.status,
                           "pay_to": payment_instructions(e)},
                "next": "Pay the amount to the bank. Work starts when the bank confirms. The contractor is paid "
                        "after our inspector passes the work."}
        return Response(body, status=201)

    @extend_schema(request=S.WorkDoneIn, responses=S.RepairSerializer)
    @action(detail=True, methods=["post"], url_path="work-done")
    @idempotent
    def work_done(self, request, pk=None):
        d = _valid(S.WorkDoneIn, request)
        return self._out(request, services.record_work_done(self.get_object(), request.user,
                                                            evidence_ids=[str(x) for x in d["evidence_ids"]],
                                                            note=d["note"]))

    @extend_schema(request=S.RepairInspectionCreate, responses={201: S.InspectionSerializer})
    @action(detail=True, methods=["post"])
    def inspections(self, request, pk=None):
        """Schedule the repair inspection and assign an inspector (CM). The inspector records it."""
        r = self.get_object()
        d = _valid(S.RepairInspectionCreate, request)
        insp = services.schedule_inspection(r.property, request.user, kind="repair", repair=r,
                                            scheduled_for=d.get("scheduled_for"),
                                            inspector=_person(d["inspector_id"]) if d.get("inspector_id") else None)
        return Response(S.InspectionSerializer(insp).data, status=201)

    @extend_schema(request=None, responses={201: S.InstructionResult})
    @action(detail=True, methods=["post"])
    @idempotent
    def instructions(self, request, pk=None):
        """The instruction to pay the contractor after an inspection pass (FR-PMG-005, RUL-22)."""
        r = self.get_object()
        ins = services.prepare_instruction(r, request.user)
        r.refresh_from_db()
        return Response({"repair_id": str(r.pk), "instruction_id": str(ins.pk), "status": ins.status,
                         "amount": {"amount": f"{ins.amount:.2f}", "currency": ins.currency},
                         "payee": ins.payee.legal_name}, status=201)

    @extend_schema(request=S.CloseRepairIn, responses=S.RepairSerializer)
    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        d = _valid(S.CloseRepairIn, request)
        return self._out(request, services.close_repair(self.get_object(), request.user, reason=d["reason"],
                                                        reject=d["reject"]))


class QuoteViewSet(Base, mixins.RetrieveModelMixin):
    serializer_class = S.QuoteSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.serializer_class.Meta.model.objects.none()
        u = self.request.user
        qs = RepairQuote.objects.select_related("repair", "contractor", "payee")
        if services.is_staff(u):
            return _scoped(qs, u)
        return qs.filter(Q(repair__property__owner=u) | Q(contractor=u))

    @extend_schema(request=S.ReasonIn, responses=S.QuoteSerializer)
    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        qt = services.withdraw_quote(self.get_object(), request.user, _valid(S.ReasonIn, request)["reason"])
        return Response(S.QuoteSerializer(qt).data)


@extend_schema(request=None, responses=S.JobResult)
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def run_rent_watch(request):
    """Run propertymgmt.match_rent now: next periods and late rent alerts (staff)."""
    if not has_role(request.user, "CM", "RV", "AD"):
        raise Forbidden()
    return Response({"result": services.rent_watch()})


@extend_schema(request=None, responses=S.JobResult)
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def run_inspection_schedule(request):
    """Run propertymgmt.schedule_inspections now (staff)."""
    if not has_role(request.user, "CM", "RV", "AD"):
        raise Forbidden()
    return Response({"result": {"scheduled": services.scheduled_inspection_watch()}})
