"""DPR services: the public interface other modules may call."""
import csv
import hashlib
import io
import json
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from audit.services import record
from core import approvals, state
from core.errors import DomainError, Forbidden, Invalid, RuleBlocked, StateConflict
from core.events import publish
from core.permissions import has_role

from . import registry, selectors
from .models import (BulkExport, Consent, DataCatalogueEntry, DataLocation, DataRequest, LegalHold,
                     PrivacyAcceptance, PrivacyNotice, RetentionRule, RetentionRun)

DPR_ROLES = ("AD", "DPO")
HOLD_ROLES = ("LW", "AD", "DPO", "RV")
VIDEO_ROLES = ("LW", "SV", "RN", "CM", "RV")
CLIENT_PURPOSES = {"partner_status", "partner_full_report", "case_study", "marketing"}
EXPORT_FIELDS = {"full_name", "email", "phone", "residence_country", "preferred_language", "created_at", "status"}
EXPORT_LINK_HOURS = 24  # 10.9, assumption


def _now():
    return timezone.now()


def _country_of(person):
    from countries.models import Country

    return getattr(person, "home_country", None) or Country.objects.filter(code="GH").first()


def _cfg(country, key, default):
    from countries.selectors import config

    return config(country, key, default) if country is not None else default


def _notify(person, template, body, needs_action=False, obj=None, channels=("in_app",)):
    from notifications.services import notify

    return notify(person, template, body=body, needs_action=needs_action, subject_obj=obj, channels=channels)


def _require(by, *roles_, msg="You do not have permission for this."):
    if not has_role(by, *roles_):
        raise Forbidden(msg)


def _alert(country, roles_, template, body, obj=None):
    from accounts.services import _staff_in

    for p in _staff_in(country, *roles_):
        _notify(p, template, body, obj=obj)


# ---------------------------------------------------------------- privacy notice (FR-DPR-001)

@transaction.atomic
def publish_notice(by, *, version, text, title="How Tenmina uses your data", summary="", country=None):
    """A new version makes every person accept again at next sign-in."""
    _require(by, *DPR_ROLES, msg="Only an administrator or the data protection officer publishes the notice.")
    try:
        with transaction.atomic():
            n = PrivacyNotice.objects.create(country=country, version=str(version), title=title, summary=summary,
                                             text=text)
    except IntegrityError as exc:
        raise Invalid("This version already exists.", code="validation-error") from exc
    for old in PrivacyNotice.objects.filter(country=country, status="published"):
        state.transition(old, "privacy_notice", "retired", actor=by)
    n.published_at = _now()
    n.published_by = by
    state.transition(n, "privacy_notice", "published", actor=by, event="privacy_notice.published",
                     extra_fields=["published_at", "published_by"], payload={"version": n.version})
    return n


@transaction.atomic
def accept_notice(person, version, *, source="portal", ip="") -> PrivacyAcceptance:
    notice = selectors.current_notice(getattr(person, "home_country", None))
    if notice is None:
        raise StateConflict("There is no privacy notice to accept.")
    if str(version) != str(notice.version):
        raise Invalid("Accept the current version of the privacy notice.", code="privacy-notice-required",
                      extra={"privacy_notice_version": notice.version})
    acc, created = PrivacyAcceptance.objects.get_or_create(person=person, notice=notice, defaults={
        "version": notice.version, "ip": ip or "", "source": source})
    if created:
        record(actor=person, action="privacy_notice.accepted", entity="person", entity_id=person.pk,
               data={"version": notice.version, "source": source})
        publish("consent.changed", acc.pk, {"person_id": person.pk, "purpose": "privacy_notice",
                                            "status": "given", "version": notice.version})
    return acc


# ---------------------------------------------------------------- consents (FR-DPR-002, RUL-16)

def _consent_changed(c, status_):
    publish("consent.changed", c.pk, {"consent_id": c.pk, "person_id": c.person_id, "purpose": c.purpose,
                                      "partner_client_id": c.partner_client_id, "report_id": c.report_id,
                                      "case_id": c.case_id, "status": status_})


@transaction.atomic
def give_consent(person, *, purpose, text_version, partner_client_id=None, report_id=None, case_id=None,
                 country=None) -> Consent:
    if purpose not in CLIENT_PURPOSES:
        raise Invalid("This consent is not given here.", code="validation-error")
    if purpose in ("partner_status", "partner_full_report") and not partner_client_id:
        raise Invalid("Choose the partner you consent to share with.", code="validation-error")
    if purpose in ("partner_full_report", "case_study") and not report_id:
        raise Invalid("Choose the report this consent is for.", code="validation-error")
    existing = selectors.active_consents(person, purpose).filter(partner_client_id=partner_client_id,
                                                                 report_id=report_id).first()
    if existing:
        return existing
    c = Consent.objects.create(country=country or _country_of(person), person=person, purpose=purpose,
                               text_version=text_version, partner_client_id=partner_client_id, report_id=report_id,
                               case_id=case_id, recorded_by=person)
    record(actor=person, action="consent.given", entity="consent", entity_id=c.pk,
           data={"purpose": purpose, "text_version": text_version}, country=c.country)
    _consent_changed(c, "given")
    return c


@transaction.atomic
def record_video_consent(by, *, subject_name, recording_evidence, text_version, case_id=None, person=None,
                         subject_phone="", role_in_recording="") -> Consent:
    """US-DPR-002 AC2: the person, the purpose and the text version are
    stored, linked to the recording."""
    _require(by, *VIDEO_ROLES, msg="Only the team on the case records consent on video.")
    if not subject_name and person is None:
        raise Invalid("Name the person who gave consent.", code="validation-error")
    c = Consent.objects.create(country=recording_evidence.country, person=person,
                               subject_name=subject_name or (person.full_name if person else ""),
                               subject_phone=subject_phone or "", purpose="video_recording",
                               text_version=text_version, case_id=case_id, recording_evidence=recording_evidence,
                               role_in_recording=role_in_recording or "", recorded_by=by)
    from evidence.services import link

    link(recording_evidence, "consent", c.pk, role="consent_recording", by=by)
    record(actor=by, action="consent.recorded", entity="consent", entity_id=c.pk,
           data={"purpose": "video_recording", "evidence_id": str(recording_evidence.pk),
                 "case_id": str(case_id) if case_id else None}, country=c.country)
    _consent_changed(c, "given")
    return c


@transaction.atomic
def withdraw_consent(c: Consent, by) -> Consent:
    if c.person_id != by.pk and c.recorded_by_id != by.pk and not has_role(by, *DPR_ROLES, "CM", "RV"):
        raise Forbidden("You can withdraw only your own consent.")
    if c.purpose == "privacy_notice":
        raise StateConflict("To stop using Tenmina, delete your account instead.")
    if c.withdrawn_at:
        return c
    c.withdrawn_at = _now()
    c.withdrawn_by = by
    c.save(update_fields=["withdrawn_at", "withdrawn_by"])
    record(actor=by, action="consent.withdrawn", entity="consent", entity_id=c.pk, data={"purpose": c.purpose},
           country=c.country)
    _consent_changed(c, "withdrawn")
    return c


@transaction.atomic
def attach_recording(by, *, evidence, case_id):
    """US-DPR-002 AC1: a consent video with no consent record cannot be
    attached to the case."""
    _require(by, *VIDEO_ROLES, msg="Only the team on the case attaches recordings.")
    if not selectors.recording_has_consent(evidence.pk):
        raise RuleBlocked("Record the consent of every person in the video first.", code="consent-missing",
                          blocking_reasons=[{"rule": "FR-DPR-002", "message": "No consent record for this video"}])
    from evidence.services import link

    lk = link(evidence, "case", case_id, role="consent_video", by=by)
    record(actor=by, action="recording.attached", entity="evidence", entity_id=evidence.pk,
           data={"case_id": str(case_id)}, country=evidence.country)
    return lk


# ---------------------------------------------------------------- subject requests (FR-DPR-003)

def _due(country):
    return timezone.localdate() + timedelta(days=int(_cfg(country, "dpr.request_due_days", 30)))  # [TO VERIFY]


@transaction.atomic
def create_request(by, *, subject, type, source="portal", details="") -> DataRequest:
    if type not in ("access", "correction", "erasure"):
        raise Invalid("Use account deletion for deleting your own account.", code="validation-error")
    if subject.pk != by.pk:
        _require(by, *DPR_ROLES, msg="Only an administrator records a request for someone else.")
        source = "staff"
    country = _country_of(subject)
    req = DataRequest.objects.create(country=country, subject=subject, requested_by=by, type=type, source=source,
                                     details=details or "", due_on=_due(country))
    record(actor=by, action="dpr_request.created", entity="dpr_request", entity_id=req.pk,
           data={"type": type, "source": source, "subject_id": str(subject.pk)}, country=country)
    publish("dpr_request.created", req.pk, {"request_id": req.pk, "type": type, "subject_id": subject.pk})
    _alert(country, DPR_ROLES, "dpr_request_new", f"New {type} request, due {req.due_on}.", obj=req)
    return req


def _export_accounts(person):
    from accounts.models import (BankAccount, FamilyMember, IdentityCheck, Membership, NationalIdCheck,
                                 ProfessionalLicence, RepresentativeGrant, Vetting)
    from accounts.normalise import mask

    return {
        "profile": {"id": str(person.pk), "full_name": person.full_name, "email": person.email,
                    "phone": person.phone, "preferred_language": person.preferred_language,
                    "residence_country": person.residence_country,
                    "home_country": getattr(person.home_country, "code", None), "status": person.status,
                    "preferred_channel": person.preferred_channel, "channels_off": person.channels_off,
                    "created_at": person.created_at.isoformat()},
        "roles": sorted(person.roles()),
        "organisations": [{"organisation": m.organisation.name, "org_role": m.org_role, "status": m.status}
                          for m in Membership.objects.filter(person=person).select_related("organisation")],
        "family_members": [{"full_name": f.full_name, "relationship": f.relationship, "phone": f.phone,
                            "address": f.address, "status": f.status}
                           for f in FamilyMember.objects.filter(client=person)],
        "bank_accounts": [{"bank_name": b.bank_name, "account_number": mask(b.account_number),
                           "account_name": b.account_name, "status": b.verification_status}
                          for b in BankAccount.objects.filter(holder=person)],
        "identity_checks": [{"method": c.method, "status": c.status, "document_type": c.document_type,
                             "date": c.created_at.isoformat()} for c in IdentityCheck.objects.filter(person=person)],
        "national_identity_checks": [{"result": c.result, "reference": c.provider_reference,
                                      "checked_at": c.checked_at.isoformat() if c.checked_at else None}
                                     for c in NationalIdCheck.objects.filter(person=person)],
        "licences": [{"role": x.role, "body": x.body, "number": x.number, "expires_on": x.expires_on.isoformat(),
                      "status": x.status} for x in ProfessionalLicence.objects.filter(person=person)],
        "vettings": [{"kind": v.kind, "status": v.status} for v in Vetting.objects.filter(person=person)],
        "representatives_named": [{"email": g.invited_email, "subject_type": g.subject_type, "status": g.status}
                                  for g in RepresentativeGrant.objects.filter(client=person)],
    }


def _export_dpr(person):
    return {
        "privacy_acceptances": [{"version": a.version, "accepted_at": a.accepted_at.isoformat()}
                                for a in PrivacyAcceptance.objects.filter(person=person)],
        "consents": [{"purpose": c.purpose, "text_version": c.text_version, "given_at": c.given_at.isoformat(),
                      "withdrawn_at": c.withdrawn_at.isoformat() if c.withdrawn_at else None}
                     for c in Consent.objects.filter(person=person)],
        "requests": [{"type": r.type, "status": r.status, "created_at": r.created_at.isoformat()}
                     for r in DataRequest.objects.filter(subject=person)],
    }


def _export_messages(person):
    from notifications.models import Message

    return [{"channel": m.channel, "subject": m.subject, "body": m.body, "created_at": m.created_at.isoformat()}
            for m in Message.objects.filter(person=person).order_by("created_at")[:1000]]


registry.exporter("accounts")(_export_accounts)
registry.exporter("data_protection")(_export_dpr)
registry.exporter("messages")(_export_messages)


@transaction.atomic
def run_export(req: DataRequest, by) -> DataRequest:
    """US-DPR-003 AC1: everything held about the person, logged."""
    _require(by, *DPR_ROLES, msg="Only an administrator runs an export.")
    if req.type != "access":
        raise StateConflict("Only an access request produces an export.")
    if req.status in ("completed", "rejected"):
        raise StateConflict("This request is closed.")
    pack = {"subject_id": str(req.subject_id), "generated_at": _now().isoformat(),
            "data": registry.collect_export(req.subject)}
    data = json.dumps(pack, indent=2, sort_keys=True, default=str).encode()
    from evidence.services import link, store

    ev = store(data=data, country=req.country, uploaded_by=by, content_type="application/json",
               original_name=f"subject-access-{req.subject_id}.json", source="generated",
               description="Subject access export")
    link(ev, "dpr_request", req.pk, role="subject_access_export", by=by)
    req.export_evidence = ev
    req.export_sha256 = ev.sha256
    req.completed_at = _now()
    req.completed_by = by
    state.transition(req, "data_request", "completed", actor=by, event="dpr_request.completed",
                     extra_fields=["export_evidence", "export_sha256", "completed_at", "completed_by"],
                     payload={"type": "access", "sha256": ev.sha256})
    _notify(req.subject, "dpr_export_ready", obj=req, channels=("in_app", "email"),
            body="The copy of your data you asked for is ready. Tenmina will send it to you securely.")
    return req


CORRECTABLE = {"full_name", "email", "phone", "preferred_language", "residence_country"}


@transaction.atomic
def apply_correction(req: DataRequest, by, *, field, value) -> DataRequest:
    """US-DPR-003 AC2: the old value stays in the audit log."""
    _require(by, *DPR_ROLES, msg="Only an administrator applies a correction.")
    if req.type != "correction" or req.status in ("completed", "rejected"):
        raise StateConflict("This request does not take corrections.")
    if field not in CORRECTABLE:
        raise Invalid(f"Only these fields are corrected here: {', '.join(sorted(CORRECTABLE))}.",
                      code="validation-error")
    from accounts.models import Person
    from accounts.normalise import normalise_phone

    p = req.subject
    if field == "email":
        value = (value or "").lower().strip()
        if Person.objects.filter(email=value).exclude(pk=p.pk).exists():
            raise Invalid("This email cannot be used.", code="validation-error")
    if field == "phone":
        value = normalise_phone(value)
        if Person.objects.filter(phone=value).exclude(pk=p.pk).exists():
            raise Invalid("This number cannot be used.", code="validation-error")
    old = getattr(p, field)
    setattr(p, field, value)
    p.save(update_fields=[field])
    record(actor=by, action="person.corrected", entity="person", entity_id=p.pk,
           data={"field": field, "old": old, "new": value, "request_id": str(req.pk)})
    req.corrections = [*req.corrections, {"field": field, "at": _now().isoformat(), "by": str(by.pk)}]
    req.save(update_fields=["corrections"])
    if req.status == "open":
        state.transition(req, "data_request", "in_progress", actor=by)
    return req


@transaction.atomic
def complete_request(req: DataRequest, by) -> DataRequest:
    _require(by, *DPR_ROLES, msg="Only an administrator closes a request.")
    if req.type == "access" and not req.export_evidence_id:
        raise StateConflict("Run the export first.")
    req.completed_at = _now()
    req.completed_by = by
    state.transition(req, "data_request", "completed", actor=by, event="dpr_request.completed",
                     extra_fields=["completed_at", "completed_by"], payload={"type": req.type})
    _notify(req.subject, "dpr_request_done", obj=req, body=f"Your {req.type} request is complete.")
    return req


@transaction.atomic
def reject_request(req: DataRequest, by, reason) -> DataRequest:
    _require(by, *DPR_ROLES, msg="Only an administrator refuses a request.")
    if not reason:
        raise Invalid("Give the reason.", code="validation-error")
    req.rejection_reason = reason
    state.transition(req, "data_request", "rejected", actor=by, reason=reason, extra_fields=["rejection_reason"])
    _notify(req.subject, "dpr_request_refused", obj=req, body=f"Your {req.type} request was refused: {reason}")
    return req


def overdue_requests():
    return DataRequest.objects.filter(status__in=["open", "in_progress"], due_on__lt=timezone.localdate())


def alert_overdue_requests() -> int:
    n = 0
    for req in overdue_requests():
        _alert(req.country, DPR_ROLES, "dpr_request_overdue",
               f"A {req.type} request was due on {req.due_on} and is still open.", obj=req)
        n += 1
    return n


# ---------------------------------------------------------------- account deletion (FR-APP-004, erasure)

DELETED_ON_REQUEST = [
    "Your profile: name, email, phone, language and preferences",
    "Your sign-in, sessions, app tokens and device keys",
    "Family members you added and your saved bank accounts, unless an open payment needs them",
    "Your notification preferences and push tokens",
]


def _rule_for(country, data_class):
    return (RetentionRule.objects.filter(status="active", data_class=data_class, country=country).first()
            or RetentionRule.objects.filter(status="active", data_class=data_class, country__isnull=True).first())


def kept_statement(person) -> list[dict]:
    """What is kept after deletion, why and for how long (US-APP-004 AC1)."""
    country = _country_of(person)
    out = []
    classes = RetentionRule.objects.filter(status="active", kept_on_deletion=True).values_list(
        "data_class", flat=True).distinct()
    for dc in sorted(set(classes)):
        r = _rule_for(country, dc)
        if r is None:
            continue
        until = f"{r.period_days} days from {r.anchor.replace('_', ' ')}" if r.period_days else \
            "[TO VERIFY] (period not yet set)"
        out.append({"data_class": dc, "what": r.description, "why": r.reason, "until": until})
    return out


def deletion_preview(person) -> dict:
    matters = registry.collect_open_matters(person)
    holds = selectors.holds_on([("person", person.pk)])
    blocking = list(matters) + [{"kind": "legal_hold", "id": str(h.pk), "title": "Legal hold",
                                 "reason": "Records are held for a legal claim and cannot be deleted yet."}
                                for h in holds]
    return {"deleted": DELETED_ON_REQUEST, "kept": kept_statement(person), "open_matters": blocking,
            "can_complete_now": not blocking}


@transaction.atomic
def request_deletion(person, *, by=None, source="app", req: DataRequest | None = None) -> DataRequest:
    """US-APP-004: deletion from inside either app. With nothing open the
    account closes and its personal data is anonymised at once; with an open
    escrow or a legal hold the request waits, the account closes to new
    orders and the held records are kept."""
    by = by or person
    open_req = DataRequest.objects.filter(subject=person, type__in=["deletion", "erasure"],
                                          status__in=["open", "in_progress", "waiting"]).first()
    if req is None and open_req is not None:
        return process_deletion(open_req)
    preview = deletion_preview(person)
    if req is None:
        country = _country_of(person)
        req = DataRequest.objects.create(country=country, subject=person, requested_by=by, type="deletion",
                                         source=source, due_on=_due(country))
    req.kept_statement = preview["kept"]
    req.open_matters = preview["open_matters"]
    req.save(update_fields=["kept_statement", "open_matters"])
    record(actor=by, action="account.deletion_requested", entity="person", entity_id=person.pk,
           data={"request_id": str(req.pk), "source": source, "open_matters": len(preview["open_matters"])})
    publish("account.deletion_requested", req.pk, {"person_id": person.pk, "request_id": req.pk,
                                                   "source": source})
    return process_deletion(req)


@transaction.atomic
def process_deletion(req: DataRequest) -> DataRequest:
    from accounts import services as acc

    person = req.subject
    preview = deletion_preview(person)
    if preview["open_matters"]:
        req.open_matters = preview["open_matters"]
        req.save(update_fields=["open_matters"])
        if req.status != "waiting":
            state.transition(req, "data_request", "waiting", reason="Open matters")
            acc.mark_closing(person)
            items = "; ".join(m["title"] for m in preview["open_matters"])
            _notify(person, "deletion_waiting", obj=req, channels=("in_app", "email"),
                    body=f"We recorded your request to delete your account. It closes to new orders now. These "
                         f"stay open until they finish: {items}. We delete the rest when they end.")
        return req
    acc.anonymise_person(person)
    req.open_matters = []
    req.completed_at = _now()
    state.transition(req, "data_request", "completed", event="account.deleted",
                     extra_fields=["open_matters", "completed_at"], payload={"person_id": person.pk})
    return req


def process_waiting_deletions() -> int:
    n = 0
    for req in DataRequest.objects.filter(type__in=["deletion", "erasure"], status="waiting"):
        process_deletion(req)
        n += 1
    return n


@transaction.atomic
def run_erasure(req: DataRequest, by) -> DataRequest:
    _require(by, *DPR_ROLES, msg="Only an administrator carries out an erasure.")
    if req.type != "erasure" or req.status in ("completed", "rejected"):
        raise StateConflict("This request is not an open erasure request.")
    if req.status == "open":
        state.transition(req, "data_request", "in_progress", actor=by)
    return request_deletion(req.subject, by=by, source="staff", req=req)


# ---------------------------------------------------------------- retention (FR-DPR-004)

@transaction.atomic
def save_rule(by, *, data_class, period_days=None, anchor="creation", action="anonymise", country=None,
              description="", reason="", kept_on_deletion=False, rule: RetentionRule | None = None) -> RetentionRule:
    _require(by, *DPR_ROLES, msg="Only an administrator sets retention rules.")
    if rule is None:
        old = RetentionRule.objects.filter(status="active", data_class=data_class, country=country).first()
        if old:
            old.status = "retired"
            old.save(update_fields=["status"])
        rule = RetentionRule(data_class=data_class, country=country)
    before = {"period_days": rule.period_days, "action": rule.action} if rule.pk else None
    rule.period_days = period_days
    rule.anchor = anchor
    rule.action = action
    rule.description = description
    rule.reason = reason
    rule.kept_on_deletion = kept_on_deletion
    rule.updated_by = by
    rule.save()
    record(actor=by, action="retention_rule.saved", entity="retention_rule", entity_id=rule.pk,
           data={"data_class": data_class, "period_days": period_days, "before": before})
    return rule


def run_retention(by=None, *, now=None) -> RetentionRun:
    """Nightly job dataprotection.retention_sweep (6.10): list expired
    records, skip any under a legal hold, then delete or anonymise."""
    now = now or _now()
    run = RetentionRun.objects.create(started_by=by)
    results = {}
    rules = list(RetentionRule.objects.filter(status="active").select_related("country"))
    own = {}
    for r in rules:
        if r.country_id:
            own.setdefault(r.data_class, []).append(r.country_id)
    for r in rules:
        key = f"{r.data_class}:{getattr(r.country, 'code', 'all')}"
        res = {"applied": 0, "held": 0, "skipped": None, "holds": []}
        results[key] = res
        if r.period_days is None:
            res["skipped"] = "Period is [TO VERIFY]; nothing deleted"
            continue
        finders = registry.finders(r.data_class)
        if not finders:
            res["skipped"] = "No records of this class are swept yet"
            continue
        scope = registry.Scope(country=r.country, exclude=[] if r.country_id else own.get(r.data_class, []))
        cutoff = now - timedelta(days=r.period_days)
        for fn in finders:
            for cand in fn(scope, cutoff):
                holds = selectors.holds_on([(cand.subject_type, cand.subject_id), *cand.related])
                if holds:
                    res["held"] += 1
                    res["holds"].append({"subject": f"{cand.subject_type}:{cand.subject_id}",
                                         "reason": holds[0].reason})
                    continue
                with transaction.atomic():
                    cand.apply()
                    record(action=f"retention.{r.action}", entity=cand.subject_type, entity_id=cand.subject_id,
                           data={"data_class": r.data_class, "rule_id": str(r.pk), "run_id": str(run.pk)})
                res["applied"] += 1
    run.results = results
    run.finished_at = _now()
    run.save(update_fields=["results", "finished_at"])
    record(actor=by, action="retention.sweep", entity="retention_run", entity_id=run.pk,
           data={k: {"applied": v["applied"], "held": v["held"]} for k, v in results.items()})
    return run


@registry.retention("account")
def _expired_accounts(scope, cutoff):
    """Closed accounts past the account period are anonymised."""
    from accounts.models import Person
    from accounts.services import anonymise_person

    qs = scope.filter(Person.objects.filter(status="closed", closed_at__lt=cutoff), "home_country")
    for p in qs:
        yield registry.Candidate("person", p.pk, apply=lambda p=p: anonymise_person(p))


@registry.retention("family")
def _expired_family(scope, cutoff):
    """Removed family members past the family period are anonymised."""
    from accounts.models import FamilyMember
    from accounts.services import anonymise_family_member

    qs = scope.filter(FamilyMember.objects.filter(status="removed", removed_at__lt=cutoff))
    for fm in qs:
        yield registry.Candidate("family_member", fm.pk, apply=lambda fm=fm: anonymise_family_member(fm),
                                 related=[("person", fm.client_id)])


@registry.retention("marketing")
def _expired_marketing(scope, cutoff):
    """Marketing consents not renewed within the period are withdrawn."""
    qs = scope.filter(Consent.objects.filter(purpose="marketing", withdrawn_at__isnull=True, given_at__lt=cutoff))
    for c in qs:
        def apply(c=c):
            c.withdrawn_at = _now()
            c.save(update_fields=["withdrawn_at"])
            _consent_changed(c, "withdrawn")
        yield registry.Candidate("consent", c.pk, apply=apply, related=[("person", c.person_id)])


# ---------------------------------------------------------------- legal holds (US-DPR-004b)

@transaction.atomic
def place_hold(by, *, subject_type, subject_id, reason, country=None) -> LegalHold:
    """A hold protects at once. Lifting needs two people."""
    _require(by, *HOLD_ROLES, msg="Only a lawyer, reviewer or administrator places a legal hold.")
    if not reason:
        raise Invalid("Give the reason for the hold.", code="validation-error")
    h = LegalHold.objects.create(country=country or _country_of(by), subject_type=subject_type,
                                 subject_id=subject_id, reason=reason, placed_by=by)
    record(actor=by, action="legal_hold.placed", entity="legal_hold", entity_id=h.pk,
           data={"subject_type": subject_type, "subject_id": str(subject_id), "reason": reason}, country=h.country)
    publish("legal_hold.placed", h.pk, {"hold_id": h.pk, "subject_type": subject_type, "subject_id": subject_id})
    return h


@transaction.atomic
def request_lift(h: LegalHold, by, reason) -> LegalHold:
    _require(by, *HOLD_ROLES, msg="Only a lawyer, reviewer or administrator asks to lift a hold.")
    if h.status != "active":
        raise StateConflict("This hold is not active.")
    h.lift_requested_by = by
    h.lift_reason = reason or ""
    req = approvals.request_approval("legal_hold", h.pk, by, required=2, country=h.country,
                                     summary=f"Lift the legal hold on {h.subject_type} {h.subject_id}")
    h.approval_request = req
    state.transition(h, "legal_hold", "lift_pending", actor=by, reason=reason,
                     extra_fields=["lift_requested_by", "lift_reason", "approval_request"])
    return h


def decide_lift(h: LegalHold, approver, *, decision, mfa_at, note=""):
    if h.status != "lift_pending" or h.approval_request is None:
        raise StateConflict("This hold has no open request to lift it.")
    return approvals.decide(h.approval_request, approver, decision=decision, mfa_at=mfa_at, note=note,
                            allowed=lambda a: has_role(a, *HOLD_ROLES))


@transaction.atomic
def apply_lift(h: LegalHold, approved: bool):
    if h.status != "lift_pending":
        return h
    if approved:
        h.lifted_at = _now()
        state.transition(h, "legal_hold", "lifted", event="legal_hold.lifted", extra_fields=["lifted_at"],
                         payload={"subject_type": h.subject_type, "subject_id": h.subject_id})
    else:
        state.transition(h, "legal_hold", "active", reason="Lift refused")
    return h


# ---------------------------------------------------------------- bulk exports (US-DPR-005)

@transaction.atomic
def request_bulk_export(by, *, purpose, country, roles=("CL",), fields=("full_name", "email")) -> BulkExport:
    _require(by, *DPR_ROLES, msg="Only an administrator asks for a bulk export.")
    bad = set(fields) - EXPORT_FIELDS
    if bad or not fields:
        raise Invalid(f"These fields cannot be exported: {', '.join(sorted(bad)) or 'none chosen'}.",
                      code="validation-error")
    if not purpose:
        raise Invalid("Give the purpose of the export.", code="validation-error")
    be = BulkExport.objects.create(country=country, requested_by=by, purpose=purpose,
                                   scope={"roles": list(roles), "fields": list(fields)})
    req = approvals.request_approval("bulk_export", be.pk, by, required=2, country=country,
                                     summary=f"Bulk export of {', '.join(fields)} for {', '.join(roles)}")
    be.approval_request = req
    be.save(update_fields=["approval_request"])
    record(actor=by, action="bulk_export.requested", entity="bulk_export", entity_id=be.pk,
           data={"scope": be.scope, "purpose": purpose}, country=country)
    _alert(country, ("AD",), "bulk_export_requested", "A bulk export of personal data waits for your approval.",
           obj=be)
    return be


def decide_bulk_export(be: BulkExport, approver, *, decision, mfa_at, note=""):
    if be.status != "pending_approval" or be.approval_request is None:
        raise StateConflict("This export is not waiting for approval.")
    return approvals.decide(be.approval_request, approver, decision=decision, mfa_at=mfa_at, note=note,
                            allowed=lambda a: has_role(a, *DPR_ROLES) and a.pk != be.requested_by_id)


@transaction.atomic
def produce_bulk_export(be: BulkExport) -> BulkExport:
    if be.status != "pending_approval" or be.approval_request is None or be.approval_request.status != "approved":
        return be
    from accounts.models import Person

    fields = be.scope.get("fields", [])
    qs = Person.objects.filter(role_grants__role__in=be.scope.get("roles", []), role_grants__revoked_at__isnull=True,
                               home_country=be.country).exclude(status="anonymised").distinct().order_by("created_at")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", *fields])
    n = 0
    for p in qs:
        w.writerow([p.pk, *[getattr(p, f) for f in fields]])
        n += 1
    data = buf.getvalue().encode()
    from evidence.services import link, store

    ev = store(data=data, country=be.country, uploaded_by=be.requested_by, content_type="text/csv",
               original_name=f"bulk-export-{be.pk}.csv", source="generated", description="Bulk export")
    link(ev, "bulk_export", be.pk, role="bulk_export_file", by=be.requested_by)
    be.file_evidence = ev
    be.file_sha256 = hashlib.sha256(data).hexdigest()
    be.row_count = n
    be.produced_at = _now()
    be.link_expires_at = be.produced_at + timedelta(hours=EXPORT_LINK_HOURS)
    state.transition(be, "bulk_export", "produced", event="bulk_export.produced",
                     extra_fields=["file_evidence", "file_sha256", "row_count", "produced_at", "link_expires_at"],
                     payload={"rows": n, "sha256": be.file_sha256})
    _notify(be.requested_by, "bulk_export_ready", obj=be,
            body=f"Your bulk export is ready for {EXPORT_LINK_HOURS} hours.")
    return be


@transaction.atomic
def download_bulk_export(be: BulkExport, by) -> bytes:
    if by.pk != be.requested_by_id:
        raise Forbidden("Only the person who asked for the export can download it.")
    if be.status != "produced":
        raise StateConflict("This export is not available.")
    if be.link_expires_at and be.link_expires_at < _now():
        state.transition(be, "bulk_export", "expired")
        raise DomainError("The download link has expired.", code="export-expired", status=410)
    from core.adapters import get_adapter

    data = get_adapter("evidence_store").get(be.file_evidence.storage_key)
    be.download_count += 1
    be.save(update_fields=["download_count"])
    record(actor=by, action="bulk_export.downloaded", entity="bulk_export", entity_id=be.pk,
           data={"rows": be.row_count}, country=be.country)
    return data


def expire_bulk_exports() -> int:
    n = 0
    for be in BulkExport.objects.filter(status="produced", link_expires_at__lt=_now()):
        state.transition(be, "bulk_export", "expired")
        n += 1
    return n


# ---------------------------------------------------------------- data catalogue and locations (NFR-PRIV-01, 02)

def sync_catalogue() -> int:
    """Add a row for every model field of every Tenmina module that is not
    catalogued yet, with no purpose (NFR-PRIV-02: CI lists the gaps)."""
    from django.apps import apps
    from django.conf import settings

    n = 0
    for name in settings.TENMINA_MODULES:
        try:
            cfg = apps.get_app_config(name)
        except LookupError:
            continue
        for model in cfg.get_models():
            for f in model._meta.concrete_fields:
                _, created = DataCatalogueEntry.objects.get_or_create(table_name=model._meta.db_table,
                                                                      field_name=f.column)
                n += int(created)
    return n


def uncatalogued_fields(prefixes=("acc_", "dpr_")) -> list[str]:
    from django.apps import apps

    have = set(DataCatalogueEntry.objects.exclude(purpose="").values_list("table_name", "field_name"))
    out = []
    for model in apps.get_models():
        t = model._meta.db_table
        if not t.startswith(tuple(prefixes)):
            continue
        for f in model._meta.concrete_fields:
            if (t, f.column) not in have:
                out.append(f"{t}.{f.column}")
    return out


@transaction.atomic
def save_location(by, **fields) -> DataLocation:
    _require(by, *DPR_ROLES, msg="Only an administrator records data locations.")
    loc = DataLocation.objects.create(**fields)
    record(actor=by, action="data_location.saved", entity="data_location", entity_id=loc.pk,
           data={"service": loc.service, "region": loc.region})
    return loc
