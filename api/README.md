# Tenmina API

The one API behind the portal, the back office and the two apps. Django 5 + Django REST Framework on PostgreSQL 16 with PostGIS (document 02, ADR-01 and ADR-02). How modules are built: `CONVENTIONS.md`.

## Run it locally

```bash
python3 -m venv ~/.venv-tenmina && source ~/.venv-tenmina/bin/activate
pip install -r requirements.txt
# PostgreSQL 16 with PostGIS, a role tenmina/tenmina and a database tenmina with CREATE EXTENSION postgis
python manage.py migrate
python manage.py seed_dev          # demo people, Ghana configuration and sample journeys
python manage.py runserver 8000    # API on http://localhost:8000/v1, docs at /v1/docs
```

Every seeded person signs in with the password `tenmina-dev-123`. Staff (case manager, reviewers, administrators) have MFA on with the shared development secret in `accounts/seed.py`; any authenticator app given that secret produces their codes.

## Tests

```bash
TEST_DB_NAME=test_tenmina python -m pytest -q
```

## Background jobs

Periodic work runs on Celery beat (ADR-08, document 02 section 7.12). The schedule is in `tenmina/celery_schedule.py` and is loaded into `CELERY_BEAT_SCHEDULE` by `tenmina/settings.py`; times are UTC (GMT) and every one is a working assumption. Each job is a Celery task in its module's `tasks.py`. Jobs that react to an event (for example `cases.create_from_order`) are not on the schedule.

```bash
python manage.py run_jobs --list                 # every scheduled job and when it runs
python manage.py run_jobs fees.schedule_due      # run one job now, in this process
celery -A tenmina worker -l info                 # production: a worker ...
celery -A tenmina beat -l info                   # ... and exactly one beat process
```

In development and tests `CELERY_TASK_ALWAYS_EAGER` runs tasks inline and events dispatch at once, so `run_jobs` is the way to move time-based work along by hand. No job approves or releases anything: silence is never approval.

## Integrations

Every integration is a port with a fake or manual adapter (ADR-10), named in `settings.TENMINA["ADAPTERS"]`. The whole workflow runs with the fakes. A real integration replaces one adapter path through an environment variable; nothing else changes.

## Front ends

- Portal (clients, professionals, sellers, institutions): `apps/portal`, `pnpm --filter @tenmina/portal dev` on port 3000.
- Back office (staff): `apps/backoffice`, `pnpm --filter @tenmina/backoffice dev` on port 3001.
- Both proxy `/v1` to the API. The typed client is regenerated with `pnpm --filter @tenmina/api-client generate` after any API change.
