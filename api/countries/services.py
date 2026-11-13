"""CTY services: the country registry, versioned country configuration with
copying, activation by two administrators, cells, data location and the
routing directory (FR-CTY-001 to 004, ADR-16, 02 section 6.9)."""
import copy
import hashlib
import hmac

from django.conf import settings as dj_settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from audit.services import record, security_event
from core import approvals, state
from core.errors import Forbidden, Invalid, NotFound, RuleBlocked, StateConflict
from core.events import publish
from core.permissions import has_role

from .models import Cell, Country, CountryConfig, DirectoryEntry

ADMIN = "AD"
REQUIRED_TEXTS = ("scope_statement", "terms")


def _admin(by):
    if not has_role(by, ADMIN):
        raise Forbidden("Only an administrator can do this.")


def sha256_json(obj) -> str:
    from administration.services import sha256_json as h

    return h(obj)


# --- Country registry ---------------------------------------------------------

@transaction.atomic
def create_country(*, code, name, currency, by, timezone_name="UTC", cell=None) -> Country:
    """A new country starts as a draft with every line off (06 2.7)."""
    _admin(by)
    code = (code or "").upper()
    if len(code) != 2 or not code.isalpha():
        raise Invalid("Use the two-letter ISO 3166-1 code.", code="validation-error")
    if len(currency or "") != 3:
        raise Invalid("Use the three-letter ISO 4217 currency code.", code="validation-error")
    if Country.objects.filter(code=code).exists():
        raise StateConflict("This country already exists.")
    c = Country.objects.create(code=code, name=name, currency=currency.upper(), timezone=timezone_name, cell=cell,
                               status="draft")
    record(actor=by, action="country.created", entity="country", entity_id=c.pk, country=c,
           data={"code": code, "currency": c.currency, "cell": getattr(cell, "name", None)})
    publish("country.created", c.pk, {"country": code})
    return c


LOCATION_FIELDS = ("cell", "data_location", "data_location_ruling", "evidence_prefix", "backup_location",
                   "kms_key_alias")
EDITABLE = ("name", "timezone", *LOCATION_FIELDS)


@transaction.atomic
def update_country(c: Country, *, by, **fields) -> Country:
    """Changes to the data location register are logged with old and new
    values (US-CTY-002b criterion 1)."""
    _admin(by)
    if "currency" in fields and fields["currency"] != c.currency:
        if c.status == "active":
            raise StateConflict("An active country's currency cannot change.")
        fields["currency"] = fields["currency"].upper()
    changes = {}
    for k, v in fields.items():
        if k not in (*EDITABLE, "currency") or v is None:
            continue
        old = getattr(c, k)
        o, n = getattr(old, "pk", old), getattr(v, "pk", v)
        if o != n:
            changes[k] = {"old": str(o) if o is not None else None, "new": str(n)}
            setattr(c, k, v)
    if changes:
        c.save()
        loc = any(k in LOCATION_FIELDS for k in changes)
        record(actor=by, action="country.data_location_changed" if loc else "country.updated", entity="country",
               entity_id=c.pk, country=c, data={"changes": changes})
    return c


@transaction.atomic
def start_manual_phase(c: Country, *, by) -> Country:
    _admin(by)
    c.manual_phase_started_at = timezone.now()
    return state.transition(c, "country", "manual_phase", actor=by, extra_fields=["manual_phase_started_at"])


@transaction.atomic
def start_validation(c: Country, *, by) -> Country:
    """The 90-day validation after the manual phase (C-13)."""
    _admin(by)
    c.validation_started_at = timezone.now()
    return state.transition(c, "country", "validating", actor=by, extra_fields=["validation_started_at"])


@transaction.atomic
def record_gate_decision(c: Country, *, by, passed: bool, note: str, evidence=None) -> Country:
    """The founder's recorded gate decision (TC-CTY-004-02), with the gate
    record as evidence."""
    _admin(by)
    if c.status not in ("manual_phase", "validating"):
        raise StateConflict("A gate decision is taken during the manual phase or validation.")
    if not note:
        raise Invalid("Say what the decision rests on.")
    c.gate_passed, c.gate_note, c.gate_decided_at, c.gate_decided_by = passed, note, timezone.now(), by
    c.gate_evidence = evidence
    c.save()
    record(actor=by, action="country.gate_decided", entity="country", entity_id=c.pk, country=c,
           data={"passed": passed, "evidence_id": str(evidence.pk) if evidence else None})
    return c


def activation_blockers(c: Country) -> list[dict]:
    out = []
    if c.status not in ("manual_phase", "validating", "paused"):
        out.append({"rule": "C-13", "message": f"The country is {c.status}; it must have passed its manual phase."})
    if not c.gate_passed or not c.gate_decided_at:
        out.append({"rule": "C-13", "message": "No recorded gate decision that the country passed."})
    cfg = c.configs.filter(status="published").order_by("-version").first()
    if not cfg:
        out.append({"rule": "FR-CTY-001", "message": "No published country configuration."})
    if not c.data_location or not c.cell_id:
        out.append({"rule": "FR-CTY-002", "message": "The data location and cell are not set."})
    return out


@transaction.atomic
def request_activation(c: Country, *, by):
    _admin(by)
    blockers = activation_blockers(c)
    if blockers:
        raise RuleBlocked("The country cannot be activated yet.", code="country-not-ready",
                          blocking_reasons=blockers)
    req = approvals.request_approval("country_activation", c.pk, by, required=1, country=c,
                                     summary=f"Activate {c.name} ({c.code})")
    c.activation_request = req
    c.save(update_fields=["activation_request"])
    record(actor=by, action="country.activation_requested", entity="country", entity_id=c.pk, country=c,
           data={"approval_request_id": str(req.pk)})
    return req


def decide_activation(c: Country, approver, *, decision="approve", mfa_at=None, note=""):
    if not c.activation_request_id or c.activation_request.status != "open":
        raise StateConflict("No activation is waiting for approval.")
    if decision == "approve":
        blockers = activation_blockers(c)
        if blockers:
            raise RuleBlocked("The country cannot be activated yet.", code="country-not-ready",
                              blocking_reasons=blockers)
    return approvals.decide(c.activation_request, approver, decision=decision, mfa_at=mfa_at, note=note,
                            allowed=lambda p: has_role(p, ADMIN))


def _activate(c: Country, req, approvers):
    from administration.models import FeatureFlag

    c = Country.objects.select_for_update().get(pk=c.pk)
    if c.status == "active":
        return c
    if activation_blockers(c) or any(not has_role(a, ADMIN) for a in approvers):
        security_event("country.invalid_activation", entity="country", entity_id=c.pk, country=c)
        return c
    first_time = c.activated_at is None
    c.activated_at = timezone.now()
    c.current_config = c.configs.filter(status="published").order_by("-version").first()
    c.activation_request = req
    people = [str(req.prepared_by_id)] + [str(a.pk) for a in approvers]
    state.transition(c, "country", "active", actor=approvers[-1] if approvers else None, event="country.activated",
                     payload={"country": c.code, "people": people},
                     extra_fields=["activated_at", "current_config", "activation_request"])
    flag, _ = FeatureFlag.objects.get_or_create(name=f"country.{c.code.lower()}", country=None)
    flag.enabled, flag.reason = True, f"Activated by two administrators ({req.pk})"
    flag.save()
    # 06 2.7: a new country goes live with every line off; each is switched on by two people.
    for name in (FeatureFlag.objects.filter(name__startswith="lines.", country__isnull=True).values_list(
            "name", flat=True) if first_time else []):
        FeatureFlag.objects.get_or_create(name=name, country=c, defaults={
            "enabled": False, "reason": "Off until this country's partners and licences are in place"})
    security_event("country.activated", actor=approvers[-1] if approvers else None, entity="country",
                   entity_id=c.pk, country=c, data={"people": people}, summary=f"{c.name} activated")
    return c


@transaction.atomic
def pause(c: Country, *, by, reason) -> Country:
    """Stopping is always safe: one administrator."""
    _admin(by)
    return state.transition(c, "country", "paused", actor=by, reason=reason)


def resume(c: Country, *, by):
    """Resuming reopens a country: it needs the same two-person activation."""
    return request_activation(c, by=by)


# --- Country configuration (FR-CTY-001, FR-CTY-004) ----------------------------------

def _next_version(country) -> int:
    return (CountryConfig.objects.filter(country=country).aggregate(m=Max("version"))["m"] or 0) + 1


@transaction.atomic
def create_config(country: Country, *, by, data=None, copy_from: CountryConfig | None = None) -> CountryConfig:
    _admin(by)
    if copy_from is not None:
        return copy_config(copy_from, country, by=by)
    if data is None:
        current = country.configs.filter(status="published").order_by("-version").first()
        data = copy.deepcopy(current.data) if current else {}
    if not isinstance(data, dict):
        raise Invalid("Configuration data must be an object.")
    cfg = CountryConfig.objects.create(country=country, version=_next_version(country), status="draft", data=data,
                                       content_sha256=sha256_json(data), prepared_by=by)
    record(actor=by, action="country_config.created", entity="country_config", entity_id=cfg.pk, country=country,
           data={"version": cfg.version, "sha256": cfg.content_sha256})
    return cfg


COPY_RESET = ("currency", "data_location", "phone_prefix", "national_id", "land_registry", "holiday_calendar")


@transaction.atomic
def copy_config(source: CountryConfig, target: Country, *, by) -> CountryConfig:
    """FR-CTY-004: copy another country's published configuration as a draft.
    Every referenced configuration item and locked text becomes a draft for
    the new country, so it never points at the source country's rows.
    Partners and bank details are not copied (TC-CTY-004-03). Country-specific
    values are cleared and must be set before publication."""
    from administration.models import ConfigVersion, LockedTextVersion
    from administration.services import copy_version_to_country, propose_locked_text

    _admin(by)
    if source.status not in ("published", "superseded"):
        raise StateConflict("Copy from a published configuration.")
    if source.country_id == target.pk:
        raise Invalid("Copy from another country.")
    data = copy.deepcopy(source.data)
    for k in COPY_RESET:
        if k in data:
            data[k] = None
    refs = data.get("refs") or {}
    new_refs = {"config_versions": {}, "locked_texts": {}, "partners": {}}
    copies = {}  # one copy per source version, even when two keys name it ("case_template", "case_template:land")
    for kind, pk in (refs.get("config_versions") or {}).items():
        cv = ConfigVersion.objects.filter(pk=pk).first()
        if cv is None:
            continue
        if cv.country_id is None:
            new_refs["config_versions"][kind] = str(cv.pk)  # shareable rows stay shared
        else:
            if cv.pk not in copies:
                copies[cv.pk] = str(copy_version_to_country(cv, target, by=by).pk)
            new_refs["config_versions"][kind] = copies[cv.pk]
    for kind, pk in (refs.get("locked_texts") or {}).items():
        lt = LockedTextVersion.objects.filter(pk=pk).first()
        if lt is not None:
            new_refs["locked_texts"][kind] = str(propose_locked_text(kind=lt.kind, country=target, text=lt.text,
                                                                     title=lt.title, by=by, copied_from=lt).pk)
    data["refs"] = new_refs
    data["copied_from"] = {"country": source.country.code, "config_id": str(source.pk), "version": source.version}
    data["to_review"] = sorted(set(COPY_RESET) | {"refs.partners", "refs.locked_texts"})
    cfg = CountryConfig.objects.create(country=target, version=_next_version(target), status="draft", data=data,
                                       content_sha256=sha256_json(data), prepared_by=by, copied_from=source)
    record(actor=by, action="country_config.copied", entity="country_config", entity_id=cfg.pk, country=target,
           data={"from_country": source.country.code, "from_config": str(source.pk),
                 "config_versions": len(new_refs["config_versions"]), "locked_texts": len(new_refs["locked_texts"])})
    publish("country_config.copied", cfg.pk, {"country": target.code, "from_country": source.country.code})
    return cfg


@transaction.atomic
def update_config(cfg: CountryConfig, *, by, data) -> CountryConfig:
    _admin(by)
    if cfg.status != "draft":
        raise StateConflict("Only a draft configuration can be edited. Create a new version.",
                            code="config-published")
    if not isinstance(data, dict):
        raise Invalid("Configuration data must be an object.")
    old = cfg.content_sha256
    cfg.data, cfg.content_sha256 = data, sha256_json(data)
    cfg.save()
    record(actor=by, action="country_config.edited", entity="country_config", entity_id=cfg.pk, country=cfg.country,
           data={"old_sha256": old, "new_sha256": cfg.content_sha256})
    return cfg


def publication_blockers(cfg: CountryConfig) -> list[dict]:
    """US-CTY-001a criterion 3 and US-CTY-004 criterion 1: currency, data
    location, scope statement and legal texts must be set, and every
    reference must point to a published row of the same country (TC-CTY-001-02)."""
    from administration.models import ConfigVersion, LockedTextVersion, Partner

    d, c, out = cfg.data or {}, cfg.country, []
    if not d.get("currency"):
        out.append({"rule": "FR-CTY-001", "message": "The currency is not set."})
    elif d["currency"] != c.currency:
        out.append({"rule": "FR-CTY-001", "message": f"The currency {d['currency']} is not {c.code}'s {c.currency}."})
    if not d.get("data_location"):
        out.append({"rule": "FR-CTY-002", "message": "The data location is not set."})
    refs = d.get("refs") or {}
    texts = refs.get("locked_texts") or {}
    for kind in REQUIRED_TEXTS:
        if not texts.get(kind):
            out.append({"rule": "RUL-04", "message": f"No {kind.replace('_', ' ')} is set."})
    for kind, pk in texts.items():
        lt = LockedTextVersion.objects.filter(pk=pk).first()
        if lt is None or lt.country_id != c.pk:
            out.append({"rule": "FR-CTY-001", "message": f"The {kind.replace('_', ' ')} belongs to another country."})
        elif lt.status != "published":
            out.append({"rule": "FR-ADM-004", "message": f"The {kind.replace('_', ' ')} is not approved yet."})
    for kind, pk in (refs.get("config_versions") or {}).items():
        cv = ConfigVersion.objects.filter(pk=pk).first()
        if cv is None or (cv.country_id not in (None, c.pk)):
            out.append({"rule": "FR-CTY-001", "message": f"The {kind.replace('_', ' ')} belongs to another country."})
        elif cv.state != "published":
            out.append({"rule": "FR-ADM-001", "message": f"The {kind.replace('_', ' ')} is not published yet."})
        else:
            out.extend(_template_reasons(cv.kind, cv.content, c, label=kind))
    if d.get("errand_catalogue") is not None:
        out.extend(_template_reasons("errand_catalogue", {"errands": d.get("errand_catalogue") or []}, c,
                                     label="errand catalogue"))
    for port, pk in (refs.get("partners") or {}).items():
        p = Partner.objects.filter(pk=pk).first()
        if p is None or p.country_id != c.pk:
            out.append({"rule": "FR-CTY-001", "message": f"The {port} partner belongs to another country."})
        elif p.status != "active":
            out.append({"rule": "FR-ADM-003", "message": f"The {port} partner is deactivated."})
    return out


def _template_reasons(kind, content, country, *, label) -> list[dict]:
    """FR-ADM-001, FR-CASE-002, FR-RPT-001, FR-TSK-001: a template the configuration names must pass its own
    module's rules (cases.templates, reports.templates, errands.catalogue)."""
    from administration.services import validate_for_publication

    try:
        validate_for_publication(kind, content, country)
    except Invalid as exc:
        return [{"rule": "FR-ADM-001", "message": f"The {label.replace('_', ' ')} is not valid: {exc.detail}"}]
    return []


@transaction.atomic
def submit_config(cfg: CountryConfig, *, by):
    """The preparer asks for publication; a second administrator approves."""
    _admin(by)
    if cfg.status != "draft":
        raise StateConflict("Only a draft can be sent for publication.")
    blockers = publication_blockers(cfg)
    if blockers:
        raise RuleBlocked("This configuration cannot be published yet.", code="config-incomplete",
                          blocking_reasons=blockers)
    req = approvals.request_approval("country_config_publish", cfg.pk, by, required=1, country=cfg.country,
                                     summary=f"{cfg.country.code} configuration version {cfg.version}")
    cfg.approval_request = req
    state.transition(cfg, "country_config", "pending_approval", actor=by, extra_fields=["approval_request"])
    return req


def decide_config(cfg: CountryConfig, approver, *, decision="approve", mfa_at=None, note=""):
    if cfg.status != "pending_approval" or not cfg.approval_request_id:
        raise StateConflict("This configuration is not waiting for approval.")
    if decision == "approve":
        blockers = publication_blockers(cfg)
        if blockers:
            raise RuleBlocked("This configuration cannot be published yet.", code="config-incomplete",
                              blocking_reasons=blockers)
    return approvals.decide(cfg.approval_request, approver, decision=decision, mfa_at=mfa_at, note=note,
                            allowed=lambda p: has_role(p, ADMIN))


def _publish(cfg: CountryConfig, approvers):
    cfg = CountryConfig.objects.select_for_update().get(pk=cfg.pk)
    if cfg.status != "pending_approval":
        return cfg
    if publication_blockers(cfg) or any(not has_role(a, ADMIN) for a in approvers):
        state.transition(cfg, "country_config", "draft", reason="Approval did not meet the publication rules")
        security_event("country_config.invalid_approval", entity="country_config", entity_id=cfg.pk,
                       country=cfg.country)
        return cfg
    for old in CountryConfig.objects.filter(country=cfg.country, status="published"):
        state.transition(old, "country_config", "superseded", payload={"replaced_by": str(cfg.pk)})
    cfg.published_at = timezone.now()
    people = [str(cfg.approval_request.prepared_by_id)] + [str(a.pk) for a in approvers]
    state.transition(cfg, "country_config", "published", actor=approvers[-1] if approvers else None,
                     event="country_config.published",
                     payload={"country": cfg.country.code, "version": cfg.version, "config_id": str(cfg.pk),
                              "people": people},
                     extra_fields=["published_at"])
    c = cfg.country
    c.current_config = cfg
    c.save(update_fields=["current_config"])
    security_event("country_config.published", actor=approvers[-1] if approvers else None, entity="country_config",
                   entity_id=cfg.pk, country=c, data={"version": cfg.version, "people": people},
                   summary=f"{c.code} configuration version {cfg.version} published")
    return cfg


@transaction.atomic
def retire_config(cfg: CountryConfig, *, by) -> CountryConfig:
    _admin(by)
    return state.transition(cfg, "country_config", "retired", actor=by)


def seed_publish(country: Country, data: dict, *, by=None) -> CountryConfig:
    """Seeds only: publish a configuration directly, superseding the current one."""
    cfg = CountryConfig.objects.create(country=country, version=_next_version(country), status="published",
                                       data=data, content_sha256=sha256_json(data), prepared_by=by,
                                       published_at=timezone.now())
    for old in CountryConfig.objects.filter(country=country, status="published").exclude(pk=cfg.pk):
        state.transition(old, "country_config", "superseded", actor=by, payload={"replaced_by": str(cfg.pk)})
    country.current_config = cfg
    country.save(update_fields=["current_config"])
    return cfg


# --- Cells and the routing directory (ADR-16) ----------------------------------

@transaction.atomic
def create_cell(*, by, name, aws_region, **fields) -> Cell:
    _admin(by)
    if Cell.objects.filter(name=name).exists():
        raise StateConflict("A cell with this name exists.")
    cell = Cell.objects.create(name=name, aws_region=aws_region,
                               **{k: v for k, v in fields.items() if k in ("aws_account", "api_host", "portal_host",
                                                                           "data_location_notes", "status")})
    record(actor=by, action="cell.created", entity="cell", entity_id=cell.pk,
           data={"name": name, "region": aws_region})
    security_event("cell.deployed", actor=by, entity="cell", entity_id=cell.pk, data={"region": aws_region},
                   summary=f"New cell {name} in {aws_region}")
    return cell


@transaction.atomic
def update_cell(cell: Cell, *, by, **fields) -> Cell:
    _admin(by)
    changes = {}
    for k in ("aws_region", "aws_account", "api_host", "portal_host", "data_location_notes", "status"):
        if k in fields and fields[k] is not None and fields[k] != getattr(cell, k):
            changes[k] = {"old": getattr(cell, k), "new": fields[k]}
            setattr(cell, k, fields[k])
    if changes:
        cell.save()
        record(actor=by, action="cell.data_location_changed", entity="cell", entity_id=cell.pk,
               data={"changes": changes})
    return cell


def blind_index(value: str) -> str:
    v = (value or "").strip().lower()
    return hmac.new(dj_settings.SECRET_KEY.encode(), f"dir:{v}".encode(), hashlib.sha256).hexdigest()


def register_signin(identifier: str, country: Country | None) -> DirectoryEntry | None:
    from .selectors import default_cell

    cell = (country.cell if country is not None and country.cell_id else None) or default_cell()
    if cell is None or not identifier:
        return None
    entry, _ = DirectoryEntry.objects.update_or_create(kind="signin", key=blind_index(identifier),
                                                       defaults={"cell": cell, "country": country})
    return entry


def register_reference_prefix(prefix: str, country: Country) -> DirectoryEntry | None:
    from .selectors import default_cell

    cell = country.cell or default_cell()
    if cell is None:
        return None
    entry, _ = DirectoryEntry.objects.update_or_create(kind="reference_prefix", key=prefix.upper(),
                                                       defaults={"cell": cell, "country": country})
    return entry


def route(*, signin: str | None = None, reference: str | None = None) -> Cell | None:
    """The cell for a sign-in or a reference such as TMR-NG-2027-00042. Falls
    back to the default cell so the answer never reveals whether an account exists."""
    from .selectors import default_cell

    if signin:
        e = DirectoryEntry.objects.filter(kind="signin", key=blind_index(signin)).select_related("cell").first()
        if e:
            return e.cell
    if reference:
        parts = reference.upper().split("-")
        for n in range(len(parts), 0, -1):
            e = DirectoryEntry.objects.filter(kind="reference_prefix", key="-".join(parts[:n]) + "-").first() \
                or DirectoryEntry.objects.filter(kind="reference_prefix", key="-".join(parts[:n])).first()
            if e:
                return e.cell
    return default_cell()


# --- Scoping (US-CTY-001b) -------------------------------------------------------

def check_access(user, country, *roles, entity="", entity_id=""):
    """Refuse a staff member's access to another country's work, as not-found,
    and log it (US-CTY-001b criterion 2). Other modules call this."""
    from .selectors import can_see_country

    if can_see_country(user, country, *roles):
        return
    security_event("access.cross_country_refused", actor=user, entity=entity or "country",
                   entity_id=entity_id or getattr(country, "pk", ""), country=country,
                   data={"roles": list(roles)}, defer=True)
    raise NotFound()
