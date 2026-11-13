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

## Integrations

Every integration is a port with a fake or manual adapter (ADR-10), named in `settings.TENMINA["ADAPTERS"]`. The whole workflow runs with the fakes. A real integration replaces one adapter path through an environment variable; nothing else changes.

## Front ends

- Portal (clients, professionals, sellers, institutions): `apps/portal`, `pnpm --filter @tenmina/portal dev` on port 3000.
- Back office (staff): `apps/backoffice`, `pnpm --filter @tenmina/backoffice dev` on port 3001.
- Both proxy `/v1` to the API. The typed client is regenerated with `pnpm --filter @tenmina/api-client generate` after any API change.
