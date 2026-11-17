# UI audit report

Run 2026-11-17 19:35 UTC by `scripts/ui-audit/audit.js` against the seeded development data (`seed_dev`).
Modes: 390x844 light, 390x844 dark, 1280x800 light, 1280x800 dark. Contrast threshold 4.5:1, or 3:1 for text 24 px and up or bold 18.66 px and up.

Pages visited: 472 (610 views including in-page tabs), each checked in 4 modes.

| Check | Findings |
|---|---|
| contrast | 0 |
| overflow | 0 |
| overlap | 0 |
| broken-image | 0 |
| bad-text | 0 |
| empty | 0 |
| still-loading | 0 |
| dead-link | 0 |
| navigation | 0 |
| problem-shown (for information) | 0 |
| console (for information) | 31 |

## console

- `/check` as portal/public [all]: console: Failed to load resource: the server responded with a status of 401 (Unauthorized)
- `/fx` as portal/public [all]: console: Failed to load resource: the server responded with a status of 401 (Unauthorized)
- `/listings` as portal/public [all]: console: Failed to load resource: the server responded with a status of 401 (Unauthorized)
- `/login` as portal/public [all]: console: Failed to load resource: the server responded with a status of 401 (Unauthorized)
- `/register` as portal/public [all]: console: Failed to load resource: the server responded with a status of 401 (Unauthorized)
- `/listings/:id` as portal/public [all]: console: Failed to load resource: the server responded with a status of 401 (Unauthorized)
- `/property/assets/:id` as portal/client [all]: api 404: GET /v1/assets/01a1eaf0-8840-711f-999a-1ebf39b6305c/boundary
- `/property/assets/:id` as portal/client [all]: console: Failed to load resource: the server responded with a status of 404 (Not Found)
- `/seller/listings/:id` as portal/seller [all]: api 404: GET /v1/listings/01a1eaf0-2c0f-7fc4-af05-6c26136c3a00/photos/01a1eaf0-2cd1-7afa-9141-9e4b6930ca9f
- `/seller/listings/:id` as portal/seller [all]: console: Failed to load resource: the server responded with a status of 404 (Not Found)
- `/login` as backoffice/public [all]: console: Failed to load resource: the server responded with a status of 401 (Unauthorized)
- `/geo` as backoffice/admin [all]: console: Failed to load resource: net::ERR_TUNNEL_CONNECTION_FAILED
- `/projects/projects/:id` as backoffice/admin [all]: api 404: GET /v1/projects/01a1eaef-efb9-760a-b984-775f019157f2/aml-review
- `/projects/projects/:id` as backoffice/admin [all]: console: Failed to load resource: the server responded with a status of 404 (Not Found)
- `/geo/layers/:id` as backoffice/admin [all]: console: Failed to load resource: net::ERR_TUNNEL_CONNECTION_FAILED
- `/payees/changes/:id` as backoffice/admin [all]: api 403: GET /v1/national-id-checks/01a1eaf0-ba0c-7ada-b233-e8cb306915ec
- `/payees/changes/:id` as backoffice/admin [all]: console: Failed to load resource: the server responded with a status of 403 (Forbidden)
- `/geo` as backoffice/cm [all]: console: Failed to load resource: net::ERR_TUNNEL_CONNECTION_FAILED
- `/projects/projects/:id` as backoffice/cm [all]: api 404: GET /v1/projects/01a1eaef-efb9-760a-b984-775f019157f2/aml-review
- `/projects/projects/:id` as backoffice/cm [all]: console: Failed to load resource: the server responded with a status of 404 (Not Found)
- `/geo/layers/:id` as backoffice/cm [all]: console: Failed to load resource: net::ERR_TUNNEL_CONNECTION_FAILED
- `/geo` as backoffice/reviewer [all]: console: Failed to load resource: net::ERR_TUNNEL_CONNECTION_FAILED
- `/projects/projects/:id` as backoffice/reviewer [all]: api 404: GET /v1/projects/01a1eaef-efb9-760a-b984-775f019157f2/aml-review
- `/projects/projects/:id` as backoffice/reviewer [all]: console: Failed to load resource: the server responded with a status of 404 (Not Found)
- `/geo/layers/:id` as backoffice/reviewer [all]: console: Failed to load resource: net::ERR_TUNNEL_CONNECTION_FAILED
- `/geo` as backoffice/dpo [all]: console: Failed to load resource: net::ERR_TUNNEL_CONNECTION_FAILED
- `/projects/projects/:id` as backoffice/dpo [all]: api 404: GET /v1/projects/01a1eaef-efb9-760a-b984-775f019157f2/aml-review
- `/projects/projects/:id` as backoffice/dpo [all]: console: Failed to load resource: the server responded with a status of 404 (Not Found)
- `/geo/layers/:id` as backoffice/dpo [all]: console: Failed to load resource: net::ERR_TUNNEL_CONNECTION_FAILED
- `/payees/changes/:id` as backoffice/dpo [all]: api 403: GET /v1/national-id-checks/01a1eaf0-ba0c-7ada-b233-e8cb306915ec
- `/payees/changes/:id` as backoffice/dpo [all]: console: Failed to load resource: the server responded with a status of 403 (Forbidden)

## Coverage

- portal/public: 6 pages. Detail routes with no link from the seeded data: `/checkout/[id]`, `/confirm/[token]`.
- portal/client: 69 pages. Detail routes with no link from the seeded data: `/family/concerns/[id]`, `/family/institutions/[id]`, `/family/schedules/[id]`, `/projects/variations/[id]`, `/property/escrows/[id]/bank-details`, `/checkout/[id]`, `/confirm/[token]`.
- portal/lawyer: 8 pages. Detail routes with no link from the seeded data: `/work/boq/[id]`, `/work/errands/[id]`, `/work/inspections/[id]`, `/work/property-inspections/[id]`, `/work/tasks/[id]`, `/work/visits/[id]`.
- portal/surveyor: 8 pages. Detail routes with no link from the seeded data: `/work/boq/[id]`, `/work/errands/[id]`, `/work/inspections/[id]`, `/work/property-inspections/[id]`, `/work/tasks/[id]`, `/work/visits/[id]`.
- portal/inspector: 7 pages. Detail routes with no link from the seeded data: `/work/boq/[id]`, `/work/errands/[id]`, `/work/inspections/[id]`, `/work/property-inspections/[id]`, `/work/reports/[id]`, `/work/tasks/[id]`, `/work/visits/[id]`.
- portal/carer: 8 pages. Detail routes with no link from the seeded data: `/work/boq/[id]`, `/work/errands/[id]`, `/work/inspections/[id]`, `/work/property-inspections/[id]`, `/work/reports/[id]`, `/work/tasks/[id]`.
- portal/seller: 7 pages.
- portal/contractor: 6 pages.
- portal/family: 1 pages.
- portal/institution: 3 pages.
- portal/partner: 3 pages.
- portal/insurer: 5 pages.
- portal/tenant: 2 pages.
- portal/authority: 3 pages. Detail routes with no link from the seeded data: `/authority/listings/[id]`.
- backoffice/public: 1 pages.
- backoffice/admin: 87 pages. Detail routes with no link from the seeded data: `/audit/[res]/[id]`, `/cases/[id]/assign/[taskId]`, `/cases/[id]`, `/escrow/accounts/[id]`, `/field/[res]/[id]`, `/payees/[id]`, `/reports/[id]`.
- backoffice/cm: 79 pages. Detail routes with no link from the seeded data: `/admin/[res]/[id]`, `/audit/[res]/[id]`, `/cases/[id]/assign/[taskId]`, `/escrow/accounts/[id]`, `/field/[res]/[id]`, `/partners/[res]/[id]`, `/pay-runs/runs/[id]`, `/payees/[id]`, `/payees/changes/[id]`, `/privacy/[res]/[id]`, `/reports/[id]`.
- backoffice/reviewer: 82 pages. Detail routes with no link from the seeded data: `/admin/[res]/[id]`, `/audit/[res]/[id]`, `/cases/[id]/assign/[taskId]`, `/escrow/accounts/[id]`, `/field/[res]/[id]`, `/partners/[res]/[id]`, `/payees/[id]`, `/payees/changes/[id]`, `/reports/[id]`.
- backoffice/dpo: 87 pages. Detail routes with no link from the seeded data: `/audit/[res]/[id]`, `/cases/[id]/assign/[taskId]`, `/cases/[id]`, `/escrow/accounts/[id]`, `/field/[res]/[id]`, `/payees/[id]`, `/reports/[id]`.

## Notes (added by hand after the run)

The first run (16:06 UTC, same script, development servers) found 3 contrast failures, 5 broken images, 4 empty pages, a missing `/records` page linked from the side bar, and lists and links that the signed-in role could not open. Causes and fixes:

- Muted label on the black payment-run approval panel, 3.48:1. Cause: `.card-ink` set light text but not the dark colour tokens, so anything inside that used a token (muted text, labels, inputs, ghost and dark buttons, cards, table cells) was drawn for a white ground. Every black panel now takes the dark tokens (`packages/web-ui/src/bloc.css`, app CSS for top bars and side bar); the money ticket takes the light ones. Screenshots: `docs/screenshots/ui-audit/payrun-approval-code-label-{before,after}.png`.
- "Nothing to draw here yet" on the map in dark mode, 1.95:1. Cause: the map ground was a fixed light grey. It now follows the surface token. Screenshots: `docs/screenshots/ui-audit/geo-asset-empty-map-dark-{before,after}.png`.
- Listing photos that fail to load now show a neutral "No photo" block (`apps/portal/src/components/photo.tsx`); satellite images likewise.
- Overlap findings in the first run were false positives (closed `<details>` bodies, wrapped inline text); the script now measures line boxes and opens `<details>`.

The checker cannot see browser autofill. Browsers paint autofilled fields (saved passwords) on their own light ground, which can leave our light text on a light field on the black sign-in pages. `bloc.css` now keeps the field's own ground and text colour for autofill. This is one possible source of the white-on-white text seen on the phone; it was not reproduced here.

The earlier run (16:59 UTC) showed 4 "problem shown" pages: seed data, not screens. An escrow's `report_id`, and field inbox items for a task, an inspection and a care visit, pointed to records that `seed_dev` never created. Every seed now writes only ids of real rows (`core/seeding.py` runs a late phase for rows that need a later module's objects), and `api/core/tests/test_seed_links.py` walks the seeded database to keep it so. This run shows none. Clients sign in with a code by SMS: pass the API log with `--api-log` so the script can read it. The console lines are expected: 401 before sign-in, 404 for a property with no boundary yet, map tiles refused by this machine's network (the SVG drawing is shown instead), and 404 for a project with no money-laundering review.
