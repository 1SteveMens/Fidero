# Tenmina API: how every module is built

Read this before writing code in `api/`. The architecture is document 02 (`docs/specs/02-architecture-and-technical-design.md`): a Django 5 + DRF modular monolith (ADR-01) on PostgreSQL 16 + PostGIS (ADR-02). Requirements are in document 01, stories in document 04, tests in document 05.

## Setup

```bash
source /home/user/.venv-tenmina/bin/activate   # Python 3.13 with requirements.txt installed
cd api
TEST_DB_NAME=test_<module> python -m pytest <module> --create-db   # first run; later runs can drop --create-db
python manage.py makemigrations <module>                            # only your own module
```

PostgreSQL runs locally (`tenmina`/`tenmina`). Use your own `TEST_DB_NAME` so parallel builds do not collide. Do not run `migrate` or `seed_dev` against the development database while other builds are running.

## Layout of a module

| File | Holds |
|---|---|
| `models.py` | Tables. `db_table` always carries the module prefix from 02 section 4.2 (`case_case`, `esc_payee`). Inherit `core.models.CountryScopedModel` for anything holding client, case, money, evidence or configuration data, else `core.models.BaseModel`. Money is two fields, `<name>_amount` (`core.money.amount_field()`) and `<name>_currency` (`core.money.currency_field()`). Register state machines here with `core.state.register(entity, table, transitions)`. |
| `services.py` | Every write and every rule. Other modules call only this file. Wrap in `transaction.atomic()`. Change status only through `core.state.transition(obj, entity, to, actor=..., event=..., payload=...)`; it audits and publishes. Other writes that matter call `audit.services.record(...)` and `core.events.publish(...)`. |
| `selectors.py` | Read-only queries other modules may use. |
| `handlers.py` | Event subscribers: `@core.events.subscribe("report.released") def on_released(ev): ...`. `ev.payload` is a dict. The AppConfig already imports `handlers.py`. Handlers must be idempotent. |
| `serializers.py`, `views.py`, `urls.py` | Thin API. `urls.py` defines `urlpatterns`; it is mounted under `/v1/`. Use `rest_framework.routers.DefaultRouter(trailing_slash=False)` or `path(...)`. Resource names are plural nouns; state actions are sub-resources, `POST /v1/cases/{id}/assign`. Follow the endpoint catalogue in 02 section 7.4 where it names a path. Money in JSON is `{"amount": "250.00", "currency": "USD"}` via `core.money.MoneyField(prefix=...)`. Every view needs a schema: use serializers, or `@extend_schema` on function views, so `python manage.py spectacular --validate` stays clean (the front ends are generated from it). |
| `adapters.py` | Ports and adapters (ADR-10). Each port has a fake or manual adapter so the whole workflow runs without the integration. Get one with `core.adapters.get_adapter("port", default="<module>.adapters.Fake...")`. |
| `seed.py` | `run(ctx)`: development and demo data. `ctx["gh"]` is Ghana, `ctx["people"][key]` the seeded cast in `accounts/seed.py` (client, client2, cm, reviewer, reviewer2, admin, admin2, lawyer, surveyor, runner, inspector, qs, carer, agent, seller, contractor, family, institution, partner, insurer, tenant, developer, authority). Put shared objects you create into ctx for later modules. Seeds must be idempotent (`get_or_create`) and run in `settings.TENMINA_MODULES` order. Seed realistic demo journeys in several states so every screen has data. |
| `dbsql.py` | `SQL = [...]` idempotent statements installed after every migrate: triggers and constraints that enforce rules a second time in the database (ADR-02). `core.dbsql.append_only("table")` makes a table append-only. |
| `tests/` | pytest. Fixtures in `api/conftest.py`: `seeded` (all seeds), `gh`, `people`, `api(person)` (an authenticated APIClient), `mfa(client, person)` (passes a step-up). Name the requirement or rule in each test's docstring (`"""FR-ESC-016, RUL-28: ..."""`). Test every rule's refusal, not only the happy path, and at least one full API journey per story group. |

## Shared kernel you must use

- `core.errors`: raise `StateConflict`, `RuleBlocked(blocking_reasons=[{"rule": "RUL-06", "message": ...}])`, `SameApprover`, `PayeeNotVerified`, `Invalid`, `Forbidden`, `NotFound`, `MfaRequired`, `FeatureOff`, or `DomainError(code=..., status=...)` with a problem code from 02 section 7.2. Responses become `application/problem+json`.
- `core.approvals`: `request_approval(subject_type, subject_id, prepared_by, required=2)`, `decide(req, approver, decision=, mfa_at=, allowed=callable)`. It refuses the preparer, a second approval by the same person and a stale MFA. When closed it publishes `approval.approved` or `approval.rejected` with `subject_type` and `subject_id`; your handler moves your object on. `subject_type` must be in `ApprovalRequest.SUBJECT_TYPES`; if you need a new one, add it there (one-line change, allowed).
- `core.views.require_mfa(request)` returns the fresh MFA time for approvals; `core.views.body(request, "field", ...)` reads required fields.
- `core.permissions.roles("CM", "RV")` permission class, `has_role(user, ...)`, `is_staff(user)`. Role codes are listed there. Clients see only their own objects; staff are scoped to their country role grants; professionals see only what they are assigned.
- `core.idempotency.idempotent` decorator on POST actions that create, pay, approve, send or submit.
- `administration.flags.require("lines.fee", country)` at the entry of every service behind a flag (document 06 section 2.6), `flags.instructions_paused()` before any release instruction, `flags.read_only_guard()` on writes.
- `countries.selectors.config(country, "key.path", default)` for anything that differs by country. Never hard-code Ghana.
- `evidence.services.store(data=..., country=..., uploaded_by=..., content_type=..., source=...)` and `evidence.services.link(evidence, subject_type, subject_id, role=...)`. Evidence is tamper-evident; never store files any other way.
- `notifications.services.notify(person, "template_code", body=..., subject=..., link=..., channels=("in_app", "email"), needs_action=True|False, subject_obj=obj)`. `needs_action=True` is what the apps show in orange: only things that need the client.

## Core design rules (from CLAUDE.md, never break them)

- Tenmina never holds client money. A licensed bank or escrow agent does. The platform only mirrors what the bank reports (ADR-18) and sends instructions.
- Money is released only to a verified institution, supplier, vendor or professional (a verified payee, ADR-17). Never as cash to a relative.
- Two Tenmina staff approve every release. The client approves first. Silence is never approval: no timer ever approves anything.
- Every piece of evidence is tamper-evident.
- Each product line or country opens only behind its flag.
- Country is configuration.
- Insurance is sold only as a licensed insurer's product. Tenmina does not transfer money across borders.
- Never use the word "guard" in names.

## Boundaries while building in parallel

- Write only inside your own module directories. Do not edit `tenmina/settings.py`, `tenmina/urls.py`, `conftest.py` or other modules. The only shared edits allowed are listed above (`ApprovalRequest.SUBJECT_TYPES`). If you need something from another module that does not exist yet, refer to it by UUID field and event topic, and list it under "Needs from other modules" in your final report.
- Cross-module foreign keys are allowed (`on_delete=PROTECT`) to modules that already exist in the tree.
- User-facing text: plain English, short sentences. Every price or threshold is a working assumption: seed values carry `[TO VERIFY]` where unknown.
