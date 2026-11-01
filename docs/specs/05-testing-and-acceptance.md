# 05 — Testing and Acceptance

Test strategy, test cases, acceptance criteria and traceability for the Fidero platform.

## 1. Document control

| Item | Value |
|---|---|
| Document | 05 of 6 in `docs/specs/` |
| Title | Testing and acceptance |
| Version | 0.2 |
| Date | 1 November 2026 |
| Status | Draft. For review. Not yet baselined |
| Owner | QA and test lead (role to be filled), for the founder as product owner |
| Approver | Founder, acting as product owner |
| Source of truth | `docs/specs/01-requirements-and-product-specification.md` (document 01), version 0.3 |
| Other sources | `docs/decisions/2026-11-01-diaspora-platform.md`, `docs/operations/verification-report-template.md`, `docs/operations/milestone-schedule.md`, `docs/validation-plan.md`, `docs/product/architecture.md` |
| Related documents | Document 02 (architecture), document 04 (epics `EP-<MODULE>` and user stories `US-<MODULE>-nnn`), document 06 (operations, runbooks, backup and restore) |

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 31 October 2026 | QA and test architect | First draft for review, against document 01 version 0.1 |
| 0.2 | 1 November 2026 | QA and test architect | Updated to document 01 version 0.3 (195 functional requirements, 25 business rules). Fidero is now the diaspora's trusted agent at home, per `docs/decisions/2026-11-01-diaspora-platform.md`. Adds risk rows and functional tests for the new modules FEE, CARE, PMG, TSK, INS and EVT; rule tests for RUL-22 to RUL-25 with abuse cases; tests for the new and changed FRs (FR-ACC-012, FR-ESC-014, FR-ESC-015, FR-MOB-012, FR-CTY-004; FR-ACC-007, FR-ACC-008, FR-ACC-011, FR-ESC-004, FR-ESC-006, FR-ESC-010, FR-MOB-010, FR-ADM-003, FR-ADM-005); state tests for the revised escrow, milestone, listing and dispute models from 01 version 0.2; journeys J-09 to J-12; security threats for institution impersonation, invoice tampering, payee substitution, check-in spoofing, confirmation-code brute force and cross-country access; carer and errand agent field trials; UAT for P-15 to P-17 and an institution contact; partner acceptance with an institution and an insurer; country configuration moved to R1 and the country-2 gate added to release acceptance. NFR tests updated for the renamed NFR-A11Y-01 and the measurable NFR-USE-01, NFR-USE-02, NFR-PERF-03 and NFR-AVL-01. Traceability and counts regenerated. Section 16 refreshed: 25 items closed by 01 versions 0.2 and 0.3, 12 kept, 14 added |

Every figure in this document is a working assumption, not verified data. Unknown numbers are marked `[TO VERIFY]`. Test tooling named here is a proposal. The engineering lead confirms it before R1 build starts.

### 1.1 How to read this document

- Section 2 sets the strategy: what we test, how deep, where and when.
- Sections 3 to 7 hold the test cases: business rules, functional requirements, state models, journeys and non-functional requirements.
- Sections 8 to 11 cover security, mobile and field, accessibility and usability, and acceptance by users, operations and partners.
- Sections 12 to 15 cover defects, release acceptance, traceability and metrics.
- Section 16 lists problems found in document 01. Document 01 is not changed here.

### 1.2 Test identifiers

Shared conventions (used by other documents):

| Prefix | Meaning | Example |
|---|---|---|
| `TC-<MODULE>-nnn-xx` | Functional test for `FR-<MODULE>-nnn` | TC-ESC-006-01 tests FR-ESC-006 |
| `TC-RUL-nn-xx` | Business-rule test for `RUL-nn` | TC-RUL-05-02 |
| `TC-NFR-<AREA>-nn-xx` | Non-functional test for `NFR-<AREA>-nn` | TC-NFR-PERF-03-01 |
| `TC-E2E-J0n-xx` | End-to-end journey test for `J-0n` | TC-E2E-J02-03 |
| `UAT-nn` | User acceptance scenario | UAT-07 |
| `US-<MODULE>-nnn` | User story in document 04. `nnn` equals the FR number | US-ESC-007 implements FR-ESC-007 |
| `S1` to `S4` | Defect severity | S1 critical |

Local conventions (used only in this document):

| Prefix | Meaning | Example |
|---|---|---|
| `TC-STM-<MODEL>-nn` | State-transition test for a state model in 01 C8 | TC-STM-ESC-04 |
| `TC-SEC-nn` | Threat-driven security test | TC-SEC-01 |
| `TC-FLD-nn` | Mobile device, network and field test | TC-FLD-05 |
| `OAT-nn` | Operational acceptance test | OAT-03 |
| `PAT-nn` | Partner acceptance test with the escrow bank or another partner | PAT-02 |

Suffix `-01` is normally the positive case. `-02` and above are negative, boundary or abuse cases.

### 1.3 Column conventions in test tables

| Column | Values |
|---|---|
| Priority (Pri) | P1: Must requirement or money, evidence or access risk. P2: Should requirement. P3: Could requirement |
| Automated (Auto) | Y: automated in CI. N: manual. P: partly automated (scripted checks plus a manual step) |
| Level | U unit, I integration, C contract, A API, E end-to-end web, M mobile, NF non-functional, S security, UAT user acceptance |
| Release (Rel) | R1, R2, R3. The release in which the test first becomes a release gate |

---

## 2. Test strategy

### 2.1 Objectives

1. Prove that no function lets Fidero receive or hold client purchase, construction, project, fee, rent or premium money (RUL-01, RUL-24, RUL-25, C-01).
2. Prove that money can only be released through the full chain: conditions closed, fresh search in date where required, no open dispute, client approval, two different staff approvals with MFA, signed instruction, bank confirmation.
3. Prove that money on every line goes only to a verified institution, supplier, vendor or professional whose bank account name matches, and never as cash to a relative or representative (RUL-22, RUL-23).
4. Prove that evidence and reports cannot be changed, replaced or faked without detection. This includes care visit check-ins, invoices, receipts and the documents that close an errand.
5. Prove that each user sees only what their role, assignment and country allow.
6. Prove that every Must requirement in document 01 works for its release, and every business rule RUL-01 to RUL-25 is enforced.
7. Prove that the product works on a low-end Android phone on a slow, dropping connection, for contractors, inspectors, carers and errand agents.
8. Prove that a second country runs on configuration only, with its data separate from Ghana's.
9. Give the product owner the evidence to accept or reject each release, against 01 C9, and to open or hold a new country against C-13.

### 2.2 Risk-based approach

Testing depth follows risk. Risk is the likelihood of failure times the impact on client money, evidence integrity, personal data, people's safety and Fidero's reputation and insurance. The redefinition in `docs/decisions/2026-11-01-diaspora-platform.md` adds two risks that did not exist before: money-critical payee verification on every line (FEE, RUL-22, FR-ESC-015), and the safety of vulnerable people visited at home (CARE).

| Module | What can go wrong | Likelihood | Impact | Risk | Test depth |
|---|---|---|---|---|---|
| ESC Escrow | Release with an open condition, open dispute, stale search, missing client approval or one approver; Fidero account shown to client; wrong amount or payee in instruction; held balance over-released | Medium | Critical | Very high | Deepest: unit, property-based, integration, contract, E2E, security, partner acceptance, UAT |
| FEE Payments to institutions | Fake or impersonated institution verified; payee account name does not match the institution; invoice altered or for the wrong person; payment released without the client's approval; receipt never returned; runner cash voucher unreconciled | High | Critical | Very high | Deepest: unit, property-based on payee matching, integration, E2E, security, partner acceptance with an institution, UAT with P-15 |
| CARE Care visits | Carer paid for a visit that did not happen; carer or client confirms their own visit; check-in spoofed; missed visit not alerted; concern about a vulnerable person not raised; unvetted carer assigned; family address and health data exposed | Medium | Critical (safety of a vulnerable person) | Very high | Deepest: device tests, field trials with carers, security, integration, UAT with P-15 and P-17; safety cases reviewed with operations |
| RPT Report builder | Green verdict with a red section; unlocked scope text; single-person release; released report changed; wrong hash | Medium | Critical | Very high | Deepest: unit, property-based, integration, E2E, PDF hash checks, UAT with lawyer and reviewer |
| EVD Evidence store | Evidence overwritten or deleted silently; public links; malware stored | Medium | Critical | Very high | Deepest: integration with object storage, security, restore tests |
| MOB Milestone app | Gallery upload accepted; GPS or clock spoofed; queue lost offline; key extracted | High | Critical | Very high | Deepest: device matrix, instrumented tests, field trials, mobile security tests |
| BLD Construction | Release without inspector pass; conflicted inspector; defect value not held; re-pricing skipped | Medium | Critical | Very high | Deepest: property-based, integration, E2E, field trials |
| AUD Audit | Entries edited or missing; chain broken undetected | Low | Critical | High | Deep: database permission tests, hash-chain verification, tamper drills |
| DPR Data protection | Bulk export by one person; data kept past retention; consent missing | Medium | High | High | Deep: integration, security, UAT with administrator |
| PAY Fee payments | Card data stored; escrow money accepted as a fee; double case creation from duplicate webhooks | Medium | High | High | Deep: sandbox integration, contract, idempotency, reconciliation tests |
| ACC Accounts | IDOR, MFA bypass, licence check bypass, lockout abuse | Medium | High | High | Deep: API authorisation matrix, security |
| PTR Partner API | Verdict or report shared without consent; enumeration | Medium | High | High | Deep: contract, authorisation, rate limit |
| DSP Disputes | Release not frozen; deadlines wrong | Medium | High | High | Deep: integration, state tests |
| CASE Case workflow | Task closed without evidence; unsafe visit assignment | Medium | High | High | Standard plus RUL-17 safety cases |
| GEO Geospatial | Wrong inside, near or clear result; stale layer used | Medium | High | High | Standard plus geometry fixtures and property tests |
| LST Listings | Listing live without a green, in-date report; badge not expired | Medium | Medium | Medium | Standard plus RUL-12 to RUL-14 |
| NTF Notifications | Report content or money amounts in SMS or WhatsApp | Medium | Medium | Medium | Standard plus content-leak tests |
| PRJ Project funds | Cash to project runner; unchecked supplier | Low | High | Medium | Standard plus RUL-21 |
| PMG Property management | Rent routed to a Fidero account or a Fidero-controlled account; repair paid without inspection or against one quote; tenant sees owner data; late rent not alerted | Medium | High | High | Deep: integration, state tests, RUL-24 abuse cases, UAT with P-16 and a tenant |
| TSK Paperwork and errands | Official fee paid to the agent, not the agency; errand closed without the resulting document; forged receipt or acknowledgement; client identity documents exposed | Medium | High | High | Deep: integration, E2E, RUL-22 and RUL-23 abuse cases, field trial with agents |
| INS Insurer partner lines | Premium collected into a Fidero account; policy shown as Fidero's; claim decided by Fidero; application data sent to the wrong insurer | Low | High (licence and legal risk, C-11) | Medium | Standard plus RUL-25 abuse cases and partner acceptance with the insurer |
| EVT Events and ceremonies | Vendor paid without invoice or delivery evidence; deposit paid without signed quote; vendor not verified | Low | Medium | Low | Standard at R3 plus RUL-22 |
| ORD Orders | Case created without payment | Low | Medium | Medium | Standard |
| ADM Administration | Scope text, bank details or a release-affecting value changed by one person; config change unaudited | Low | High | Medium | Standard plus RUL-04 and second-administrator cases |
| ANL Analytics | Personal data in dashboards; metrics mixed across countries | Low | Medium | Low | Standard |
| RAT Ratings | Ratings manipulated | Low | Low | Low | Light |
| REC Records | Wrong pre-fill of ownership chain | Low | Medium | Low | Standard at R3 |
| CTY Multi-country | A Ghana user sees country-2 data or the reverse; Ghana values hard-coded; data stored in the wrong country; a country opened before its gate | Medium | High | High | Deep from R1: authorisation matrix by country, configuration-only checks, data location audit at R2 |

Rules that follow from the matrix:

- Every RUL test and every test on ESC, FEE, CARE, RPT, EVD, MOB, BLD, AUD, DPR and PAY Must requirements is P1 and automated where possible.
- Very high risk modules need property-based tests (hypothesis) on their decision functions, for example "may this release be instructed?", "does this payee match the verified institution?" and "what overall verdicts are allowed?". The property is stated in the test, such as "for any combination of section verdicts with a red in 4 to 10, green is never allowed" or "for any payee whose account name differs from the verified name, no instruction is generated".
- Very high risk modules need mutation testing on the release and verdict decision code before each release `[TO VERIFY]` tool choice, such as mutmut. Target: no surviving mutants in those functions.
- A defect in any very high risk area is at least S2. A defect that lets money move, or evidence change, without the rules is S1 (section 12).

### 2.3 Test levels

| Level | What it tests | Owner | Proposed tools |
|---|---|---|---|
| Unit | Functions and classes in isolation: verdict rules, release eligibility, deadline maths, re-pricing, hashing | Developers | pytest, pytest-django, factory_boy, hypothesis; Jest or Vitest for web; JUnit for Android |
| Integration | Module with real PostgreSQL and PostGIS, Celery tasks, object storage emulator, Redis | Developers | pytest with test containers, LocalStack or MinIO for storage `[TO VERIFY]` |
| Contract | API schema and partner interfaces stay stable: portal and back office against core API; bank instruction and statement formats; payment provider webhooks | Developers, QA | schemathesis against the OpenAPI schema; Pact for portal, back office and app consumers |
| API | Business flows through the public API, including authorisation for every role | QA | pytest with an API client; generated role-by-endpoint matrix |
| End-to-end web | Journeys through portal and back office in a browser | QA | Playwright, including a throttled 3G profile |
| Mobile | Milestone app on emulators and real devices | QA, Android developer | Espresso, UI Automator, Android emulator network shaping |
| Non-functional | Performance, availability, recovery, scalability, observability | QA, engineering lead | k6, Lighthouse CI, AWS fault injection `[TO VERIFY]` |
| Security | SAST, dependency scan, DAST, ASVS L2 checks, threat cases, penetration test | Engineering lead, external tester | Semgrep, Bandit, dependency scanning, OWASP ZAP, MobSF for the app `[TO VERIFY]` |
| Accessibility | WCAG 2.2 AA | QA, designer | axe-core in Playwright, manual screen reader checks |
| User acceptance (UAT) | The product does the job for real users | Product owner, real users, staff, partners | Staging, scripted scenarios, sign-off forms |
| Operational acceptance (OAT) | The product can be run: backups, restore, alerts, runbooks, deploy and rollback | Engineering lead, operations | Staging and production drills, runbooks in document 06 |

### 2.4 Test types per release

| Test type | R0 | R1 | R2 | R3 |
|---|---|---|---|---|
| Manual process checks against the report template and rules | Yes | Yes (regression of process) | Yes | Yes |
| Unit and property-based | No software | Yes | Yes | Yes |
| Integration (PostGIS, Celery, storage) | No | Yes | Yes | Yes |
| Contract: internal API | No | Yes | Yes | Yes |
| Contract: payment provider sandbox | Payment link only | Yes | Yes | Yes |
| Contract and partner acceptance: escrow bank | Manual letters | Manual entry and instruction format; held balance with small releases | Statement file, API if available; partial releases | Plus country-2 partner `[TO VERIFY]` |
| Partner acceptance: institutions (receipt return) | Manual, existing clients | Yes, at least one school and one hospital `[TO VERIFY]` | Yes, plus institution portal or file (IF-10) | Yes, per country |
| Partner acceptance: insurer (premium routing, policy return) | No | No | Yes, one insurer per country (AS-11) | Yes |
| E2E web, including 3G profile | Landing page only | Yes | Yes | Yes |
| Mobile app and device matrix | No | No (phone browser only) | Yes | Yes |
| Field trials | No | Phone browser tasks for runners | Yes: contractors, inspectors, carers, errand agents | Yes, in country-2 pilot |
| Country isolation and configuration-only checks | No | Yes (Ghana plus a synthetic test country) | Yes, country 2 if its gate passes | Yes, countries 2 and 3 |
| Performance and load | No | Yes | Yes plus NFR-SCL-01 | Yes |
| Security: SAST, dependency, DAST | Landing page and payment link review | Yes | Yes | Yes |
| Independent penetration test | No | Yes (before go-live, incl. payee verification and country separation) | Yes (incl. app, partner API, care check-in, insurer and institution interfaces) | Yes (incl. live country data split) |
| Accessibility WCAG 2.2 AA | Landing page | Yes, web | Yes, web and Android app | Yes |
| Usability (NFR-USE-01) | Observe manual ordering | Yes | Regression | Regression |
| UAT | Day-90 review | Yes | Yes | Yes |
| OAT, backup restore, runbooks | Spreadsheet backups | Yes | Yes plus country-2 hosting | Yes plus country-3 hosting |

R0 has no platform. Its acceptance is the day-90 gate in `docs/validation-plan.md` section 6. During R0, QA still checks every delivered report by hand against RUL-02, RUL-03, RUL-04 and RUL-20, using a paper checklist. R0 also pays institution fees by hand for existing clients. QA checks each of these payments against RUL-22 by hand: institution verified, account name matches, receipt returned. These checks feed the R1 test data, the institution fixtures and the UAT scripts.

Country 2 starts its manual phase at about month 6 (01 Releases table, C-13). Its software is tested as a configuration of the same platform, not as a separate product. Country-2 tests run under the country-2 settings in staging from R2, once its own day-90 gate has passed (AS-13).

### 2.5 Entry and exit criteria per level

| Level | Entry criteria | Exit criteria |
|---|---|---|
| Unit | Code compiles; story has acceptance criteria in document 04 | All tests pass; line coverage of core API at least 80% (NFR-MNT-01); every RUL decision function has positive, negative and property tests |
| Integration | Unit tests pass; migrations apply cleanly on PostGIS | All tests pass; no flaky test quarantined for more than 5 working days (assumption) |
| Contract | OpenAPI schema published from the build; partner format specs agreed or drafted | No breaking change without a version bump; schemathesis finds no 5xx and no schema violations |
| API | Build deployed to a test environment with seeded data | Role-by-endpoint authorisation matrix passes 100%; all P1 API tests pass |
| End-to-end web | Build on staging; seeded synthetic data; sandboxes reachable | All P1 journeys pass on Chrome Android profile and one desktop browser; 3G profile journeys pass |
| Mobile | Signed debug and release builds; device farm or physical devices available | All P1 tests pass on the minimum and reference devices; offline queue tests pass |
| Non-functional | Production-like staging sizing; load scripts reviewed | Targets in section 7 met, or a waiver signed by the product owner for Should items |
| Security | Feature-complete release candidate; scope letter signed | No open high or critical findings (NFR-SEC-03); ASVS L2 checklist complete |
| Accessibility | UI stable; content final | No open WCAG 2.2 AA failures on P1 journeys |
| UAT | System test exit met; no open S1; UAT scripts and participants ready; staging matches release candidate | All UAT scenarios for the release accepted; sign-off forms signed |
| OAT | Runbooks in document 06 drafted; monitoring live on staging | Restore drill meets RPO and RTO; each runbook executed once by someone who did not write it |

### 2.6 Environments

| Environment | Purpose | Data | Integrations |
|---|---|---|---|
| Local developer | Unit and integration tests | Factories only | Fakes and recorded fixtures |
| CI (GitHub Actions) | PR and nightly gates | Factories and fixture files; created and destroyed per run | Fakes, provider sandboxes for nightly only |
| dev | Shared integration, early E2E | Synthetic seed set, reset weekly | Provider sandboxes |
| staging | System test, E2E, performance, security scans, UAT, OAT | Synthetic seed set sized to R1 or R2 volumes; no real personal data | Provider sandboxes; bank test channel `[TO VERIFY]`; test SMS numbers |
| production | Live service; smoke tests after deploy; restore drills to an isolated copy | Real data | Live providers |

Rules:

- No real personal data in any non-production environment. This includes consent videos, Ghana Card images and bank statements.
- Production data is never copied to staging. Restore drills restore production backups into an isolated, access-controlled account that is destroyed after the drill (OAT-02).
- Production smoke tests use a dedicated test client account and the payment provider's live small-value test procedure `[TO VERIFY]`. They never create an escrow or a release instruction.

### 2.7 Test data strategy

**Synthetic people and organisations.** Factories generate Ghanaian-style names (such as Akosua, Kwabena, Efua, Yaw with family names such as Mensah, Owusu, Boateng, Asante), diaspora addresses in the UK, US, Canada, Germany and the Netherlands, and Ghana localities (Kasoa, Tema, Aburi, Prampram, Kumasi). Names are drawn from a fixed list and combined at random. No real person's data is used.

**Synthetic identifiers.** Ghana Card numbers, phone numbers and Ghana Post GPS addresses follow the real formats but use reserved or invalid ranges so they cannot match real people `[TO VERIFY]` with the identity provider and telecoms providers which ranges are safe. Licence numbers use a `TEST-` prefix.

**Documents and media.** Site plans, indentures, search results and receipts are generated PDFs and images marked "SYNTHETIC TEST DOCUMENT". Consent videos are short generated clips with actors who have signed a release, or with no people.

**Map layer fixtures.** A synthetic layer set with known geometry around a fictional grid: one acquisition polygon, one road reserve strip, one wetland, one flood zone, one dispute area and one planning zone. Plot fixtures cover inside, touching the edge, inside the buffer, just outside the buffer, clear, multipolygon, very small, very large, self-intersecting and invalid polygons. A second layer version tests versioning. If licences allow, a snapshot of real layers is loaded in staging only `[TO VERIFY]`.

**Bank statement file fixtures.** The real format is not yet known (AS-03, Q-01). Fixtures are written in the draft format and replaced when the bank confirms. Cases: exact match, unmatched line, two escrows with the same amount, amount short, amount over, wrong currency, duplicate line, reversal, line with missing reference, file with bad header, empty file, file for the wrong date, file imported twice.

**Payment provider sandbox.** Card approved, card declined, 3-D Secure challenge passed and failed, mobile money approved, mobile money timeout, insufficient funds, refund, duplicate webhook, webhook out of order, webhook with a bad signature, settlement file with a mismatch.

**Identity provider sandbox.** Pass, fail, manual review, provider down. If no sandbox exists, a fake service with the same contract is used `[TO VERIFY]`.

**Messaging.** Email to a capture service in non-production. SMS and WhatsApp to provider test numbers only, with a deny list that blocks any other number in non-production.

**Institutions and payees.** A synthetic set of schools, hospitals, clinics, pharmacies, agencies and utilities with registration numbers in a `TEST-` range, each with a verified bank account in the institution's name and a named contact. Negative fixtures: an institution with no registration; one whose account name differs from its registered name by one word, by a trading name, by an individual's name, and by case and spacing only; one with a real-looking name that copies a well-known hospital `[TO VERIFY]` that the name is not protected; one whose contact's phone belongs to the client's family member. Invoice fixtures: valid, wrong patient or student, amount altered after upload, duplicate reference, reference from another institution, invoice dated after payment.

**Carers, care plans and families.** Synthetic carers with vetting status (complete, pending, failed, expired). Care plans with two visits a week and three task types. Registered addresses in the synthetic Ghana grid. Family members marked as "may confirm" and "may not confirm". Check-in fixtures: inside the configured radius, just outside, far away, mock location on, GPS denied, no check-out.

**Properties, tenants and repairs.** Managed properties with tenancy agreements, rent due dates and the owner's own account at the partner bank. Negative fixtures: rent account set to a Fidero fee account, to a staff member's account, to the tenant's account. Repair fixtures: two quotes, one quote, quote above budget, inspection photos present and missing.

**Errands and agents.** A catalogue of five errand types for Ghana and three for the synthetic test country, each with a checklist, official fees and Fidero's charge. Agencies with verified accounts. Negative fixtures: agent's personal account as payee, errand closed without a document, acknowledgement image reused from another errand.

**Insurer and event fixtures.** One synthetic insurer with two products and a sandbox or fake interface `[TO VERIFY]` (IF-11); premium account in the insurer's name; a negative fixture with the premium account set to a Fidero account. Event vendors with invoices, delivery notes and a signed quote for a deposit.

**Test country.** A synthetic second country, "Testland", with its own currency, templates, scope statement, overlay layers, licence bodies, holiday calendar, errand catalogue and data location. It is used for isolation tests from R1 so that no test depends on the real country-2 choice (Q-15). Country-2 fixtures are added when the founder confirms the country.

**Seed sets.** `seed-r1` holds about 300 cases, 50 escrows, 20 institutions and 200 institution payments in all states (assumption, matching the R1 targets). `seed-r2` adds 40 builds, listings, disputes, partners, 10 care plans with 100 visits, 10 managed properties, 30 errands and 5 policies. `seed-scale` meets NFR-SCL-01 volumes for load tests. Every seed set holds a small Testland slice for isolation tests.

**Time control.** Deadlines, windows and expiry rules are tested with a controllable clock (freezegun or the equivalent) and with public holidays loaded from each country's holiday calendar (FR-CTY-001).

**Configurable values.** RUL-07, RUL-12 and RUL-13 windows, plot buffers, dispute deadlines, the client approval reminder period, the SMS money threshold and the project fund check threshold are not yet fixed. Tests read the value from configuration (FR-ADM-005) and check the boundary: one day inside, exactly on, and one day outside the window. Tests do not hard-code a number. The check-in radius for care visits and the receipt return target for institutions are not in FR-ADM-005 (section 16); tests read them from configuration as well.

### 2.8 Automation pyramid

Target shape by count of automated tests (assumption):

| Layer | Share of automated tests | Runs |
|---|---|---|
| Unit and property-based | About 65% | Every PR |
| Integration and API | About 25% | Every PR |
| Contract | About 5% | Every PR |
| E2E web and mobile UI | About 5% | Smoke on PR; full nightly |

Manual testing is kept for exploratory testing, usability, accessibility with screen readers, field trials, UAT and the penetration test.

### 2.9 CI gates

| Gate | When | Must pass |
|---|---|---|
| PR gate | Every pull request | Lint and type checks; unit and property tests (fast hypothesis profile); integration tests on PostGIS; contract tests; the full `rul` test tag with zero skips; API authorisation matrix, including the country dimension; coverage of core API at least 80% and not lower than main; migration check; Semgrep and Bandit with no new high findings; dependency scan with no new high or critical; secret scan; hard-coded country check (no "GH", "GHS" or Ghana text outside configuration); web unit tests; axe checks on changed components; Playwright smoke (sign in, order, release block, payee mismatch block) |
| Merge to main | After PR gate | PR gate re-run on the merge result; deploy to dev |
| Nightly | Every night on staging | Full Playwright regression including 3G profile; extended hypothesis profile; OWASP ZAP baseline scan; k6 smoke load; Android instrumented tests on the emulator matrix (R2 on); audit hash-chain verification job; flaky test report |
| Weekly | Once a week | Backup restore test into an isolated account (automated part of OAT-02); dependency licence report; full ZAP active scan on staging |
| Pre-release | Before each release candidate goes to UAT and again before go-live | Full regression green; k6 load at target; ZAP full scan; mutation test on release and verdict code; WCAG audit; penetration test closed (NFR-SEC-03); UAT, OAT and partner acceptance signed; go/no-go checklist (section 13.4) |

A test tagged `rul` cannot be skipped, marked as expected to fail or quarantined. A pipeline that skips one fails.

---

## 3. Business-rule test suite

Every rule in 01 B7 has at least one positive and one negative or abuse test. All tests in this section carry the `rul` tag (section 2.9). Where a rule has an unset value (`[TO VERIFY]` in 01), the test reads the configured value and checks the boundary.

Levels: U unit, I integration, A API, E end-to-end web, M mobile, S security. Auto: Y automated, N manual, P partly automated.

### 3.1 Money rules (RUL-01, RUL-05, RUL-06, RUL-07, RUL-11, RUL-15, RUL-18, RUL-21)

| ID | Rule | Preconditions | Steps | Expected result | Level | Auto | Rel |
|---|---|---|---|---|---|---|---|
| TC-RUL-01-01 | RUL-01 | Escrow in Agreed state | Client opens the escrow payment page | Only the bank's account details and reference are shown. No Fidero account, card form or mobile money prompt appears | E | Y | R1 |
| TC-RUL-01-02 | RUL-01 | API route inventory generated from the build | Scan every route, Celery task and payment provider product configuration for any intent that takes money other than a fee order | No route, task or provider product accepts purchase, construction or project money. Any new payment route fails the check unless it is linked to a fee order type | U/S | Y | R1 |
| TC-RUL-01-03 | RUL-01 | Client with a fee order | Tamper the payment request to change order type to "escrow deposit" or amount to the purchase price | Request rejected with a validation error; no payment intent created; attempt audited | A/S | Y | R1 |
| TC-RUL-01-04 | RUL-01 | Payment provider sandbox | Send a webhook for a payment that is not linked to a fee order | Payment flagged for refund review; no escrow state changes; alert raised | I | Y | R1 |
| TC-RUL-05-01 | RUL-05 | Escrow Ready to release; staff A and B have release rights and MFA | A approves with MFA; B approves with MFA | State moves to Release approved; both names, times and MFA events recorded in the instruction and audit log | A | Y | R1 |
| TC-RUL-05-02 | RUL-05 | As above | A approves twice, from two sessions | Second approval rejected: "approver already recorded"; state stays Ready to release | A | Y | R1 |
| TC-RUL-05-03 | RUL-05 | Staff C has no release rights | A approves, then C approves | C's approval rejected with 403; audited | A/S | Y | R1 |
| TC-RUL-05-04 | RUL-05 | A has two accounts (same person, different emails) | Approve with both accounts | Rejected: approvals must come from two different persons (person ID, not account). If identity linking is not possible, defect raised against design | A/S | Y | R1 |
| TC-RUL-05-05 | RUL-05 | Property test | Generate random sequences of approval events by random users and roles | Instruction is never generated unless two distinct persons with release rights and fresh MFA approved | U | Y | R1 |
| TC-RUL-06-01 | RUL-06 | Escrow Funded; all conditions closed with evidence; fresh search in date | Request release approval | Allowed; state Ready to release | A | Y | R1 |
| TC-RUL-06-02 | RUL-06 | One condition open | Request release approval through UI and directly through the API | Blocked with the open condition named; no instruction generated | A/E | Y | R1 |
| TC-RUL-06-03 | RUL-06 | Both approvals given; then a case manager reopens a condition before sending | Try to send the instruction | Blocked; approvals invalidated; state back to Funded | A | Y | R1 |
| TC-RUL-06-04 | RUL-06 | Property test | Random sets of conditions in open and closed states | Send is allowed only when the open set is empty | U | Y | R1 |
| TC-RUL-07-01 | RUL-07 | Fresh-search case released N days ago, N one day inside the configured window | Request release | Allowed | A | Y | R1 |
| TC-RUL-07-02 | RUL-07 | Fresh search exactly on the window limit, and one day past it | Request release in each case | On the limit: allowed or blocked as the configured rule says (inclusive by default, see section 16); past it: blocked with "fresh search out of date" | U/A | Y | R1 |
| TC-RUL-07-03 | RUL-07 | No fresh-search case linked | Request release | Blocked with "fresh search missing" | A | Y | R1 |
| TC-RUL-07-04 | RUL-07 | Fresh search linked to a different asset | Request release | Blocked; asset mismatch reported | A | Y | R1 |
| TC-RUL-11-01 | RUL-11 | Milestone Inspected (pass); client signed in | Client approves | Milestone moves to Client approved only. No instruction is sent until two staff approve | A/E | Y | R2 |
| TC-RUL-11-02 | RUL-11 | Client signed in | Client calls the staff release-approval endpoint or sends a crafted request to send an instruction | 403; audited; no state change | A/S | Y | R1 |
| TC-RUL-11-03 | RUL-11 | Client is also a Fidero staff member with release rights (test fixture) | Staff-client approves their own escrow as staff | Rejected: party to the escrow cannot approve its release | A/S | Y | R1 |
| TC-RUL-11-04 | RUL-11 | Purchase escrow Ready to release; client has not approved | Two staff approve | Rejected: client approval missing; state stays Ready to release (01 C8 Escrow, Client approved) | A | Y | R1 |
| TC-RUL-11-05 | RUL-11 | Milestone Inspected (pass); client silent past the configured reminder period | Run reminder job; try staff approval | Reminders sent; state stays Inspected; staff approval rejected; silence is never approval | A | Y | R2 |
| TC-RUL-11-06 | RUL-11 | Property test | Random sequences of client, staff and bank events | Instruction is never generated without an explicit client approval event that is later than the last condition change | U | Y | R1 |
| TC-RUL-15-01 | RUL-15 | Escrow Funded; dispute opened against it | Request release approval | Blocked; escrow shows Frozen; dispute linked | A | Y | R2 |
| TC-RUL-15-02 | RUL-15 | Escrow Release approved (both approvals given), instruction not yet sent | Open dispute, then try to send | Send blocked; approvals invalidated; state Frozen | A | Y | R2 |
| TC-RUL-15-03 | RUL-15 | Construction project with three milestones; dispute on milestone 2 | Try release on milestones 2 and 3 | Milestone 2 frozen; milestone 3 follows the configured scope of the freeze (see section 16); both outcomes recorded | A | Y | R2 |
| TC-RUL-15-04 | RUL-15 | Dispute closed | Request release again | Freeze lifted; normal checks apply again, including fresh search date | A | Y | R2 |
| TC-RUL-18-01 | RUL-18 | Milestone Inspected (pass); USD guide rate changed since budget | Open client approval | New GHS amount shown with old amount, rate and date; client must approve the changed amount | A/E | Y | R2 |
| TC-RUL-18-02 | RUL-18 | Re-pricing job failed or rate older than the configured age | Request release approval | Blocked: "re-pricing missing or stale" | A | Y | R2 |
| TC-RUL-18-03 | RUL-18 | Client approved before a rate change | Rate changes before staff approval | Client approval invalidated; client must approve again | A | Y | R2 |
| TC-RUL-21-01 | RUL-21 | Project with checked supplier S and invoice I for stage 1 confirmed | Release to S against I | Allowed; instruction names S's bank details from the supplier record | A | Y | R2 |
| TC-RUL-21-02 | RUL-21 | Person running the project is P | Try to add P as payee, or create a payee with P's account details | Rejected: project runner cannot be a payee; matching account details flagged | A/S | Y | R2 |
| TC-RUL-21-03 | RUL-21 | Supplier not yet checked, or invoice missing | Request release | Blocked with reason | A | Y | R2 |
| TC-RUL-21-04 | RUL-21 | Invoice already paid on another release | Reuse invoice | Rejected as duplicate | A | Y | R2 |

### 3.2 Report rules (RUL-02, RUL-03, RUL-04, RUL-20)

| ID | Rule | Preconditions | Steps | Expected result | Level | Auto | Rel |
|---|---|---|---|---|---|---|---|
| TC-RUL-02-01 | RUL-02 | Report with sections 4 to 10 all green | Set overall verdict green | Allowed | U/A | Y | R1 |
| TC-RUL-02-02 | RUL-02 | Section 7 red, others green | Set overall green through UI and API | Blocked; allowed values amber or red shown; attempt audited | A/E | Y | R1 |
| TC-RUL-02-03 | RUL-02 | Section 10 red only | Set overall green | Blocked (rule covers 4 to 10; see section 16 on the template's "4 to 9") | U | Y | R1 |
| TC-RUL-02-04 | RUL-02 | Overall green set; then section 5 changed to red | Save section | Overall verdict reset to unset or blocked from release until reset | U/A | Y | R1 |
| TC-RUL-02-05 | RUL-02 | Property test | Generate every combination of red, amber, green for sections 4 to 10 | Green allowed only where no section 4 to 10 is red | U | Y | R1 |
| TC-RUL-03-01 | RUL-03 | Report in review; lawyer L signed legal section; reviewer R is a different person | L approves; R approves | Report released; both recorded | A | Y | R1 |
| TC-RUL-03-02 | RUL-03 | As above | R approves twice, or L approves as both lawyer and reviewer | Release blocked; "two different people required" | A | Y | R1 |
| TC-RUL-03-03 | RUL-03 | Lawyer L2 did not sign the legal section | L2 tries the lawyer approval | Rejected: only the signing lawyer can approve | A | Y | R1 |
| TC-RUL-03-04 | RUL-03 | Legal section edited after L approved | Try to release | Blocked; L's approval invalidated | A | Y | R1 |
| TC-RUL-04-01 | RUL-04 | Locked scope statement version v1 | Generate report | Section 12 text equals v1 byte for byte; version stored on report | U/I | Y | R1 |
| TC-RUL-04-02 | RUL-04 | Report in draft | Try to edit section 12 through UI, API, and by editing the report template | Edit rejected in each path; audited | A/S | Y | R1 |
| TC-RUL-04-03 | RUL-04 | Released PDF | Extract section 12 text from PDF | Matches locked v1 exactly | I | Y | R1 |
| TC-RUL-20-01 | RUL-20 | Lawyer with verified licence, expiry in future | Sign legal section | Allowed; name, licence number and time recorded | A | Y | R1 |
| TC-RUL-20-02 | RUL-20 | Licence expired yesterday, or unverified | Try to sign | Blocked with reason; case manager alerted | A | Y | R1 |
| TC-RUL-20-03 | RUL-20 | Licence verified but for the wrong body (surveyor licence on a lawyer) | Try to sign legal section | Blocked | A | Y | R1 |
| TC-RUL-20-04 | RUL-20 | Licence expires between signing and release | Release | Release allowed only if the signature was valid at signing time; expiry noted (see section 16) | A | Y | R1 |

### 3.3 Evidence and construction rules (RUL-08, RUL-09, RUL-10, RUL-19)

| ID | Rule | Preconditions | Steps | Expected result | Level | Auto | Rel |
|---|---|---|---|---|---|---|---|
| TC-RUL-08-01 | RUL-08 | Contractor on assigned milestone | Capture photo with app camera and submit | Accepted; item marked app-captured with valid device signature | M/I | Y | R2 |
| TC-RUL-08-02 | RUL-08 | As above | Try to pick from gallery, share a file into the app, or use the file picker | No path exists; share intent rejected with a message | M | Y | R2 |
| TC-RUL-08-03 | RUL-08 | Valid contractor token | Upload a file directly to the submission API without a device signature | Stored as uploaded (not evidence) or rejected; cannot satisfy a milestone evidence item | A/S | Y | R2 |
| TC-RUL-08-04 | RUL-08 | Rooted device or emulator with a forged signature | Submit evidence signed with an unregistered key | Signature fails; item flagged; not counted | S | P | R2 |
| TC-RUL-09-01 | RUL-09 | Milestone with inspector pass | Complete approvals | Release allowed for full milestone amount | A | Y | R2 |
| TC-RUL-09-02 | RUL-09 | Inspector pass with defects valued GHS X | Complete approvals | Instruction amount equals milestone amount minus X; X held | A | Y | R2 |
| TC-RUL-09-03 | RUL-09 | Inspector fail, or no inspection recorded | Request release | Blocked | A | Y | R2 |
| TC-RUL-09-04 | RUL-09 | Defects valued above milestone amount | Record outcome | Rejected or flagged for reviewer; never a negative release | U | Y | R2 |
| TC-RUL-09-05 | RUL-09 | Milestone 0 (mobilisation); contract signed; Fidero staff member confirms site handover | Client approves; two staff approve | Release allowed without evidence or inspection (the RUL-09 exception) | A | Y | R2 |
| TC-RUL-09-06 | RUL-09 | Milestone 0; contract unsigned, or handover not confirmed, or confirmed by the contractor | Request release | Blocked; contractor cannot confirm handover | A | Y | R2 |
| TC-RUL-09-07 | RUL-09 | Milestone 1 (foundation) with the mobilisation flag set by tampering | Request release without inspection | Blocked; the exception applies to milestone 0 only (property test over all milestones) | U/S | Y | R2 |
| TC-RUL-10-01 | RUL-10 | Inspector with no recorded link to contractor | Assign | Allowed | A | Y | R2 |
| TC-RUL-10-02 | RUL-10 | Inspector recorded as employee, payee or nominee of the contractor | Assign | Blocked with conflict reason | A | Y | R2 |
| TC-RUL-10-03 | RUL-10 | Contractor signed in | Try to choose or change inspector through API | 403 | A/S | Y | R2 |
| TC-RUL-10-04 | RUL-10 | Contractor tries to pay inspector through a project payment | Create payment line to inspector | Rejected | A | Y | R2 |
| TC-RUL-19-01 | RUL-19 | Active milestone | Contractor proposes variation; client accepts in app | Variation recorded with both acceptances and time; budget updated | A/E | Y | R2 |
| TC-RUL-19-02 | RUL-19 | Variation not accepted by client | Contractor submits milestone evidence that includes varied work | Submission flagged "unagreed variation"; release of varied value blocked | A | Y | R2 |
| TC-RUL-19-03 | RUL-19 | Variation accepted after the work's capture time | Submit | Flagged: agreement after work started | A | Y | R2 |

### 3.4 Listing, consent and safety rules (RUL-12, RUL-13, RUL-14, RUL-16, RUL-17)

| ID | Rule | Preconditions | Steps | Expected result | Level | Auto | Rel |
|---|---|---|---|---|---|---|---|
| TC-RUL-12-01 | RUL-12 | Listing with green report one day inside the configured age | Publish | Live | A | Y | R2 |
| TC-RUL-12-02 | RUL-12 | Report amber or red | Publish | Rejected; listing state Rejected | A | Y | R2 |
| TC-RUL-12-03 | RUL-12 | Green report one day older than the configured age | Publish | Rejected: "report too old, order re-verification" | A | Y | R2 |
| TC-RUL-12-04 | RUL-12 | Seller links a green report for a different asset | Publish | Rejected: asset mismatch | A/S | Y | R2 |
| TC-RUL-13-01 | RUL-13 | Live listing; clock moved to badge expiry | Run expiry job | Listing Expired; badge removed from page and API | I | Y | R2 |
| TC-RUL-13-02 | RUL-13 | Live listing; monitoring alert raised | Leave alert unresolved | Listing Suspended; badge hidden | I | Y | R2 |
| TC-RUL-13-03 | RUL-13 | Expiry job fails to run | Load listing page after expiry date | Page computes expiry at read time and hides badge (no reliance on job alone) | I | Y | R2 |
| TC-RUL-14-01 | RUL-14 | Live listing | Buyer opens listing | Link to full report works for any signed-in buyer | E | Y | R2 |
| TC-RUL-14-02 | RUL-14 | Seller tries to hide or replace report link, or attach a summary only | Edit listing | Rejected; report link is system-set | A | Y | R2 |
| TC-RUL-16-01 | RUL-16 | Client consented to share full report with partner B | B requests full report | Returned; consent ID logged | A | Y | R2 |
| TC-RUL-16-02 | RUL-16 | No consent, or consent for partner C only | B requests full report or verdict | Full report refused; only "report exists" returned | A/S | Y | R2 |
| TC-RUL-16-03 | RUL-16 | Consent withdrawn | B requests again | Refused from the moment of withdrawal | A | Y | R2 |
| TC-RUL-17-01 | RUL-17 | Plot flagged disputed; risk screen completed | Assign two people to site visit | Allowed | A | Y | R1 |
| TC-RUL-17-02 | RUL-17 | Plot flagged disputed | Assign one person, or skip risk screen | Blocked with safety message | A/E | Y | R1 |
| TC-RUL-17-03 | RUL-17 | Two people assigned; one removed later | Remove assignee | Blocked, or visit task returns to unassigned and cannot start | A | Y | R1 |
| TC-RUL-17-04 | RUL-17 | Plot flagged disputed after visit assigned | Flag set | Existing assignment re-checked; screen required before visit | A | Y | R1 |

### 3.5 Payee, care, rent and insurance rules (RUL-22, RUL-23, RUL-24, RUL-25)

These rules come from the redefinition in `docs/decisions/2026-11-01-diaspora-platform.md`. Each has abuse cases, because the threat is a person who wants money to reach a relative or themselves without proof.

| ID | Rule | Preconditions | Steps | Expected result | Level | Auto | Rel |
|---|---|---|---|---|---|---|---|
| TC-RUL-22-01 | RUL-22 | Institution verified: registration, bank account in the institution's name, named contact (FR-FEE-001) | Client approves an invoice; two staff approve | Instruction names the institution's verified account; payment released | A | Y | R1 |
| TC-RUL-22-02 | RUL-22 | Payee account name mismatch: account name differs from the verified institution name (an individual's name, a trading name, one word changed) | Request release through UI and API | Blocked with "payee name does not match"; no instruction generated; attempt audited and reviewer alerted | A/S | Y | R1 |
| TC-RUL-22-03 | RUL-22 | Fake institution: registration number not found, or belongs to a different body, or the contact's phone matches a family member on the client's account | Verify institution | Verification fails; institution stays unverified; no invoice can be approved against it | A/S | Y | R1 |
| TC-RUL-22-04 | RUL-22 | Verified institution; staff member edits the payee account after verification | Save edit | Institution returns to unverified; second-administrator approval required (FR-ADM-003); open invoices blocked until re-verified | A | Y | R1 |
| TC-RUL-22-05 | RUL-22 | Any line (project, repair, errand, event); payee is the client's representative, a family member or the project runner | Add as payee or request release | Rejected: cash to a relative or representative is never released; matching account details flagged (extends TC-RUL-21-02 to every line) | A/S | Y | R2 |
| TC-RUL-22-06 | RUL-22 | Property test | Random payees with random account names and verification states | Instruction generated only when payee is verified and the normalised account name equals the verified name | U | Y | R1 |
| TC-RUL-22-07 | RUL-22 | Runner cash payment (FR-FEE-006) | Voucher signed; runner pays in person; receipt uploaded | Allowed only against a voucher approved by two staff; reconciled within 2 working days; unreconciled voucher alerts (see section 16 on cash and RUL-22) | A/I | Y | R1 |
| TC-RUL-23-01 | RUL-23 | Carer checked in at the registered address, completed plan items, checked out; family member marked "may confirm" confirms with the one-tap code | Run carer payment | Visit confirmed; carer paid for that visit | A | Y | R2 |
| TC-RUL-23-02 | RUL-23 | Carer self-confirming: carer enters the family confirmation code from their own device, or from a device registered to the carer | Confirm | Rejected; code accepted only from the family member's registered channel; flagged for reviewer | A/S | Y | R2 |
| TC-RUL-23-03 | RUL-23 | Check-in missing, or outside the configured radius, or no check-out | Family confirms anyway | Visit marked "confirmed without check-in"; not payable until a reviewer decides; client alerted | A | Y | R2 |
| TC-RUL-23-04 | RUL-23 | Check-in valid; family does not confirm within the configured period | Run payment | Not paid; client and Fidero alerted (FR-CARE-005); visit stays unconfirmed (see section 16 on the confirmation deadline) | A | Y | R2 |
| TC-RUL-23-05 | RUL-23 | Errand with steps recorded; resulting document not yet uploaded | Request agent payment for completion | Blocked; agency fee for official steps allowed only against uploaded receipts (FR-TSK-003, FR-TSK-004) | A | Y | R2 |
| TC-RUL-23-06 | RUL-23 | Agent uploads a document image already used on another errand | Confirm completion | Hash already seen; flagged; not confirmed | A/S | Y | R2 |
| TC-RUL-24-01 | RUL-24 | Managed property; owner's own account at the partner bank recorded | Tenant pays rent; statement line imported | Rent marked received against the owner's account; owner sees it | I | Y | R2 |
| TC-RUL-24-02 | RUL-24 | Rent routed to a Fidero account: staff or owner sets the rent account to a Fidero fee account, a staff member's account or any account not in the owner's name | Save | Rejected by deny list and name check; alert raised; audited | A/S | Y | R2 |
| TC-RUL-24-03 | RUL-24 | Build inventory | Scan routes, tasks and bank instruction templates for any path that receives rent | None exists; rent only ever appears as a statement line on the owner's account (extends TC-RUL-01-02) | U/S | Y | R2 |
| TC-RUL-24-04 | RUL-24 | Tenant signed in | Tenant's rent page | Shows the owner's account at the partner bank and the agreement reference; never Fidero's details | E | Y | R2 |
| TC-RUL-25-01 | RUL-25 | Insurer partner verified; product configured | Client applies; premium instruction generated | Instruction names the insurer's account; policy page names the insurer as the policy holder's counterparty | A/E | Y | R2 |
| TC-RUL-25-02 | RUL-25 | Premium collected by Fidero: administrator sets the premium account to a Fidero account, or a fee order type "premium" is created | Save; attempt payment | Rejected by deny list and order-type allow list; alert raised (extends TC-RUL-01-02) | A/S | Y | R2 |
| TC-RUL-25-03 | RUL-25 | Claim started by client | Staff tries to record a claim decision | No function to decide; only the insurer's response can be recorded (FR-INS-004) | A | Y | R2 |
| TC-RUL-25-04 | RUL-25 | Product page and policy document | Inspect text | The insurer's name appears; no wording presents Fidero as insurer; disclaimer text from a locked block | E | Y | R2 |

---

## 4. Functional test cases

Every FR in document 01 has at least one test case. Every Must FR has at least one positive and one negative test. Steps are short. Detailed steps live in the test code or the manual test script with the same ID.

Each test case also verifies the acceptance criteria of the user story with the same number in document 04 (US-<MODULE>-nnn).

### 4.1 Accounts and identity (ACC)

| TC ID | FR | Title | Preconditions | Steps | Expected result | Pri | Auto | Rel |
|---|---|---|---|---|---|---|---|---|
| TC-ACC-001-01 | FR-ACC-001 | Sign up with verified email and phone | None | Enter email and phone; enter both one-time codes | Account created; both marked verified | P1 | Y | R1 |
| TC-ACC-001-02 | FR-ACC-001 | Sign-up rejects wrong or expired code | Codes sent | Enter wrong code; enter code after expiry; reuse a used code | Each rejected; account stays unverified; codes rate-limited | P1 | Y | R1 |
| TC-ACC-001-03 | FR-ACC-001 | Duplicate email or phone | Existing account | Sign up with the same email or phone | Rejected without revealing whether the account exists beyond a neutral message | P1 | Y | R1 |
| TC-ACC-002-01 | FR-ACC-002 | Sign in by email and password, by phone and password, and by one-time code | Verified account | Sign in each way | Session created each time | P1 | Y | R1 |
| TC-ACC-002-02 | FR-ACC-002 | Sign-in fails with wrong password or code | Verified account | Wrong password; wrong code | Neutral error; failure counted toward lockout | P1 | Y | R1 |
| TC-ACC-003-01 | FR-ACC-003 | MFA enforced for staff and approvers | Staff user with MFA enrolled | Sign in | Second factor required before any back office page | P1 | Y | R1 |
| TC-ACC-003-02 | FR-ACC-003 | Staff without MFA cannot work | Staff user without MFA | Sign in; call back office API with session | Forced to enrol; API returns 403 until enrolled | P1 | Y | R1 |
| TC-ACC-003-03 | FR-ACC-003 | Release approval needs fresh MFA | Staff signed in 20 minutes ago | Approve release | Step-up MFA challenge shown and required | P1 | Y | R1 |
| TC-ACC-004-01 | FR-ACC-004 | Identity check passes through provider | Client with Ghana Card or passport fixture | Submit identity check | Status passed; provider reference stored | P1 | Y | R1 |
| TC-ACC-004-02 | FR-ACC-004 | Report release and escrow opening blocked without identity check | Client identity status pending or failed | Try to release report; try to create escrow | Both blocked with reason | P1 | Y | R1 |
| TC-ACC-004-03 | FR-ACC-004 | Manual document check fallback | Provider down | Case manager records manual check with document image and second reviewer | Status passed (manual); evidence linked | P1 | P | R1 |
| TC-ACC-005-01 | FR-ACC-005 | Licence stored and verified | Professional invited | Admin records body, number, expiry and verification | Professional can sign | P1 | Y | R1 |
| TC-ACC-005-02 | FR-ACC-005 | Expired or unverified licence blocks signing | Licence expired or unverified | Try to sign section | Blocked (see TC-RUL-20-02) | P1 | Y | R1 |
| TC-ACC-006-01 | FR-ACC-006 | Admin invites and assigns roles | Admin signed in | Invite lawyer, surveyor, contractor, inspector | Invites sent; roles assigned on acceptance | P1 | Y | R1 |
| TC-ACC-006-02 | FR-ACC-006 | Non-admin cannot invite or change roles | Case manager signed in | Call invite and role endpoints | 403; audited | P1 | Y | R1 |
| TC-ACC-007-01 | FR-ACC-007 | User sees own and assigned items only | Two clients, two lawyers, seeded cases | Each lists cases | Each sees only owned or assigned cases | P1 | Y | R1 |
| TC-ACC-007-02 | FR-ACC-007 | IDOR on case, report, evidence, escrow, institution payment, visit, property and errand IDs | Client A signed in | Request client B's object IDs directly | 404 for every object type; audited | P1 | Y | R1 |
| TC-ACC-007-03 | FR-ACC-007 | Operational scope: case managers and reviewers see their country and team | Ghana case manager; Testland case manager; two teams in Ghana | Each opens queue and search | Ghana manager sees Ghana cases of their team only; Testland manager sees no Ghana data; reviewer sees their country | P1 | Y | R1 |
| TC-ACC-007-04 | FR-ACC-007 | Scope cannot be widened by the user | Case manager | Edit own team or country in profile or request | Rejected; only an administrator changes scope; audited | P1 | Y | R1 |
| TC-ACC-008-01 | FR-ACC-008 | Client names a read-only representative in the home country | Client with case and project | Invite representative to the case only | Representative sees that case only, read-only; project not visible | P2 | Y | R1 |
| TC-ACC-008-02 | FR-ACC-008 | Representative cannot act or be paid | Representative signed in | Try to approve, message as client, download other cases, or be added as a payee | Blocked in every path (payee path per RUL-22) | P2 | Y | R1 |
| TC-ACC-009-01 | FR-ACC-009 | Lockout after 5 failures | Verified account | 5 wrong passwords | Account locked 15 minutes; user notified | P1 | Y | R1 |
| TC-ACC-009-02 | FR-ACC-009 | Lockout boundary and expiry | Verified account | 4 failures then success; lock then wait 15 minutes | 4 failures do not lock; access returns after 15 minutes; correct password during lock rejected | P1 | Y | R1 |
| TC-ACC-010-01 | FR-ACC-010 | Notification preferences | Signed-in client | Set WhatsApp as preferred; turn off email for status | Next notification follows the preference | P2 | Y | R1 |
| TC-ACC-011-01 | FR-ACC-011 | Organisation account with several users | Developer signed in | Create organisation; add two users | Users act for the organisation and see its listings | P2 | Y | R2 |
| TC-ACC-011-02 | FR-ACC-011 | Institution and insurer organisations | Institution contact; insurer partner | Create organisation; add a second user; second user confirms an invoice or returns a policy | Both users act for the organisation; neither sees the client's other activity | P2 | Y | R2 |
| TC-ACC-011-03 | FR-ACC-011 | Organisation user cannot change the organisation's bank account | Institution user | Edit verified account | Rejected; only Fidero re-verification changes it (FR-FEE-001, FR-ADM-003) | P2 | Y | R2 |
| TC-ACC-012-01 | FR-ACC-012 | Family members, properties and institutions on one dashboard | Client with one case, one institution payment and one family member | Add a property; open home dashboard | All items listed with plain status and next date; nothing from other clients | P2 | Y | R1 |
| TC-ACC-012-02 | FR-ACC-012 | Family member data limited | Client adds a family member | Enter relationship, address, phone; try to add health details not asked for | Only catalogued fields accepted (NFR-PRIV-02); family member notified that they were added `[TO VERIFY]` consent route | P2 | Y | R1 |
| TC-ACC-012-03 | FR-ACC-012 | Dashboard on 3G phone | Client with 10 running items | Load on 3G profile | Under NFR-PERF-01 target; items paged | P2 | Y | R1 |

### 4.2 Orders and leads (ORD)

| TC ID | FR | Title | Preconditions | Steps | Expected result | Pri | Auto | Rel |
|---|---|---|---|---|---|---|---|---|
| TC-ORD-001-01 | FR-ORD-001 | Order a plot verification | Signed-in client | Enter locality, plot number, site plan ref, GPS address, seller details; upload site plan | Order saved with all fields and files | P1 | Y | R1 |
| TC-ORD-001-02 | FR-ORD-001 | Missing required fields or bad files | Signed-in client | Omit locality; upload 0-byte file; upload unsupported type | Clear field errors; nothing submitted | P1 | Y | R1 |
| TC-ORD-001-03 | FR-ORD-001 | Order a building verification | Signed-in client | Choose building; complete fields | Order uses building product line | P2 | Y | R1 |
| TC-ORD-002-01 | FR-ORD-002 | Tiers and price in client currency | Tiers configured | Client in UK selects each tier | Price shown in configured currency before payment; matches admin price | P1 | Y | R1 |
| TC-ORD-002-02 | FR-ORD-002 | Price tampering | Client at checkout | Change price or tier in request | Server recalculates; tampered price ignored; audited | P1 | Y | R1 |
| TC-ORD-003-01 | FR-ORD-003 | Scope and terms accepted with version | Order ready | View scope; accept | Acceptance stored with time and versions | P1 | Y | R1 |
| TC-ORD-003-02 | FR-ORD-003 | Payment blocked without acceptance | Order ready | Skip acceptance; call payment API directly | Payment refused | P1 | Y | R1 |
| TC-ORD-004-01 | FR-ORD-004 | Case created on confirmed payment | Order paid in sandbox | Receive confirmed webhook | One case created, status Paid | P1 | Y | R1 |
| TC-ORD-004-02 | FR-ORD-004 | No case before confirmation; no duplicates | Order pending | Send pending webhook; send confirmed webhook twice | No case for pending; exactly one case after duplicates | P1 | Y | R1 |
| TC-ORD-004-03 | FR-ORD-004 | Offline payment with proof | Case manager signed in | Record offline payment without proof, then with proof | Without proof rejected; with proof case created and audited | P1 | Y | R1 |
| TC-ORD-005-01 | FR-ORD-005 | Lead source recorded | New order | Choose "webinar" | Lead source stored and in dashboard | P2 | Y | R1 |
| TC-ORD-006-01 | FR-ORD-006 | Referral code applied | Valid code | Apply at checkout | Discount applied; reward owed recorded for referrer | P3 | Y | R1 |
| TC-ORD-006-02 | FR-ORD-006 | Self-referral and reused code | Client's own code | Apply own code | Rejected | P3 | Y | R1 |
| TC-ORD-007-01 | FR-ORD-007 | Order extra inspection | Active project | Client orders extra inspection | Fee charged at configured price; inspection task created | P2 | Y | R2 |

### 4.3 Payments for Fidero fees (PAY)

| TC ID | FR | Title | Preconditions | Steps | Expected result | Pri | Auto | Rel |
|---|---|---|---|---|---|---|---|---|
| TC-PAY-001-01 | FR-PAY-001 | Pay by card and by mobile money | Sandbox | Pay with test card; pay with test mobile money wallet | Both confirmed; order paid | P1 | Y | R1 |
| TC-PAY-001-02 | FR-PAY-001 | Declined, timeout and failed 3-D Secure | Sandbox | Use decline card; let mobile money time out; fail challenge | Order stays unpaid; plain message; retry allowed | P1 | Y | R1 |
| TC-PAY-002-01 | FR-PAY-002 | Card data never reaches Fidero | Card payment done | Search database, logs, traces and backups for test card number | Not found; only provider token and last 4 digits if any | P1 | Y | R1 |
| TC-PAY-002-02 | FR-PAY-002 | Card fields hosted by provider | Checkout page | Inspect page | Card entry is in provider-hosted field or redirect; no card field posts to Fidero | P1 | Y | R1 |
| TC-PAY-003-01 | FR-PAY-003 | Receipt by email and portal | Payment confirmed | Check email capture and portal | Receipt in both with amount, currency, date, reference | P1 | Y | R1 |
| TC-PAY-003-02 | FR-PAY-003 | No receipt for failed payment | Payment failed | Check | No receipt issued | P1 | Y | R1 |
| TC-PAY-004-01 | FR-PAY-004 | Refund with reason and approver | Paid order | Record refund | Refund stored with reason and approver; provider refund called | P2 | Y | R1 |
| TC-PAY-004-02 | FR-PAY-004 | Refund without reason or by unauthorised role | Paid order | Submit refund without reason; as runner | Rejected | P2 | Y | R1 |
| TC-PAY-005-01 | FR-PAY-005 | Fee and escrow records separate | Fee paid; escrow funded | Inspect data model and reports | Fee ledger and escrow tracker are separate tables and views; no shared balance | P1 | Y | R1 |
| TC-PAY-005-02 | FR-PAY-005 | No function to accept escrow money | Build | Run TC-RUL-01-02 inventory | Pass | P1 | Y | R1 |
| TC-PAY-006-01 | FR-PAY-006 | Daily settlement reconciliation | Settlement fixture with 1 mismatch | Run job | One mismatch listed for case manager | P2 | Y | R1 |
| TC-PAY-006-02 | FR-PAY-006 | Malformed or duplicate settlement | Bad file; same file twice | Run job | Bad file rejected with alert; second import ignored | P2 | Y | R1 |
| TC-PAY-007-01 | FR-PAY-007 | Seller invoiced for listing and success fees | Listing paid; escrow released | Run invoicing | Listing and success invoices issued to seller | P2 | Y | R2 |

### 4.4 Verification case workflow (CASE)

| TC ID | FR | Title | Preconditions | Steps | Expected result | Pri | Auto | Rel |
|---|---|---|---|---|---|---|---|---|
| TC-CASE-001-01 | FR-CASE-001 | Case from template by product line and country | Land template Ghana v2 | Create case | Case linked to template and version | P1 | Y | R1 |
| TC-CASE-001-02 | FR-CASE-001 | No template for line and country | No building template for country X | Create case | Blocked with a clear configuration error | P1 | Y | R1 |
| TC-CASE-001-03 | FR-CASE-001 | Template change does not alter open cases | Open case on v2; admin publishes v3 | Reload case | Case stays on v2 | P1 | Y | R1 |
| TC-CASE-002-01 | FR-CASE-002 | Land steps created as tasks | New land case | Inspect tasks | Nine tasks in order: intake to release, each with owner role, evidence list and target | P1 | Y | R1 |
| TC-CASE-002-02 | FR-CASE-002 | Task with no owner role or evidence in template | Faulty template | Publish template | Publish rejected | P1 | Y | R1 |
| TC-CASE-003-01 | FR-CASE-003 | Assign task and change due date with reason | Case manager | Assign surveyor; change date with reason | Assignment and date change recorded with reason | P1 | Y | R1 |
| TC-CASE-003-02 | FR-CASE-003 | Due date change without reason; assignment to wrong role | Case manager | Change date with no reason; assign runner to legal review | Both rejected | P1 | Y | R1 |
| TC-CASE-004-01 | FR-CASE-004 | Task done with evidence | Task with evidence attached | Mark done | Done | P1 | Y | R1 |
| TC-CASE-004-02 | FR-CASE-004 | Task done blocked without evidence | Evidence missing | Mark done via UI and API | Blocked; missing item named | P1 | Y | R1 |
| TC-CASE-005-01 | FR-CASE-005 | Queue sorted by due date with overdue highlighted | Seeded cases | Open queue | Sorted by due date; overdue marked | P1 | Y | R1 |
| TC-CASE-005-02 | FR-CASE-005 | Queue respects country and team scope and hides closed items | Two case managers in different teams (FR-ACC-007) | Open queue | Each sees own team's cases; released and cancelled cases not in default view | P1 | Y | R1 |
| TC-CASE-006-01 | FR-CASE-006 | Professional completes task on phone browser | Surveyor on Android Chrome 3G profile | Open task; attach evidence; complete | Works at 360 px width; task done | P1 | Y | R1 |
| TC-CASE-006-02 | FR-CASE-006 | Professional cannot see unassigned tasks | Surveyor signed in | Open another surveyor's task URL | 404 | P1 | Y | R1 |
| TC-CASE-007-01 | FR-CASE-007 | Plain status at each step | Case moves to "searches lodged" | Check client tracker | Message from template with date and next expected date | P1 | Y | R1 |
| TC-CASE-007-02 | FR-CASE-007 | Missing next date or template | Step without template text | Move step | Step blocked or default message raised to case manager; no blank status to client | P1 | Y | R1 |
| TC-CASE-008-01 | FR-CASE-008 | Request documents from client | Case in progress | Request indenture copy | Request shows in tracker; client notified; upload links to request | P1 | Y | R1 |
| TC-CASE-008-02 | FR-CASE-008 | Request to wrong party | Representative only has read access | Representative tries to upload | Blocked; only client can respond | P1 | Y | R1 |
| TC-CASE-009-01 | FR-CASE-009 | Risk screen before site visit | Any plot | Complete risk screen; assign | Allowed | P1 | Y | R1 |
| TC-CASE-009-02 | FR-CASE-009 | Visit without screen; disputed plot with one person | Disputed plot | Assign without screen; assign one person | Both blocked (TC-RUL-17-02) | P1 | Y | R1 |
| TC-CASE-010-01 | FR-CASE-010 | Log safety incident | Runner on case | Log incident | Stored in restricted log; safety lead notified | P1 | Y | R1 |
| TC-CASE-010-02 | FR-CASE-010 | Restricted access to incident log | Client and lawyer on case | Open incident log | Not visible; 404 | P1 | Y | R1 |
| TC-CASE-011-01 | FR-CASE-011 | Case costs by item | Case manager | Enter lawyer, surveyor, runner, fee and travel costs | Totals correct; feed cost per report metric | P2 | Y | R1 |
| TC-CASE-012-01 | FR-CASE-012 | Pause, cancel and refund with reasons | Case in progress | Pause with reason; resume; cancel with refund decision | States change; reasons stored; refund triggers FR-PAY-004 | P2 | Y | R1 |
| TC-CASE-012-02 | FR-CASE-012 | Cancel released case | Released case | Cancel | Blocked | P2 | Y | R1 |
| TC-CASE-013-01 | FR-CASE-013 | Building template extra steps | Building order | Create case | Permit, structural, occupancy and rates and bills steps present | P2 | Y | R1 |
| TC-CASE-014-01 | FR-CASE-014 | Fresh-search case on verified asset | Released report on asset | Create fresh-search case | Search and site check tasks only; linked to asset and escrow | P1 | Y | R1 |
| TC-CASE-014-02 | FR-CASE-014 | Fresh search on unverified asset | No released report | Create fresh-search case | Blocked | P1 | Y | R1 |
| TC-CASE-015-01 | FR-CASE-015 | Client messages within case | Client and case manager | Exchange messages | Thread kept with case; notifications sent | P2 | Y | R1 |

### 4.5 Report builder (RPT)

| TC ID | FR | Title | Preconditions | Steps | Expected result | Pri | Auto | Rel |
|---|---|---|---|---|---|---|---|---|
| TC-RPT-001-01 | FR-RPT-001 | Report from versioned template | Case in review | Build report | Sections 1 to 14 in order; template version stored | P1 | Y | R1 |
| TC-RPT-001-02 | FR-RPT-001 | Missing or reordered section | Faulty template version | Publish template | Rejected | P1 | Y | R1 |
| TC-RPT-002-01 | FR-RPT-002 | Section owner enters findings and verdict | Surveyor owns section 6 | Enter findings; attach evidence; set amber | Saved | P1 | Y | R1 |
| TC-RPT-002-02 | FR-RPT-002 | Non-owner cannot edit section | Runner signed in | Edit section 6 | 403 | P1 | Y | R1 |
| TC-RPT-003-01 | FR-RPT-003 | Allowed verdicts computed | Sections 4 to 10 green | Open verdict | Green, amber, red allowed | P1 | Y | R1 |
| TC-RPT-003-02 | FR-RPT-003 | Green blocked with any red | Any section 4 to 10 red | Set green | Blocked (TC-RUL-02-02) | P1 | Y | R1 |
| TC-RPT-004-01 | FR-RPT-004 | Locked scope inserted | Locked v1 | Build report | Exact text (TC-RUL-04-01) | P1 | Y | R1 |
| TC-RPT-004-02 | FR-RPT-004 | Scope cannot be edited | Draft report | Edit section 12 | Rejected (TC-RUL-04-02) | P1 | Y | R1 |
| TC-RPT-005-01 | FR-RPT-005 | Lawyer and surveyor sign | Valid licences | Sign | Name, licence number and time recorded | P1 | Y | R1 |
| TC-RPT-005-02 | FR-RPT-005 | Wrong signer | Surveyor tries to sign legal section | Sign | Rejected | P1 | Y | R1 |
| TC-RPT-006-01 | FR-RPT-006 | Two-person approval then release | Signed report | Lawyer and reviewer approve | Released (TC-RUL-03-01) | P1 | Y | R1 |
| TC-RPT-006-02 | FR-RPT-006 | Same person twice | Signed report | Reviewer is the lawyer | Blocked (TC-RUL-03-02) | P1 | Y | R1 |
| TC-RPT-007-01 | FR-RPT-007 | PDF and SHA-256 stored | Released report | Download PDF; hash locally | Hash equals stored hash | P1 | Y | R1 |
| TC-RPT-007-02 | FR-RPT-007 | Regenerated PDF does not replace stored PDF | Released report | Trigger regeneration | Stored PDF and hash unchanged; new version only through FR-RPT-010 | P1 | Y | R1 |
| TC-RPT-008-01 | FR-RPT-008 | Hash check passes | Reference and correct PDF | Upload to checker | "Matches" | P2 | Y | R1 |
| TC-RPT-008-02 | FR-RPT-008 | Altered PDF fails; no data leak | Edited PDF; wrong reference | Upload | "Does not match"; no report content or client name shown; rate limited | P2 | Y | R1 |
| TC-RPT-009-01 | FR-RPT-009 | Conditions structured | Green report with 3 conditions | Copy into escrow | Three condition records created with text and evidence needed | P1 | Y | R1 |
| TC-RPT-009-02 | FR-RPT-009 | Red report conditions cannot open escrow | Red report | Try to create escrow | Blocked | P1 | Y | R1 |
| TC-RPT-010-01 | FR-RPT-010 | Correction creates new version | Released v1 | Issue correction with reason | v2 created with new hash; v1 kept; client notified | P1 | Y | R1 |
| TC-RPT-010-02 | FR-RPT-010 | Released report cannot be edited | Released v1 | Edit any field via UI, API, admin | Rejected; database constraint also blocks update | P1 | Y | R1 |
| TC-RPT-011-01 | FR-RPT-011 | Anonymised version with consent | Consent on file | Generate | Names, plot numbers, coordinates and faces removed | P3 | P | R1 |
| TC-RPT-011-02 | FR-RPT-011 | No consent | Consent missing | Generate | Blocked | P3 | Y | R1 |

### 4.6 Geospatial checks and monitoring (GEO)

| TC ID | FR | Title | Preconditions | Steps | Expected result | Pri | Auto | Rel |
|---|---|---|---|---|---|---|---|---|
| TC-GEO-001-01 | FR-GEO-001 | Store polygon from coordinates | Surveyor coordinates fixture | Save | Valid polygon stored with coordinate system | P1 | Y | R1 |
| TC-GEO-001-02 | FR-GEO-001 | Invalid geometry | Self-intersecting, open ring, under 3 points, wrong coordinate order | Save | Rejected with plain message | P1 | Y | R1 |
| TC-GEO-002-01 | FR-GEO-002 | Overlay check on save | Layer fixtures v1 | Save plot | Result per layer with layer version | P1 | Y | R1 |
| TC-GEO-002-02 | FR-GEO-002 | Layer missing or job fails | Remove one layer; make worker fail | Save plot | Result marked incomplete; case manager alerted; section 7 cannot be green | P1 | Y | R1 |
| TC-GEO-003-01 | FR-GEO-003 | Inside, near, clear | Plots inside, in buffer, clear | Run checks | Correct flag per plot; section 7 verdict proposed red, amber, green | P1 | Y | R1 |
| TC-GEO-003-02 | FR-GEO-003 | Buffer boundary | Plot exactly on buffer distance and 1 m outside | Run checks | On boundary: near; 1 m outside: clear (property test on distances) | P1 | Y | R1 |
| TC-GEO-004-01 | FR-GEO-004 | Admin uploads layer version | Admin | Upload v2 | v2 active; v1 kept; past results still show v1 | P1 | Y | R1 |
| TC-GEO-004-02 | FR-GEO-004 | Bad layer file | Corrupt file; wrong projection | Upload | Rejected; active version unchanged | P1 | Y | R1 |
| TC-GEO-005-01 | FR-GEO-005 | Overlap with verified plots | Verified plot A | Save overlapping plot B | Overlap flagged with area | P2 | Y | R1 |
| TC-GEO-006-01 | FR-GEO-006 | Satellite image in report | Imagery fixture | Build report | Image with boundary in section 4 | P2 | Y | R1 |
| TC-GEO-007-01 | FR-GEO-007 | Change detection alert | Two imagery fixtures, new structure | Run schedule | Alert raised; listing follows RUL-13 | P3 | Y | R2 |
| TC-GEO-008-01 | FR-GEO-008 | GPS address conversion | Service sandbox `[TO VERIFY]` | Convert known address | Coordinates returned; unavailable service shows manual entry | P3 | P | R1 |

### 4.7 Escrow tracking (ESC)

| TC ID | FR | Title | Preconditions | Steps | Expected result | Pri | Auto | Rel |
|---|---|---|---|---|---|---|---|---|
| TC-ESC-001-01 | FR-ESC-001 | Create escrow from report | Green report; identity passed | Create | Parties, asset, price, currency, bank ref, conditions copied | P1 | Y | R1 |
| TC-ESC-001-02 | FR-ESC-001 | Invalid escrow | Missing bank ref; currency not configured; price zero | Create | Rejected | P1 | Y | R1 |
| TC-ESC-002-01 | FR-ESC-002 | All parties accept terms | Proposed escrow | Client, seller, Fidero accept | Agreed; times and terms version stored | P1 | Y | R1 |
| TC-ESC-002-02 | FR-ESC-002 | Terms changed after acceptance | One party accepted v1; terms v2 issued | Check state | Earlier acceptance void; all must accept v2 | P1 | Y | R1 |
| TC-ESC-003-01 | FR-ESC-003 | Bank payment instructions shown | Agreed escrow | Client opens pay page | Bank name, account and escrow reference from bank record | P1 | Y | R1 |
| TC-ESC-003-02 | FR-ESC-003 | Fidero details never shown | Admin edits bank record to a Fidero account number from the fee account list | Save | Rejected by deny list; alert raised | P1 | Y | R1 |
| TC-ESC-004-01 | FR-ESC-004 | Deposit by manual entry with confirmation and second-person check | Agreed escrow | Case manager A enters deposit with bank letter; staff member B checks it | Funded only after B's check; letter linked; both names audited | P1 | Y | R1 |
| TC-ESC-004-02 | FR-ESC-004 | Deposit without confirmation or wrong amount | Agreed escrow | Enter without attachment; enter amount different from price | Without attachment rejected; mismatch flagged for reviewer | P1 | Y | R1 |
| TC-ESC-004-03 | FR-ESC-004 | Second person missing or the same person | Manual entry by A | A confirms own entry; no second check | Not Funded; entry stays pending; reminder to a second staff member (01 C2: a case manager cannot confirm their own entry) | P1 | Y | R1 |
| TC-ESC-004-04 | FR-ESC-004 | Release confirmation by manual entry | Instruction sent | A enters bank release confirmation; B checks | Released after B's check; without B, stays Release approved | P1 | Y | R1 |
| TC-ESC-004-05 | FR-ESC-004 | API and file confirmations need no second person | Bank API or statement fixture | Deposit confirmed by file | Funded automatically; source recorded as file or API | P2 | Y | R2 |
| TC-ESC-005-01 | FR-ESC-005 | Close condition with evidence | Funded escrow | Attach signed indenture; close | Condition closed; closer recorded | P1 | Y | R1 |
| TC-ESC-005-02 | FR-ESC-005 | Close without evidence or by client | Funded escrow | Close with no file; client tries to close | Rejected | P1 | Y | R1 |
| TC-ESC-006-01 | FR-ESC-006 | Release allowed when clear | All closed; fresh search in date; client approved; no dispute | Request release approval | Allowed; state Client approved then Release approved | P1 | Y | R1 |
| TC-ESC-006-02 | FR-ESC-006 | Blocked by open condition | One open | Request | Blocked (TC-RUL-06-02) | P1 | Y | R1 |
| TC-ESC-006-03 | FR-ESC-006 | Blocked by dispute (from R2) | Dispute open | Request | Blocked (TC-RUL-15-01). In R1 there is no dispute module; a reviewer hold is the only freeze (see section 16) | P1 | Y | R2 |
| TC-ESC-006-04 | FR-ESC-006 | Blocked by stale or missing fresh search | Search out of date | Request | Blocked (TC-RUL-07-02, -03) | P1 | Y | R1 |
| TC-ESC-006-05 | FR-ESC-006 | Blocked without client approval | All conditions closed; client silent | Two staff try to approve | Blocked: "client has not approved" (TC-RUL-11-04) | P1 | Y | R1 |
| TC-ESC-006-06 | FR-ESC-006 | Client approval invalidated by a later change | Client approved; a condition reopened or amount changed | Request release | Blocked; client must approve again | P1 | Y | R1 |
| TC-ESC-007-01 | FR-ESC-007 | Two approvers with MFA | Ready to release | Two staff approve with MFA | Release approved | P1 | Y | R1 |
| TC-ESC-007-02 | FR-ESC-007 | Single approver, same person, no MFA | Ready to release | One approval only; same person twice; approval without step-up | Not approved in each case | P1 | Y | R1 |
| TC-ESC-008-01 | FR-ESC-008 | Instruction in bank format, signed, sent | Release approved | Generate and send | File validates against the bank format; signatures verify; sent by agreed channel; receipt logged | P1 | Y | R1 |
| TC-ESC-008-02 | FR-ESC-008 | Instruction altered after signing | Generated instruction | Change amount or account in stored file | Signature check fails; send blocked; alert | P1 | Y | R1 |
| TC-ESC-008-03 | FR-ESC-008 | Channel failure | Channel down | Send | Retry with backoff; never sent twice (idempotency key); case manager alerted | P1 | Y | R1 |
| TC-ESC-009-01 | FR-ESC-009 | Bank confirmation shown to parties | Instruction sent | Record bank confirmation | Released; all parties see it and are notified | P1 | Y | R1 |
| TC-ESC-009-02 | FR-ESC-009 | Confirmation mismatch | Confirmation amount or reference differs | Record | Flagged; state not Released until reviewer resolves | P1 | Y | R1 |
| TC-ESC-010-01 | FR-ESC-010 | Partial release per milestone | Construction escrow with milestones | Release milestone 1 | Partial instruction; balance updated; escrow stays open | P1 | Y | R2 |
| TC-ESC-010-02 | FR-ESC-010 | Partial releases exceed held amount | Remaining balance less than request | Request | Blocked; sum of releases never exceeds confirmed deposits (property test) | P1 | Y | R2 |
| TC-ESC-011-01 | FR-ESC-011 | Statement file import and match | Statement fixtures | Import | Matches linked; unmatched listed | P2 | Y | R2 |
| TC-ESC-011-02 | FR-ESC-011 | Bad, duplicate and ambiguous lines | Fixture set in 2.7 | Import | Bad file rejected; duplicates ignored; ambiguous lines go to manual match, never auto-matched | P2 | Y | R2 |
| TC-ESC-012-01 | FR-ESC-012 | Bank API status | Bank sandbox `[TO VERIFY]` | Poll or receive callback | Deposit and release status updated; signature on callback verified | P3 | Y | R2 |
| TC-ESC-013-01 | FR-ESC-013 | Cancellation with two-person approval | Funded escrow | Two staff approve cancel and refund | Cancellation instruction sent; Cancelled after bank refund confirmation | P1 | Y | R1 |
| TC-ESC-013-02 | FR-ESC-013 | Cancellation by one person or by client | Funded escrow | One approval; client request | Not sent | P1 | Y | R1 |

### 4.8 Evidence store (EVD)

| TC ID | FR | Title | Preconditions | Steps | Expected result | Pri | Auto | Rel |
|---|---|---|---|---|---|---|---|---|
| TC-EVD-001-01 | FR-EVD-001 | Metadata stored with each file | Upload to case | Upload photo with EXIF position | Hash, uploader, device, capture time, server time, position and link stored; hash matches file | P1 | Y | R1 |
| TC-EVD-001-02 | FR-EVD-001 | Upload not linked to an owner object | API client | Upload with no case, project or listing; link to an object the user cannot access | Rejected | P1 | Y | R1 |
| TC-EVD-002-01 | FR-EVD-002 | Same name upload creates a new item | Existing evidence | Upload file with same name | New item; old item unchanged and visible in history | P1 | Y | R1 |
| TC-EVD-002-02 | FR-EVD-002 | Overwrite and delete attempts | Existing evidence | Call delete API; try object storage put on the same key with app credentials | API refuses; storage versioning and object lock keep the original; attempt logged | P1 | Y | R1 |
| TC-EVD-002-03 | FR-EVD-002 | Retention deletion is logged | Item past retention, no hold | Run retention job | Deleted or anonymised; audit entry with rule and time | P1 | Y | R1 |
| TC-EVD-003-01 | FR-EVD-003 | Signed link works | Authorised user | Open evidence | Signed link with expiry at most 15 minutes | P1 | Y | R1 |
| TC-EVD-003-02 | FR-EVD-003 | Expired, altered or shared link | Link issued | Use after 15 minutes; change object key; use from another account | Refused each time; bucket has no public access | P1 | Y | R1 |
| TC-EVD-004-01 | FR-EVD-004 | Previews created | Upload 8 MB photo and 60 s video | Wait for job | Small image preview and compressed video preview served by default | P1 | Y | R1 |
| TC-EVD-004-02 | FR-EVD-004 | Preview failure does not lose original | Corrupt video | Upload | Original kept; preview marked failed; alert | P1 | Y | R1 |
| TC-EVD-005-01 | FR-EVD-005 | Clean file accepted | Clean PDF | Upload | Scanned and accepted | P1 | Y | R1 |
| TC-EVD-005-02 | FR-EVD-005 | Malware and disguised files rejected | EICAR test file; executable renamed .jpg; PDF with script | Upload | Rejected; not served; logged | P1 | Y | R1 |
| TC-EVD-006-01 | FR-EVD-006 | App-captured marking | App submission with valid signature | Upload | Marked app-captured | P1 | Y | R2 |
| TC-EVD-006-02 | FR-EVD-006 | Uploaded file cannot claim app-captured | Web upload with forged "app-captured" field | Upload | Marked uploaded; field ignored | P1 | Y | R2 |

### 4.9 Milestone app (MOB)

| TC ID | FR | Title | Preconditions | Steps | Expected result | Pri | Auto | Rel |
|---|---|---|---|---|---|---|---|---|
| TC-MOB-001-01 | FR-MOB-001 | Sign in and see assigned work | Contractor with two projects | Sign in | Only those two projects shown | P1 | Y | R2 |
| TC-MOB-001-02 | FR-MOB-001 | Unassigned project | Contractor | Deep link to another project | Not shown; API 404 | P1 | Y | R2 |
| TC-MOB-002-01 | FR-MOB-002 | In-app camera capture | Milestone open | Capture photo and video | Items attached | P1 | Y | R2 |
| TC-MOB-002-02 | FR-MOB-002 | Gallery and file uploads blocked | Milestone open | Look for gallery or file picker; share an image into the app | None available; share rejected (TC-RUL-08-02) | P1 | Y | R2 |
| TC-MOB-003-01 | FR-MOB-003 | GPS recorded; no warning on site | Mock location inside plot | Capture | Position and accuracy stored; no warning | P1 | Y | R2 |
| TC-MOB-003-02 | FR-MOB-003 | Warning off site or with poor accuracy | Mock location 500 m away; accuracy 200 m | Capture | Warning shown; position recorded; server flag (TC-MOB-011-02) | P1 | Y | R2 |
| TC-MOB-004-01 | FR-MOB-004 | Hash and signature at capture | Device key enrolled | Capture | Hash, position and device time signed with keystore key; server verifies | P1 | Y | R2 |
| TC-MOB-004-02 | FR-MOB-004 | File changed after capture | Captured item | Modify file in app storage before upload (debug build) | Server hash mismatch; rejected and flagged | P1 | P | R2 |
| TC-MOB-005-01 | FR-MOB-005 | Offline capture and later upload | Airplane mode | Capture, fill checklist, submit; reconnect | Queued; uploaded once on reconnect; server confirms | P1 | Y | R2 |
| TC-MOB-005-02 | FR-MOB-005 | Queue survives app kill and reboot | Queue with 10 items | Force stop; reboot phone; reopen | All items still queued and upload once | P1 | Y | R2 |
| TC-MOB-005-03 | FR-MOB-005 | Connection drops mid-upload | Throttled network with drops | Upload 30 items | Resumes; no duplicates; no lost items | P1 | Y | R2 |
| TC-MOB-006-01 | FR-MOB-006 | Required evidence list | Foundation milestone | Open milestone | List matches milestone schedule; submit enabled when complete | P1 | Y | R2 |
| TC-MOB-006-02 | FR-MOB-006 | Submission blocked when incomplete | One item missing | Submit in app; call API directly | Both blocked | P1 | Y | R2 |
| TC-MOB-007-01 | FR-MOB-007 | Inspector records pass with defects | Inspector assigned | Complete checklist; add 2 defects with photos and values | Outcome stored with defect values | P1 | Y | R2 |
| TC-MOB-007-02 | FR-MOB-007 | Incomplete checklist or defect without value | Inspector assigned | Submit with unticked items; defect with no value or photo | Blocked | P1 | Y | R2 |
| TC-MOB-008-01 | FR-MOB-008 | Compression and caps | Capture 12 MP photo and long video | Capture | Photo compressed to configured size; video stops at cap; original kept until server confirms | P1 | Y | R2 |
| TC-MOB-008-02 | FR-MOB-008 | Original not deleted before confirmation | Upload fails after send | Check device | Original still on device | P1 | Y | R2 |
| TC-MOB-009-01 | FR-MOB-009 | Device storage encrypted and cleared | Items queued | Inspect app storage on rooted test device; upload | Files unreadable without key; removed after server confirmation | P1 | P | R2 |
| TC-MOB-009-02 | FR-MOB-009 | No evidence in shared storage or backups | Items queued | Check shared media folders and Android backup | No evidence files present; backup excludes evidence | P1 | P | R2 |
| TC-MOB-010-01 | FR-MOB-010 | Runner captures case evidence | Runner with site visit task | Capture photos for task | Linked to case task as app-captured | P2 | Y | R2 |
| TC-MOB-011-01 | FR-MOB-011 | Clean submission passes server checks | Valid submission | Upload | Signature verified; server time stored; no flags | P1 | Y | R2 |
| TC-MOB-011-02 | FR-MOB-011 | Each fraud flag raised | Fixtures: outside buffer; clock gap; capture before previous pass; hash reused on another project; metadata mismatch | Upload each | Matching flag raised; submission routed to reviewer | P1 | Y | R2 |

### 4.10 Construction, off-plan and buildings (BLD)

| TC ID | FR | Title | Preconditions | Steps | Expected result | Pri | Auto | Rel |
|---|---|---|---|---|---|---|---|---|
| TC-BLD-001-01 | FR-BLD-001 | Project on verified plot | Green report on plot | Create project | Project created and linked | P1 | Y | R2 |
| TC-BLD-001-02 | FR-BLD-001 | Unverified or red plot | No report, or red report | Create project | Blocked | P1 | Y | R2 |
| TC-BLD-002-01 | FR-BLD-002 | Bill of quantities and split | Quantity surveyor assigned | Upload BoQ; set split | Milestones created; shares sum to 100% | P1 | Y | R2 |
| TC-BLD-002-02 | FR-BLD-002 | Split not 100% or by wrong role | QS or contractor | Set split to 95%; contractor tries to set split | Rejected | P1 | Y | R2 |
| TC-BLD-003-01 | FR-BLD-003 | Panel with documents and status | Admin | Add contractor with documents | On panel; status vetted after checks | P1 | Y | R2 |
| TC-BLD-003-02 | FR-BLD-003 | Unvetted contractor not selectable | Contractor pending | Client chooses contractor | Not offered | P1 | Y | R2 |
| TC-BLD-004-01 | FR-BLD-004 | Unconflicted inspector assigned | No links | Assign | Allowed (TC-RUL-10-01) | P1 | Y | R2 |
| TC-BLD-004-02 | FR-BLD-004 | Conflicted inspector blocked | Recorded link | Assign | Blocked (TC-RUL-10-02) | P1 | Y | R2 |
| TC-BLD-005-01 | FR-BLD-005 | Milestone route in order | Submitted milestone | Walk each step | Each state reached in order; each change audited | P1 | Y | R2 |
| TC-BLD-005-02 | FR-BLD-005 | Skip a step | Submitted milestone | Call client-approve or release-approve before inspection | Rejected (see section 5.3) | P1 | Y | R2 |
| TC-BLD-006-01 | FR-BLD-006 | Defect value held then released | Pass with defects | Release; close defect with evidence; inspector confirms | Held value released after closure | P1 | Y | R2 |
| TC-BLD-006-02 | FR-BLD-006 | Defect closed without evidence | Open defect | Close without evidence | Rejected; value stays held | P1 | Y | R2 |
| TC-BLD-007-01 | FR-BLD-007 | Re-price and show change | Rate changed | Open approval | Change shown (TC-RUL-18-01) | P1 | Y | R2 |
| TC-BLD-007-02 | FR-BLD-007 | Release without re-pricing | Re-pricing missing | Approve | Blocked (TC-RUL-18-02) | P1 | Y | R2 |
| TC-BLD-008-01 | FR-BLD-008 | Variation agreed before work | Active project | Agree variation | Recorded (TC-RUL-19-01) | P1 | Y | R2 |
| TC-BLD-008-02 | FR-BLD-008 | Work before agreement | Unagreed variation | Submit | Flagged (TC-RUL-19-02) | P1 | Y | R2 |
| TC-BLD-009-01 | FR-BLD-009 | Build dashboard | Project with 2 paid milestones | Open dashboard | Budget vs actual, status, photo timeline, inspector results, payments correct | P1 | Y | R2 |
| TC-BLD-009-02 | FR-BLD-009 | Dashboard for other client | Client B | Open client A's dashboard | 404 | P1 | Y | R2 |
| TC-BLD-010-01 | FR-BLD-010 | Contractor removed after confirmed fraud | Fraud flag confirmed by reviewer | Confirm | Contractor removed from panel; all their releases frozen; clients notified | P1 | Y | R2 |
| TC-BLD-010-02 | FR-BLD-010 | No removal without reviewer | Flag raised, not confirmed | Case manager tries removal | Blocked | P1 | Y | R2 |
| TC-BLD-011-01 | FR-BLD-011 | Off-plan stage release | Developer verified; stage payments held | Stage evidence and inspector pass | Stage released | P2 | Y | R2 |
| TC-BLD-011-02 | FR-BLD-011 | Unverified developer | Developer title not verified | Open off-plan escrow | Blocked | P2 | Y | R2 |
| TC-BLD-012-01 | FR-BLD-012 | Retention released after defects period | Handover done; period ended; inspector confirms none open | Release retention | Allowed | P1 | Y | R2 |
| TC-BLD-012-02 | FR-BLD-012 | Retention early or with open defects | Period not ended, or a defect open | Release retention | Blocked | P1 | Y | R2 |
| TC-BLD-013-01 | FR-BLD-013 | Materials order paid through bank | Held funds | Order materials | Supplier paid by bank instruction; delivery shown | P3 | Y | R3 |

### 4.11 Project funds (PRJ)

| TC ID | FR | Title | Preconditions | Steps | Expected result | Pri | Auto | Rel |
|---|---|---|---|---|---|---|---|---|
| TC-PRJ-001-01 | FR-PRJ-001 | Create project | Signed-in client | Enter budget, stages, runner, suppliers | Project created | P2 | Y | R2 |
| TC-PRJ-002-01 | FR-PRJ-002 | Checks before bank accepts money | Project created | Run checks on runner and suppliers | Escrow cannot be agreed until all pass | P2 | Y | R2 |
| TC-PRJ-002-02 | FR-PRJ-002 | Failed supplier check | Supplier fails | Proceed | Supplier blocked; client told to replace | P2 | Y | R2 |
| TC-PRJ-003-01 | FR-PRJ-003 | Release to supplier against invoice | Stage confirmed | Release | Allowed (TC-RUL-21-01) | P2 | Y | R2 |
| TC-PRJ-003-02 | FR-PRJ-003 | Release to runner or without invoice | As in TC-RUL-21-02, -03 | Release | Blocked | P2 | Y | R2 |
| TC-PRJ-004-01 | FR-PRJ-004 | Enhanced checks above threshold | Threshold configured `[TO VERIFY]` | Create project one unit above and one below | Above: enhanced checks required; below: standard | P2 | Y | R2 |
| TC-PRJ-005-01 | FR-PRJ-005 | No-advice statement in agreement | Project agreement | Generate | Statement present in every agreement version | P1 | Y | R2 |
| TC-PRJ-005-02 | FR-PRJ-005 | Statement cannot be removed | Admin edits agreement template | Remove statement | Template publish rejected | P1 | Y | R2 |

### 4.12 Verified listings (LST)

| TC ID | FR | Title | Preconditions | Steps | Expected result | Pri | Auto | Rel |
|---|---|---|---|---|---|---|---|---|
| TC-LST-001-01 | FR-LST-001 | Submit listing and pay fee | Developer | Submit plot; pay | In verification | P2 | Y | R2 |
| TC-LST-002-01 | FR-LST-002 | Publish with green in-date report | Green, in date | Publish | Live (TC-RUL-12-01) | P1 | Y | R2 |
| TC-LST-002-02 | FR-LST-002 | Not green or out of date | Amber or old report | Publish | Rejected (TC-RUL-12-02, -03) | P1 | Y | R2 |
| TC-LST-003-01 | FR-LST-003 | Badge, date and report link | Live listing | View | Badge, check date and working report link shown | P1 | Y | R2 |
| TC-LST-003-02 | FR-LST-003 | Badge not shown when not live | Suspended or expired listing | View | No badge | P1 | Y | R2 |
| TC-LST-004-01 | FR-LST-004 | Search, filter and map | 500 listing fixtures | Filter by region, price, size, type, date; open map | Correct results; map pins match | P2 | Y | R2 |
| TC-LST-005-01 | FR-LST-005 | Reserve starts fresh search and escrow | Live listing | Buyer reserves | Reserved; fresh-search case and proposed escrow created | P2 | Y | R2 |
| TC-LST-005-02 | FR-LST-005 | Double reservation | Reserved listing | Second buyer reserves | Rejected; offered waiting list or enquiry | P2 | Y | R2 |
| TC-LST-006-01 | FR-LST-006 | Expiry and suspension | Live listing | Pass validity; raise alert | Expired; suspended (TC-RUL-13-01, -02) | P1 | Y | R2 |
| TC-LST-006-02 | FR-LST-006 | Seller cannot extend badge | Seller | Edit expiry via API | 403 | P1 | Y | R2 |
| TC-LST-007-01 | FR-LST-007 | Sold on release and fee invoiced | Reserved; escrow released | Bank confirms | Sold; success fee invoice issued | P2 | Y | R2 |
| TC-LST-008-01 | FR-LST-008 | Reviewer removes listing and seller | Misconduct case | Remove with reason | Listing and seller's other listings removed; reason audited | P1 | Y | R2 |
| TC-LST-008-02 | FR-LST-008 | Removal without reason or by non-reviewer | Case manager | Remove | Rejected | P1 | Y | R2 |
| TC-LST-009-01 | FR-LST-009 | Family or stool listing from records | Records module data | List plot | Listing created and follows RUL-12 | P3 | Y | R3 |
| TC-LST-010-01 | FR-LST-010 | Indexable and fast on 3G | Live listing | Lighthouse SEO audit; Playwright 3G timing | Indexable; under 3 s at p75 (NFR-PERF-01 profile) | P2 | Y | R2 |
| TC-LST-010-02 | FR-LST-010 | Non-live listings not indexed | Draft, suspended, sold | Fetch as crawler | noindex or 404 | P2 | Y | R2 |

### 4.13 Track records and ratings (RAT)

| TC ID | FR | Title | Preconditions | Steps | Expected result | Pri | Auto | Rel |
|---|---|---|---|---|---|---|---|---|
| TC-RAT-001-01 | FR-RAT-001 | Track record computed | Contractor with deals, milestones, disputes | Run job | Figures match fixture totals | P2 | Y | R2 |
| TC-RAT-002-01 | FR-RAT-002 | Client rates completed item | Completed milestone | Rate 4 with comment | Stored | P2 | Y | R2 |
| TC-RAT-002-02 | FR-RAT-002 | Invalid ratings | Incomplete item; score 0 or 6; second rating | Submit | Rejected | P2 | Y | R2 |
| TC-RAT-003-01 | FR-RAT-003 | Shown on listings and contractor choice | Track records exist | View listing; choose contractor | Track record shown | P2 | Y | R2 |
| TC-RAT-004-01 | FR-RAT-004 | Hide abusive comment | Reviewer | Hide with reason | Comment hidden; score unchanged; audited | P2 | Y | R2 |

### 4.14 Disputes (DSP)

| TC ID | FR | Title | Preconditions | Steps | Expected result | Pri | Auto | Rel |
|---|---|---|---|---|---|---|---|---|
| TC-DSP-001-01 | FR-DSP-001 | Party opens dispute | Seller on escrow | Open with reason and evidence | Dispute Open; other parties notified | P1 | Y | R2 |
| TC-DSP-001-02 | FR-DSP-001 | Non-party or no reason | Unrelated client; no reason | Open | Rejected | P1 | Y | R2 |
| TC-DSP-002-01 | FR-DSP-002 | Linked releases frozen | Escrow and milestone | Open dispute | All linked releases frozen (TC-RUL-15-01) | P1 | Y | R2 |
| TC-DSP-002-02 | FR-DSP-002 | Release attempt during freeze | Frozen | Approve or send | Blocked (TC-RUL-15-02) | P1 | Y | R2 |
| TC-DSP-003-01 | FR-DSP-003 | Deadlines set in working days | Dispute opened on a Friday before a public holiday | Check deadlines | 5, 10 and 10 working days counted with weekends and holidays skipped | P1 | Y | R2 |
| TC-DSP-003-02 | FR-DSP-003 | Missed deadline moves state | Response deadline passes | Run job | Moves to Evidence; parties notified | P1 | Y | R2 |
| TC-DSP-004-01 | FR-DSP-004 | Decision recorded and notified | Dispute in Decision | Reviewer decides | Decision, reasons, decider stored; all notified | P1 | Y | R2 |
| TC-DSP-004-02 | FR-DSP-004 | Decision by conflicted person | Reviewer is a party or approved the disputed release | Decide | Blocked | P1 | Y | R2 |
| TC-DSP-005-01 | FR-DSP-005 | Refer to mediation | Open dispute | Refer; record outcome | Referred then Closed with outcome | P2 | Y | R2 |

### 4.15 Partner API (PTR)

| TC ID | FR | Title | Preconditions | Steps | Expected result | Pri | Auto | Rel |
|---|---|---|---|---|---|---|---|---|
| TC-PTR-001-01 | FR-PTR-001 | Status by reference or coordinates | Authenticated partner | Query plots with no report, in progress, released | Correct status each time | P2 | Y | R2 |
| TC-PTR-001-02 | FR-PTR-001 | Unauthenticated or revoked key | No key; revoked key | Query | 401 | P2 | Y | R2 |
| TC-PTR-002-01 | FR-PTR-002 | Verdict and full report with consent | Consents on file | Query | Verdict and date; full report only with specific consent | P1 | Y | R2 |
| TC-PTR-002-02 | FR-PTR-002 | No consent | No consent for this partner | Query | No verdict, no report (TC-RUL-16-02) | P1 | Y | R2 |
| TC-PTR-003-01 | FR-PTR-003 | Partner orders for consenting client | Client consent | Order | Order created; client confirms in portal | P3 | Y | R2 |
| TC-PTR-004-01 | FR-PTR-004 | Metering and rate limits | Partner limit configured | Exceed limit | 429 after limit; calls metered per partner | P2 | Y | R2 |

### 4.16 Notifications and messaging (NTF)

| TC ID | FR | Title | Preconditions | Steps | Expected result | Pri | Auto | Rel |
|---|---|---|---|---|---|---|---|---|
| TC-NTF-001-01 | FR-NTF-001 | Notifications by preference | Client prefers WhatsApp | Trigger status change | Sent on WhatsApp; email per preference | P1 | Y | R1 |
| TC-NTF-001-02 | FR-NTF-001 | Channel failure fallback | WhatsApp provider fails | Trigger | Falls back to next channel; failure logged | P1 | Y | R1 |
| TC-NTF-002-01 | FR-NTF-002 | Editable templates | Admin edits template | Trigger | New text used; version stored | P1 | Y | R1 |
| TC-NTF-002-02 | FR-NTF-002 | Broken template | Unknown placeholder | Save template | Rejected with error | P1 | Y | R1 |
| TC-NTF-003-01 | FR-NTF-003 | Reminder 2 working days before due | Task due Tuesday | Run scheduler Friday | Reminder sent | P1 | Y | R1 |
| TC-NTF-003-02 | FR-NTF-003 | Overdue alert and no duplicate reminders | Task overdue | Run scheduler twice | One overdue alert to case manager | P1 | Y | R1 |
| TC-NTF-004-01 | FR-NTF-004 | SMS and WhatsApp carry only safe content | Status change with verdict and escrow amount | Inspect message | No verdict, findings, amount above threshold or third-party data; link to portal only | P1 | Y | R1 |
| TC-NTF-004-02 | FR-NTF-004 | Template that leaks content | Admin adds report verdict placeholder to an SMS template | Save | Rejected by placeholder allow list per channel | P1 | Y | R1 |
| TC-NTF-005-01 | FR-NTF-005 | Notification log | Sends done | Open log | Each send with channel and delivery status | P2 | Y | R1 |

### 4.17 Administration (ADM)

| TC ID | FR | Title | Preconditions | Steps | Expected result | Pri | Auto | Rel |
|---|---|---|---|---|---|---|---|---|
| TC-ADM-001-01 | FR-ADM-001 | Versioned templates and schedules | Admin | Publish new case template and milestone schedule | New version active for new items; history kept | P1 | Y | R1 |
| TC-ADM-001-02 | FR-ADM-001 | Edit a published version | Admin | Edit v1 in place | Rejected; must create v2 | P1 | Y | R1 |
| TC-ADM-002-01 | FR-ADM-002 | Prices, tiers, currencies, rate guides | Admin | Change diaspora price; add rate guide | New orders use new price; open orders unchanged | P1 | Y | R1 |
| TC-ADM-002-02 | FR-ADM-002 | Invalid price or rate | Admin | Negative price; zero rate | Rejected | P1 | Y | R1 |
| TC-ADM-003-01 | FR-ADM-003 | Manage partners | Admin | Add bank, supplier, API partner | Created with status | P1 | Y | R1 |
| TC-ADM-003-02 | FR-ADM-003 | Bank account change on partner | Admin | Change bank account details | Needs second admin approval `[TO VERIFY]`; audited (see section 16) | P1 | Y | R1 |
| TC-ADM-004-01 | FR-ADM-004 | Scope change with two admins and approvals | Lawyer and insurer approvals uploaded | Admin A proposes; admin B approves | New version active for new reports only | P1 | Y | R1 |
| TC-ADM-004-02 | FR-ADM-004 | Scope change by one admin or without approvals | Admin | Approve own change; omit insurer approval | Rejected | P1 | Y | R1 |
| TC-ADM-005-01 | FR-ADM-005 | Configurable values | Admin | Set fresh-search window, badge validity, buffers, deadlines | Values used by rules; change audited | P1 | Y | R1 |
| TC-ADM-005-02 | FR-ADM-005 | Unsafe values | Admin | Set window to 0 or negative; buffer above maximum | Rejected with allowed range | P1 | Y | R1 |

### 4.18 Audit (AUD)

| TC ID | FR | Title | Preconditions | Steps | Expected result | Pri | Auto | Rel |
|---|---|---|---|---|---|---|---|---|
| TC-AUD-001-01 | FR-AUD-001 | Every action logged | Seeded actions | Create, change, approve, release, export, sign in | One entry each with who, when, what, from where | P1 | Y | R1 |
| TC-AUD-001-02 | FR-AUD-001 | Audit write failure blocks action | Audit store unavailable | Approve release | Action fails safe; nothing changes without its audit entry | P1 | Y | R1 |
| TC-AUD-002-01 | FR-AUD-002 | Admin cannot edit or delete | Admin | Try UI and API | No function exists; API 405 | P1 | Y | R1 |
| TC-AUD-002-02 | FR-AUD-002 | Database role cannot update or delete | Application database role | Run UPDATE and DELETE on audit table | Permission denied | P1 | Y | R1 |
| TC-AUD-003-01 | FR-AUD-003 | Search audit log | Reviewer | Search by case, user, date, action | Correct results | P2 | Y | R1 |
| TC-AUD-004-01 | FR-AUD-004 | Hash chain verifies | Seeded log | Run verifier | Chain valid | P2 | Y | R1 |
| TC-AUD-004-02 | FR-AUD-004 | Tampering detected | Superuser edits one entry in a test copy | Run verifier | Break detected at that entry; alert raised | P2 | Y | R1 |

### 4.19 Analytics and reporting (ANL)

| TC ID | FR | Title | Preconditions | Steps | Expected result | Pri | Auto | Rel |
|---|---|---|---|---|---|---|---|---|
| TC-ANL-001-01 | FR-ANL-001 | Dashboard metrics and filters | `seed-r1` | Open dashboard; filter by date, country, line, tier | Each A9 metric matches a hand-computed fixture value | P2 | Y | R1 |
| TC-ANL-002-01 | FR-ANL-002 | CSV export logged | Reviewer | Export | CSV matches dashboard; export audited | P2 | Y | R1 |
| TC-ANL-003-01 | FR-ANL-003 | Role-limited dashboard | Case manager | Open dashboard | Aggregates only; no client names unless role allows | P1 | Y | R1 |
| TC-ANL-003-02 | FR-ANL-003 | Small-number re-identification | Filter to one client | Open | Values for groups under a minimum size suppressed `[TO VERIFY]` size | P1 | Y | R1 |

### 4.20 Data protection and retention (DPR)

| TC ID | FR | Title | Preconditions | Steps | Expected result | Pri | Auto | Rel |
|---|---|---|---|---|---|---|---|---|
| TC-DPR-001-01 | FR-DPR-001 | Privacy notice at sign-up | New user | Sign up | Notice shown; acceptance with version stored | P1 | Y | R1 |
| TC-DPR-001-02 | FR-DPR-001 | Sign-up without acceptance; new version | New user; notice v2 published | Skip; sign in after v2 | Sign-up blocked; v2 acceptance requested | P1 | Y | R1 |
| TC-DPR-002-01 | FR-DPR-002 | Consent linked to video | Consent video uploaded | Record consents for 3 people | Each consent linked to the recording | P1 | Y | R1 |
| TC-DPR-002-02 | FR-DPR-002 | Video without consent | Video uploaded | Close consent task without consents | Blocked | P1 | Y | R1 |
| TC-DPR-003-01 | FR-DPR-003 | Access and correction requests | Admin | Export person's data; correct phone | Export complete; correction applied; request logged | P1 | Y | R1 |
| TC-DPR-003-02 | FR-DPR-003 | Export leaks other people's data | Person on a case with others | Export | Only that person's data; third parties redacted | P1 | Y | R1 |
| TC-DPR-004-01 | FR-DPR-004 | Retention applied | Items past period | Run job | Deleted or anonymised per class | P1 | Y | R1 |
| TC-DPR-004-02 | FR-DPR-004 | Legal hold respected | Item past period with hold | Run job | Kept; hold reason logged | P1 | Y | R1 |
| TC-DPR-005-01 | FR-DPR-005 | Bulk export with two approvals | Admins A and B | A requests; B approves | Export produced, logged, link expires | P1 | Y | R1 |
| TC-DPR-005-02 | FR-DPR-005 | Single-person bulk export | Admin A | Approve own request; use CSV export to pull all clients | Blocked; ANL export cannot exceed role or size limit | P1 | Y | R1 |

### 4.21 Records programme (REC)

| TC ID | FR | Title | Preconditions | Steps | Expected result | Pri | Auto | Rel |
|---|---|---|---|---|---|---|---|---|
| TC-REC-001-01 | FR-REC-001 | Capture allocation records | Authority records fixture | Capture plots with boundaries, allottees, dates, documents | Stored and searchable | P2 | Y | R3 |
| TC-REC-002-01 | FR-REC-002 | Match and pre-fill chain | Matching record | Create case | Chain pre-filled and marked as from records; lawyer must confirm | P2 | Y | R3 |
| TC-REC-002-02 | FR-REC-002 | Near match | Plot overlaps record partly | Create case | Flag for review; no automatic pre-fill | P2 | Y | R3 |
| TC-REC-003-01 | FR-REC-003 | Revenue share | Cases used records | Run calculation | Share per authority correct | P2 | Y | R3 |
| TC-REC-004-01 | FR-REC-004 | Authority representative views own records | Representative | View and confirm | Only own authority's records visible | P2 | Y | R3 |

### 4.22 Multi-country (CTY)

| TC ID | FR | Title | Preconditions | Steps | Expected result | Pri | Auto | Rel |
|---|---|---|---|---|---|---|---|---|
| TC-CTY-001-01 | FR-CTY-001 | Country as configuration | Nigeria configuration in staging | Create Nigerian case | Nigerian template, scope, layers, NGN, partners and licence bodies used; no code change | P1 | Y | R3 |
| TC-CTY-001-02 | FR-CTY-001 | Mixing countries | Ghana case | Use Nigerian scope text or licence body | Rejected | P1 | Y | R3 |
| TC-CTY-002-01 | FR-CTY-002 | Data location per country | Data location rules `[TO VERIFY]` | Create Nigerian case with evidence | Stored in required location; data location register updated | P1 | P | R3 |
| TC-CTY-002-02 | FR-CTY-002 | No cross-country leakage | Nigerian evidence | Check backups, logs, analytics stores | No copy outside allowed locations | P1 | P | R3 |
| TC-CTY-003-01 | FR-CTY-003 | Metrics by country | Two countries seeded | Open dashboard | Every metric splits by country | P1 | Y | R3 |
| TC-CTY-003-02 | FR-CTY-003 | Currency not mixed | GHS and NGN orders | View revenue metric | Shown per currency or converted with stated rate; never summed raw | P1 | Y | R3 |

---

## 5. State-transition tests

### 5.1 Approach

Each state model in 01 C8 is coded as one transition table. Two kinds of test run against it:

1. **Matrix test (automated, every PR).** A generated test walks every pair of states (from, to). Pairs listed in 01 C8 must succeed when their trigger is met and fail when it is not. Every other pair must be rejected with an error, leave the state unchanged and write an audit entry for the attempt. This catches any transition added in code but not in the specification.
2. **Named tests (below).** Each valid transition and the riskiest invalid ones have a named test that checks the trigger, side effects (notifications, audit, linked records) and the client-facing status message.

Concurrency: every money-moving transition is also tested with two parallel requests. Exactly one may succeed.

### 5.2 Case

| ID | From | To | Valid | Steps | Expected result | Auto | Rel |
|---|---|---|---|---|---|---|---|
| TC-STM-CASE-01 | Draft | Paid | Yes | Payment confirmed webhook | Paid; receipt issued | Y | R1 |
| TC-STM-CASE-02 | Paid | In progress | Yes | Case manager accepts | In progress; tasks created | Y | R1 |
| TC-STM-CASE-03 | In progress | On hold | Yes | Pause with reason | On hold; client status shows reason | Y | R1 |
| TC-STM-CASE-04 | On hold | In progress | Yes | Clear blocker | In progress; due dates recalculated or kept as configured | Y | R1 |
| TC-STM-CASE-05 | In progress | In review | Yes | All tasks done; report drafted | In review | Y | R1 |
| TC-STM-CASE-06 | In review | In progress | Yes | Reviewer returns with comments | In progress; comments stored; approvals cleared | Y | R1 |
| TC-STM-CASE-07 | In review | Released | Yes | Lawyer and different reviewer approve | Released; PDF and hash stored | Y | R1 |
| TC-STM-CASE-08 | Draft, Paid, In progress, On hold, In review | Cancelled | Yes | Cancel with reason and refund decision, from each state | Cancelled; refund flow started where decided | Y | R1 |
| TC-STM-CASE-09 | Draft | In progress | No | Accept unpaid case | Rejected | Y | R1 |
| TC-STM-CASE-10 | In progress | In review | No (trigger missing) | Move with one task open | Rejected | Y | R1 |
| TC-STM-CASE-11 | In progress, On hold | Released | No | Call release | Rejected | Y | R1 |
| TC-STM-CASE-12 | In review | Released | No (trigger missing) | One approval only, or same person twice | Rejected | Y | R1 |
| TC-STM-CASE-13 | Released | Any | No | Cancel, reopen or edit | Rejected; corrections only via new report version | Y | R1 |
| TC-STM-CASE-14 | Cancelled | Any | No | Reopen | Rejected | Y | R1 |
| TC-STM-CASE-15 | In review | Released | Race | Two final approvals in parallel | One release, one PDF, one hash | Y | R1 |

### 5.3 Escrow

| ID | From | To | Valid | Steps | Expected result | Auto | Rel |
|---|---|---|---|---|---|---|---|
| TC-STM-ESC-01 | Proposed | Agreed | Yes | All parties accept current terms | Agreed | Y | R1 |
| TC-STM-ESC-02 | Agreed | Funded | Yes | Bank deposit confirmation recorded | Funded | Y | R1 |
| TC-STM-ESC-03 | Funded | Ready to release | Yes | Last condition closed; fresh search in date | Ready to release | Y | R1 |
| TC-STM-ESC-04 | Ready to release | Release approved | Yes | Two different staff approve with MFA | Release approved; instruction generated | Y | R1 |
| TC-STM-ESC-05 | Release approved | Released | Yes | Bank confirms payment | Released; parties notified | Y | R1 |
| TC-STM-ESC-06 | Funded | Frozen | Yes | Dispute opened | Frozen | Y | R1 |
| TC-STM-ESC-07 | Ready to release | Frozen | Yes | Dispute opened | Frozen; any partial approval cleared | Y | R1 |
| TC-STM-ESC-08 | Frozen | Funded | Yes | Dispute resolved | Funded; conditions and fresh search re-checked before Ready | Y | R2 |
| TC-STM-ESC-09 | Agreed | Cancelled | Yes | Two-person approved cancellation | Cancelled (no money held) | Y | R1 |
| TC-STM-ESC-10 | Funded | Cancelled | Yes | Two-person cancellation; bank confirms refund | Cancelled only after bank refund confirmation | Y | R1 |
| TC-STM-ESC-11 | Proposed | Funded | No | Record deposit before agreement | Rejected; deposit held as unmatched for review | Y | R1 |
| TC-STM-ESC-12 | Agreed | Ready to release | No | Close all conditions before funding | Stays Agreed | Y | R1 |
| TC-STM-ESC-13 | Funded | Release approved | No | Approve with open condition | Rejected | Y | R1 |
| TC-STM-ESC-14 | Frozen | Release approved, Released | No | Approve or confirm release while frozen | Rejected | Y | R2 |
| TC-STM-ESC-15 | Released | Any | No | Cancel, freeze or approve again | Rejected | Y | R1 |
| TC-STM-ESC-16 | Cancelled | Any | No | Fund or release | Rejected | Y | R1 |
| TC-STM-ESC-17 | Release approved | Frozen | Not in C8 | Dispute opened after approvals, before bank confirms | Behaviour per resolution of section 16 item; test expects send blocked and state Frozen | Y | R2 |
| TC-STM-ESC-18 | Ready to release | Release approved | Race | Two second-approvals in parallel | One instruction only | Y | R1 |
| TC-STM-ESC-19 | Release approved | Released | Race | Bank confirmation received twice | Recorded once; duplicate logged | Y | R1 |

### 5.4 Milestone

| ID | From | To | Valid | Steps | Expected result | Auto | Rel |
|---|---|---|---|---|---|---|---|
| TC-STM-MIL-01 | Not started | Submitted | Yes | Contractor submits complete evidence | Submitted | Y | R2 |
| TC-STM-MIL-02 | Submitted | Evidence checked | Yes | No flags; Fidero accepts | Evidence checked | Y | R2 |
| TC-STM-MIL-03 | Submitted | Evidence checked | Yes | Flags present; reviewer clears each | Evidence checked; reviewer recorded | Y | R2 |
| TC-STM-MIL-04 | Submitted | Returned | Yes | Evidence incomplete or flag upheld | Returned with reasons | Y | R2 |
| TC-STM-MIL-05 | Evidence checked | Inspected | Yes | Inspector records outcome | Inspected with outcome | Y | R2 |
| TC-STM-MIL-06 | Inspected (fail) | Returned | Yes | Fail recorded | Returned; contractor told what to fix | Y | R2 |
| TC-STM-MIL-07 | Inspected (pass, pass with defects) | Client approved | Yes | Client approves | Client approved | Y | R2 |
| TC-STM-MIL-08 | Inspected (pass) | Client approved | Yes | Approval window lapses `[TO VERIFY]` | Client approved (lapsed) recorded distinctly from explicit approval | Y | R2 |
| TC-STM-MIL-09 | Client approved | Release approved | Yes | Two staff approve | Release approved | Y | R2 |
| TC-STM-MIL-10 | Release approved | Paid | Yes | Bank confirms | Paid; dashboard updated | Y | R2 |
| TC-STM-MIL-11 | Returned | Submitted | Not in C8 | Contractor resubmits | Expected allowed (milestone schedule step 6); see section 16 | Y | R2 |
| TC-STM-MIL-12 | Not started | Evidence checked, Inspected | No | Skip submission | Rejected | Y | R2 |
| TC-STM-MIL-13 | Submitted (flagged) | Evidence checked | No (trigger missing) | Case manager accepts without reviewer | Rejected | Y | R2 |
| TC-STM-MIL-14 | Inspected (fail) | Client approved | No | Client approves a fail | Rejected | Y | R2 |
| TC-STM-MIL-15 | Evidence checked | Client approved | No | Approve before inspection | Rejected | Y | R2 |
| TC-STM-MIL-16 | Client approved | Paid | No | Record bank payment without staff approvals | Rejected; alert | Y | R2 |
| TC-STM-MIL-17 | Paid | Any | No | Resubmit or re-approve | Rejected | Y | R2 |
| TC-STM-MIL-18 | Not started | Submitted | No (order) | Submit milestone 3 before milestone 2 passed | Rejected, or flagged per FR-MOB-011 | Y | R2 |

### 5.5 Listing

| ID | From | To | Valid | Steps | Expected result | Auto | Rel |
|---|---|---|---|---|---|---|---|
| TC-STM-LST-01 | Draft | In verification | Yes | Listing fee paid | In verification | Y | R2 |
| TC-STM-LST-02 | In verification | Rejected | Yes | Report amber or red | Rejected; seller told why | Y | R2 |
| TC-STM-LST-03 | In verification | Live | Yes | Report green and in date | Live with badge | Y | R2 |
| TC-STM-LST-04 | Live | Suspended | Yes | Monitoring alert, dispute, or misconduct (three sub-cases) | Suspended; badge hidden | Y | R2 |
| TC-STM-LST-05 | Suspended | Live | Yes | Issue resolved and report still in date | Live | Y | R2 |
| TC-STM-LST-06 | Live | Expired | Yes | Badge validity ends | Expired | Y | R2 |
| TC-STM-LST-07 | Expired | In verification | Yes | Seller orders re-verification | In verification | Y | R2 |
| TC-STM-LST-08 | Live | Reserved | Yes | Buyer reserves | Reserved; fresh search started | Y | R2 |
| TC-STM-LST-09 | Reserved | Sold | Yes | Escrow released | Sold | Y | R2 |
| TC-STM-LST-10 | Reserved | Live | Yes | Reservation lapses or fresh search fails | Live (lapse); on failed fresh search see section 16 | Y | R2 |
| TC-STM-LST-11 | Draft | Live | No | Publish without fee or verification | Rejected | Y | R2 |
| TC-STM-LST-12 | Rejected, Expired | Live | No | Republish directly | Rejected | Y | R2 |
| TC-STM-LST-13 | Suspended | Live | No (trigger missing) | Seller lifts suspension | Rejected; reviewer only | Y | R2 |
| TC-STM-LST-14 | Suspended | Reserved | No | Buyer reserves suspended listing | Rejected | Y | R2 |
| TC-STM-LST-15 | Sold | Any | No | Relist the same listing | Rejected; new listing needed | Y | R2 |
| TC-STM-LST-16 | Live | Reserved | Race | Two buyers reserve at once | One reservation | Y | R2 |

### 5.6 Dispute

| ID | From | To | Valid | Steps | Expected result | Auto | Rel |
|---|---|---|---|---|---|---|---|
| TC-STM-DSP-01 | Open | Awaiting response | Yes | Other party notified | Awaiting response; deadline set | Y | R2 |
| TC-STM-DSP-02 | Awaiting response | Evidence | Yes | Response received | Evidence | Y | R2 |
| TC-STM-DSP-03 | Awaiting response | Evidence | Yes | Response deadline passes | Evidence; non-response recorded | Y | R2 |
| TC-STM-DSP-04 | Evidence | Decision | Yes | Evidence deadline passes | Decision | Y | R2 |
| TC-STM-DSP-05 | Decision | Closed | Yes | Decision recorded and notified | Closed; linked freezes lifted or outcome applied | Y | R2 |
| TC-STM-DSP-06 | Open, Awaiting response, Evidence, Decision | Referred | Yes | Reviewer refers to mediation, from each state | Referred; releases stay frozen | Y | R2 |
| TC-STM-DSP-07 | Referred | Closed | Yes | Mediation outcome recorded | Closed | Y | R2 |
| TC-STM-DSP-08 | Open | Decision, Closed | No | Decide before response stage | Rejected | Y | R2 |
| TC-STM-DSP-09 | Evidence | Decision | No (early) | All parties finished early | Rejected under current C8; see section 16 | Y | R2 |
| TC-STM-DSP-10 | Decision | Closed | No (trigger missing) | Close with no reasons or no notification | Rejected | Y | R2 |
| TC-STM-DSP-11 | Closed | Any, including Referred | No | Reopen or refer | Rejected; new dispute needed (C8 "Any" read as "any open state", see section 16) | Y | R2 |

---

## 6. End-to-end journey tests

Run in Playwright on staging against provider sandboxes. Mobile steps in J-03 and J-05 run with the app on an emulator or real device. Each journey has a happy path (`-01`) and unhappy paths.

| ID | Journey | Scenario | Personas | Steps (short) | Expected result | Auto | Rel |
|---|---|---|---|---|---|---|---|
| TC-E2E-J01-01 | J-01 | Diaspora buyer orders on a phone, report released | P-01, P-03, P-04, P-05, P-06, P-07 | Sign up; identity check; order; pay by card; case accepted; tasks done; report signed; two approvals; download PDF; check hash; escrow offered | Each status visible in tracker with dates; PDF hash matches; escrow offer shown for green | Y | R1 |
| TC-E2E-J01-02 | J-01 | Local buyer pays by mobile money | P-02 | Order local tier; pay with mobile money | Price in GHS; case created after confirmation | Y | R1 |
| TC-E2E-J01-03 | J-01 | Payment fails then succeeds | P-01 | Card declined; retry with mobile money | One case only; one receipt | Y | R1 |
| TC-E2E-J01-04 | J-01 | Identity check fails | P-01, P-03 | Provider fails check; report ready | Report release blocked until manual check passes; client told what to do | Y | R1 |
| TC-E2E-J01-05 | J-01 | Red verdict | P-01 | Overlay result inside acquisition; report red | Released red report; no escrow offer; plain "do not buy" summary | Y | R1 |
| TC-E2E-J01-06 | J-01 | Reviewer returns report | P-04 | Reviewer returns with comments | Case back in progress; lawyer's approval cleared; client status unchanged in tone | Y | R1 |
| TC-E2E-J01-07 | J-01 | Slow, dropping connection | P-01 | Run J01-01 on 3G profile with a forced drop during site plan upload | Upload resumes or retries cleanly; no duplicate order; under NFR-PERF-01 targets | Y | R1 |
| TC-E2E-J01-08 | J-01 | Disputed plot site visit | P-03, P-06, P-07 | Plot flagged disputed | Visit cannot be assigned until risk screen and two people | Y | R1 |
| TC-E2E-J02-01 | J-02 | Purchase through escrow, released | P-01, P-03, P-04, seller | Choose escrow; conditions copied; all accept; bank deposit recorded; fresh search; close conditions; two approvals; instruction; bank confirms | Every step visible to client; client never sees Fidero account details; release confirmed | Y | R1 |
| TC-E2E-J02-02 | J-02 | Open condition blocks | P-03, P-04 | Leave consent condition open; try approval | Blocked with condition named | Y | R1 |
| TC-E2E-J02-03 | J-02 | Fresh search stale | P-03 | Move clock past window | Blocked; new fresh-search case ordered; release after it | Y | R1 |
| TC-E2E-J02-04 | J-02 | Only one approver available | P-04 | One approval; wait | Not sent; reminder to second approver; nothing reaches bank | Y | R1 |
| TC-E2E-J02-05 | J-02 | Bank confirmation mismatch | P-03 | Confirmation with different amount | Not marked Released; reviewer task | Y | R1 |
| TC-E2E-J02-06 | J-02 | Cancel and refund | P-01, P-03, P-04 | Seller withdraws; two staff approve cancellation | Refund instruction; Cancelled after bank confirms | Y | R1 |
| TC-E2E-J02-07 | J-02 | Seller declines terms | Seller | Seller rejects terms | Escrow stays Proposed; client told; no bank details shown | Y | R1 |
| TC-E2E-J03-01 | J-03 | Build milestone paid on pass | P-01, P-08, P-09, P-04 | Create project; BoQ; contractor; app capture; submit; evidence checked; inspection pass; client approves; two approvals; bank pays | Dashboard shows photos, result and payment | P | R2 |
| TC-E2E-J03-02 | J-03 | Inspection fail and resubmit | P-08, P-09 | Fail; contractor fixes; resubmit; pass | No payment on fail; payment after pass | P | R2 |
| TC-E2E-J03-03 | J-03 | Pass with defects | P-09 | Two defects valued | Payment minus defect value; balance after defects closed | P | R2 |
| TC-E2E-J03-04 | J-03 | Fraud flags | P-08, P-04 | Submit from 2 km away; reuse photo hash from another project | Flags raised; reviewer upholds; Returned; confirmed fraud removes contractor (FR-BLD-010) | P | R2 |
| TC-E2E-J03-05 | J-03 | Conflicted inspector | P-03 | Assign inspector linked to contractor | Blocked | Y | R2 |
| TC-E2E-J03-06 | J-03 | Re-pricing change | P-01 | Rate guide changes before approval | Client sees new GHS amount and approves again | Y | R2 |
| TC-E2E-J03-07 | J-03 | Offline site | P-08 | Capture with no signal; close app; reboot; reconnect next day | Submission arrives complete; capture times preserved; server time recorded | N | R2 |
| TC-E2E-J04-01 | J-04 | Buy verified listing | P-10, P-01 | Developer lists; verification green; live with badge; buyer opens full report; reserves; fresh search; escrow per J-02; release | Listing Sold; success fee invoiced | Y | R2 |
| TC-E2E-J04-02 | J-04 | Plot fails verification | P-10 | Report amber | Listing Rejected; never public | Y | R2 |
| TC-E2E-J04-03 | J-04 | Badge expires while buyer browsing | P-01 | Clock past validity | Badge gone; reserve disabled | Y | R2 |
| TC-E2E-J04-04 | J-04 | Fresh search finds a new caveat | P-01, P-03 | Fresh search red after reservation | Reservation ends; listing suspended; escrow cancelled before funding | Y | R2 |
| TC-E2E-J05-01 | J-05 | Fund project, supplier paid on stage | P-13 | Create project; checks pass; bank holds; invoice and receipts; stage confirmed; two approvals | Supplier paid directly | Y | R2 |
| TC-E2E-J05-02 | J-05 | Supplier fails check | P-13 | Supplier fails | Cannot be paid; owner told | Y | R2 |
| TC-E2E-J05-03 | J-05 | Runner asks for cash | P-13 | Runner submits invoice in own name | Rejected (RUL-21) | Y | R2 |
| TC-E2E-J05-04 | J-05 | Amount above AML threshold | P-13 | Budget above threshold | Enhanced checks before bank accepts money | Y | R2 |
| TC-E2E-J06-01 | J-06 | Bank checks with consent | P-12, P-01 | Client consents; partner queries | Verdict and date returned | Y | R2 |
| TC-E2E-J06-02 | J-06 | No consent | P-12 | Partner queries | Only "report exists" | Y | R2 |
| TC-E2E-J06-03 | J-06 | Consent withdrawn | P-01, P-12 | Client withdraws; partner queries | Verdict no longer returned | Y | R2 |
| TC-E2E-J06-04 | J-06 | Bad key and rate limit | P-12 | Revoked key; burst calls | 401; 429 | Y | R2 |
| TC-E2E-J07-01 | J-07 | Dispute decided, release resumes | Buyer, seller, P-04 | Open dispute on funded escrow; statements; decision | Frozen then Funded; release follows normal checks | Y | R2 |
| TC-E2E-J07-02 | J-07 | Party misses deadlines | Seller | No response | Moves on at deadlines; decision recorded | Y | R2 |
| TC-E2E-J07-03 | J-07 | Mediation | P-04 | Refer | Referred; frozen until outcome | Y | R2 |
| TC-E2E-J07-04 | J-07 | Dispute between approval and bank payment | P-04 | Open dispute after two approvals | Instruction not sent; if already sent, bank recall procedure triggered (see section 16) | P | R2 |
| TC-E2E-J08-01 | J-08 | Existing building verified | P-01 | Order building check; extra steps done | Report includes permit, structural, occupancy, rates and bills | Y | R1 |
| TC-E2E-J08-02 | J-08 | Tenant found | P-01, P-03 | Tenancy found | Amber with vacant possession condition | Y | R1 |
| TC-E2E-J08-03 | J-08 | Release needs keys and vacant possession | P-03, P-04 | Close all but vacant possession | Release blocked until keys and vacant possession evidence closed | Y | R1 |

---

## 7. Non-functional tests

| ID | NFR | Method | Tool (proposed) | Target | Environment | Pass criterion | Rel |
|---|---|---|---|---|---|---|---|
| TC-NFR-PERF-01-01 | NFR-PERF-01 | Load key portal pages on throttled profile, 20 runs each | Playwright with network throttling; Lighthouse CI | Useful content (largest contentful paint) under 3 s at p75 on 1.6 Mbps, 300 ms latency | staging | p75 under 3 s on every P1 page | R1 |
| TC-NFR-PERF-02-01 | NFR-PERF-02 | Measure transferred bytes on first load, cache empty | Lighthouse CI budgets; Playwright request log | Under 500 KB excluding user-opened images | CI and staging | Budget check fails the build when exceeded | R1 |
| TC-NFR-PERF-03-01 | NFR-PERF-03 | Load test mixed read and write traffic | k6 | Reads p95 under 500 ms; writes p95 under 1 s at 10 times expected R1 load `[TO VERIFY]` load model | staging sized like production | Targets met for 30 minutes steady state; error rate under 0.1% (assumption) | R1 |
| TC-NFR-PERF-03-02 | NFR-PERF-03 | Soak test | k6 | Expected load for 8 hours | staging | No memory growth trend; no latency drift above target | R1 |
| TC-NFR-PERF-04-01 | NFR-PERF-04 | Save polygons with all layers loaded, single and concurrent | pytest timing; k6 | Overlay results within 30 s | staging with full layer set | 95% (assumption) under 30 s; none lost | R1 |
| TC-NFR-PERF-05-01 | NFR-PERF-05 | Measure cold start and install size on reference 2 GB device | Android macrobenchmark; APK analyser | Start under 3 s; install under 30 MB | Physical device lab | Median cold start under 3 s over 10 runs; release build under 30 MB | R2 |
| TC-NFR-AVL-01-01 | NFR-AVL-01 | External uptime checks every minute | Synthetic monitoring `[TO VERIFY]` tool | 99.5% monthly | production | Monthly report shows at least 99.5%; checked at R1 go-live plus 1 month as part of acceptance | R1 |
| TC-NFR-AVL-01-02 | NFR-AVL-01 | Fail one instance and one availability zone | AWS fault injection `[TO VERIFY]` | Service continues | staging | No user-visible outage beyond health-check failover time | R1 |
| TC-NFR-AVL-02-01 | NFR-AVL-02 | Restore database and storage to a point in time | Runbook in document 06 | RPO 1 hour; RTO 4 hours | Isolated restore account | Data loss at most 1 hour; service usable within 4 hours (OAT-02) | R1 |
| TC-NFR-AVL-03-01 | NFR-AVL-03 | Inspect storage replication and object lock | AWS config checks | Two copies in separate locations | staging and production | Replication on; test object present in both locations; deletion of primary leaves copy | R1 |
| TC-NFR-SEC-01-01 | NFR-SEC-01 | Scan endpoints for protocol versions; check storage and database encryption settings | testssl.sh; AWS config rules | TLS 1.2 or later; encryption at rest on | staging and production | No TLS below 1.2; every store encrypted | R1 |
| TC-NFR-SEC-02-01 | NFR-SEC-02 | Inspect password hashing; idle staff session | Unit test; Playwright with clock | Argon2id or equivalent; staff timeout 30 min | CI | Hash algorithm and parameters as set; staff session ends after 30 min idle and not before | R1 |
| TC-NFR-SEC-03-01 | NFR-SEC-03 | Independent penetration test | External firm | No open high or critical findings | staging matching release candidate | Retest letter confirms closure | R1 |
| TC-NFR-SEC-04-01 | NFR-SEC-04 | Scan repository history, images and configuration for secrets | gitleaks or equivalent; image scan | No secrets in code or config | CI | Zero findings; secrets loaded from secrets manager at runtime | R1 |
| TC-NFR-SEC-05-01 | NFR-SEC-05 | ASVS L2 checklist verification (section 8.3) | Checklist plus ZAP and manual tests | All applicable L2 items pass | staging | Every applicable item has evidence; failures closed or accepted by product owner in writing | R1 |
| TC-NFR-PRIV-01-01 | NFR-PRIV-01 | Audit every service against the data location register | Infrastructure inventory script | All personal data in accepted locations `[TO VERIFY]` | production | Register complete; no store outside accepted regions | R1 |
| TC-NFR-PRIV-02-01 | NFR-PRIV-02 | Compare schema fields to data catalogue | Schema diff script in CI | Each personal field has a purpose | CI | Build fails on a new personal field without a catalogue entry | R1 |
| TC-NFR-USE-01-01 | NFR-USE-01 | Moderated usability test (section 10.2) | Remote session recording | 5 diaspora users order on own phone, unaided | staging with sandbox payment | Each of 5 completes in under 10 minutes without help (see section 16 on interpretation) | R1 |
| TC-NFR-USE-02-01 | NFR-USE-02 | Readability score on all status templates | Script using a readability formula `[TO VERIFY]` choice | Reading age 12 or lower | CI | Every status template scores within target; failures listed | R1 |
| TC-NFR-USE-02-02 | NFR-USE-02 | Plain English review | Manual review by 3 users from P-01 and P-02 groups | Understood without help | staging | Each user restates meaning correctly for 10 sample messages | R1 |
| TC-NFR-A11Y-01-01 | NFR-A11Y-01 | Automated checks on every page and state | axe-core in Playwright | WCAG 2.2 AA | CI and staging | Zero serious or critical violations | R1 |
| TC-NFR-A11Y-01-02 | NFR-A11Y-01 | Manual audit (section 10.1) | Screen readers, keyboard, zoom | WCAG 2.2 AA | staging | No open AA failures on P1 journeys | R1 |
| TC-NFR-OBS-01-01 | NFR-OBS-01 | Check trace IDs and alerts | Integration test; alert drills | Trace ID on every request; alerts on errors, latency, upload queue, job failures | staging | Trace ID in logs for API, worker and app upload; each alert fires in a drill within 5 minutes (assumption) | R1 |
| TC-NFR-MNT-01-01 | NFR-MNT-01 | Coverage report; RUL coverage check | coverage.py; script mapping `rul` tags to RUL IDs | 80% lines of core API; every RUL tested | CI | Gate fails below 80% or if any RUL-nn has no passing test | R1 |
| TC-NFR-MNT-02-01 | NFR-MNT-02 | Add a test product line and a test country through configuration only | Admin UI; diff of code repository | No code change outside integrations | staging | Line works end to end; code diff empty apart from new integration adapters | R2 |
| TC-NFR-SCL-01-01 | NFR-SCL-01 | Load test on `seed-scale` data | k6; PostgreSQL query plans | 2,000 open cases, 500 projects, 20,000 listings | staging | NFR-PERF-03 targets still met; no table scans on hot paths | R2 |
| TC-NFR-LOC-01-01 | NFR-LOC-01 | Static scan for hard-coded user-facing strings; pseudo-locale run | i18n lint; pseudo-localisation | All strings in translation files | CI | Zero hard-coded strings; pseudo-locale shows no untranslated text | R1 |
| TC-NFR-AUD-01-01 | NFR-AUD-01 | Read audit entries for archived data near retention end | Integration test with clock | Readable for full retention | staging | Entries for records at retention minus one day are readable and chain-verifiable | R1 |

---

## 8. Security testing plan

### 8.1 Approach

Security testing is threat-driven. The main threats are people who want money released without proof, want evidence to look real when it is not, or want personal data. Each threat below has a test. Threat cases run in staging. Automated ones run nightly. Manual ones run before each release and are repeated by the penetration tester.

### 8.2 Threat-driven test cases

| ID | Threat | Linked requirements | Test | Expected result | Auto | Rel |
|---|---|---|---|---|---|---|
| TC-SEC-01 | Bypass two-person release by replaying the first approver's request as the second | RUL-05, FR-ESC-007 | Capture approval request; replay with second session and with changed user ID | Rejected; approver is taken from the authenticated session only | Y | R1 |
| TC-SEC-02 | Bypass two-person release with two accounts owned by one person | RUL-05 | Create two staff accounts with same phone or device; approve | Rejected or flagged; staff onboarding requires identity link (TC-RUL-05-04) | P | R1 |
| TC-SEC-03 | Send instruction by calling the send endpoint directly | RUL-05, RUL-06 | Call send with valid staff token on Ready to release escrow | Rejected; send only from Release approved state | Y | R1 |
| TC-SEC-04 | Change release amount or payee between approval and sending | FR-ESC-008 | Modify instruction record or file in storage | Signature check fails; send blocked; alert | Y | R1 |
| TC-SEC-05 | Social engineering: forged bank confirmation uploaded to mark Funded or Released | FR-ESC-004, FR-ESC-009 | Upload edited bank letter | Manual entry flagged for second check against bank channel `[TO VERIFY]` procedure (see section 16) | N | R1 |
| TC-SEC-06 | Replay signed milestone evidence from a past milestone or another project | FR-MOB-004, FR-MOB-011 | Resubmit a previously accepted signed item | Hash already seen; flagged; not counted | Y | R2 |
| TC-SEC-07 | Gallery upload spoofing: inject a pre-made photo into the capture pipeline | RUL-08, FR-MOB-002 | Hook camera API on rooted device; use virtual camera app; intercept upload and swap file | Hash or signature mismatch, or device integrity check fails `[TO VERIFY]` Play Integrity use; item flagged | P | R2 |
| TC-SEC-08 | GPS spoofing with mock location apps | FR-MOB-003, FR-MOB-011 | Enable mock location; capture on site coordinates from far away | Mock location detected and flagged; cross-check with network position and image metadata where possible | P | R2 |
| TC-SEC-09 | Device clock set back | FR-MOB-011 | Set device time 3 days back; capture | Device-server time gap flagged | Y | R2 |
| TC-SEC-10 | Extract device signing key | FR-MOB-004 | Attempt key export on rooted device | Key is non-exportable (hardware-backed where available); attestation recorded | N | R2 |
| TC-SEC-11 | IDOR on cases, reports, evidence, escrows, projects, listings, disputes | FR-ACC-007 | Generated test: for every object endpoint, every role, request objects owned by another user | 404 in all unauthorised cases; 100% matrix pass | Y | R1 |
| TC-SEC-12 | Guess or share evidence links | FR-EVD-003 | Enumerate keys; reuse expired link; open link while signed out | Refused; bucket not listable | Y | R1 |
| TC-SEC-13 | Audit log tampering by an administrator | FR-AUD-002 | Use admin UI, API, Django admin, and data export-import | No path edits or deletes entries | Y | R1 |
| TC-SEC-14 | Audit log tampering by a database superuser | FR-AUD-004 | Edit an entry in a copy; run verifier; check external hash anchor `[TO VERIFY]` | Break detected | Y | R1 |
| TC-SEC-15 | Partner API consent bypass | RUL-16, FR-PTR-002 | Query with another partner's consent ID; change partner ID in body; query coordinates near a consented plot | No verdict without matching consent for this partner | Y | R2 |
| TC-SEC-16 | Partner API enumeration of plots | FR-PTR-001, FR-PTR-004 | Sweep coordinates and references | Rate limited; anomalies alerted; responses do not reveal owner data | Y | R2 |
| TC-SEC-17 | SMS and WhatsApp content leakage | FR-NTF-004 | For every SMS and WhatsApp template and every event, render with fixture data containing verdicts, amounts above threshold and third-party names | No forbidden content in any rendered message | Y | R1 |
| TC-SEC-18 | Account takeover by SIM swap on one-time codes | FR-ACC-002, FR-ACC-003 | Use one-time code sign-in for a staff user | Staff and approvers cannot sign in with SMS code alone; authenticator app or key required `[TO VERIFY]` design choice | Y | R1 |
| TC-SEC-19 | Lockout abuse to stop approvers working | FR-ACC-009 | Lock a known approver by failed attempts | Lockout happens as specified; alert to admin; second approver pool exists (see section 16) | Y | R1 |
| TC-SEC-20 | Payment webhook forgery | FR-ORD-004, FR-PAY-001 | Send unsigned or wrongly signed webhook | Rejected; no case created | Y | R1 |
| TC-SEC-21 | Escrow bank details changed by an insider | FR-ESC-003, FR-ADM-003 | Change bank account on bank partner record | Needs second admin and alert to founder; client-facing details show change history | Y | R1 |
| TC-SEC-22 | Malicious file upload: malware, polyglot, XXE in office files, oversized images | FR-EVD-005 | Upload fixtures | Rejected or safely stored and never rendered inline | Y | R1 |
| TC-SEC-23 | Stored cross-site scripting through case messages, listing text and file names | FR-CASE-015, FR-LST-001 | Inject payloads | Escaped everywhere; content security policy blocks inline script | Y | R1 |
| TC-SEC-24 | Locked scope text changed through template import | RUL-04 | Import template with altered section 12 | Rejected | Y | R1 |
| TC-SEC-25 | Report hash checker used to find reports | FR-RPT-008 | Submit many references | Rate limited; no data beyond match result | Y | R1 |
| TC-SEC-26 | Licence spoofing: professional uploads fake licence | RUL-20 | Upload fake licence document | Not verified until staff check with the licence body; cannot sign | N | R1 |
| TC-SEC-27 | Inspector collusion through a new company | RUL-10 | Inspector and contractor share phone, bank account or address | Link detected and flagged `[TO VERIFY]` link sources | P | R2 |
| TC-SEC-28 | Bulk data theft through CSV export | FR-DPR-005, FR-ANL-002 | Export repeatedly with filters to rebuild client list | Personal data not in metric exports; volume alerts | Y | R1 |
| TC-SEC-29 | Incident log exposure | FR-CASE-010 | Access as every role except safety roles | Refused | Y | R1 |
| TC-SEC-30 | Secrets in mobile app | NFR-SEC-04 | Decompile APK; search for keys | No secrets; only public configuration | Y | R2 |
| TC-SEC-31 | Cross-tenant access between developer organisations | FR-ACC-011 | Developer A user opens developer B listing admin | Refused | Y | R2 |
| TC-SEC-32 | Country data leakage | FR-CTY-002 | Nigerian user queries Ghana data and the reverse | Refused where roles do not span countries | Y | R3 |

### 8.3 OWASP ASVS level 2 verification (NFR-SEC-05)

1. At R1 start, the engineering lead copies the ASVS L2 requirement list into a tracked checklist, one row per requirement, with "applies" or "does not apply and why".
2. Each applicable row names how it is verified: automated test ID, SAST rule, DAST scan, configuration check or manual review.
3. The checklist is reviewed before each release. Every applicable row must have evidence dated in that release cycle.
4. The penetration tester receives the checklist and samples at least the authentication, session, access control, validation, cryptography, file handling and API sections.
5. Failures are logged as defects. A failed L2 control on authentication, access control or file handling is at least S2.

The ASVS version to use is the latest stable version at R1 start `[TO VERIFY]`.

### 8.4 Automated security checks

| Check | Tool (proposed) | When | Gate |
|---|---|---|---|
| SAST | Semgrep (Django and React rules plus custom rules for RUL decision code), Bandit | Every PR | No new high findings |
| Dependency scan | GitHub dependency scanning or equivalent; npm audit; Gradle dependency check | Every PR and daily | No new high or critical; existing ones have a dated plan |
| Secret scan | gitleaks or equivalent | Every PR | Zero findings |
| Container and infrastructure scan | Image scanner; infrastructure-as-code scanner | Every PR touching them | No high misconfigurations |
| DAST | OWASP ZAP baseline (nightly), full active scan (weekly and pre-release) | Staging | No high findings |
| Mobile static and dynamic | MobSF `[TO VERIFY]` | Every app release candidate | No high findings |
| Authorisation matrix | Generated API tests (TC-SEC-11) | Every PR | 100% pass |

### 8.5 Penetration test scope and timing (NFR-SEC-03)

| Release | When | Scope |
|---|---|---|
| R1 | After feature freeze, at least 4 weeks (assumption) before go-live, then retest | Portal, back office, core API, evidence storage, payment and identity integrations, escrow release flow, infrastructure configuration on AWS |
| R2 | Before R2 go-live | R1 scope regression plus milestone app (static, dynamic, rooted device), partner API, bank statement and API integration, listings, disputes |
| R3 | Before R3 go-live | R2 scope regression plus records module, family and stool listings, country data separation |
| Any | After a major change to release, evidence, or access control code | Targeted test of the change |

Rules:

- The tester is independent of the developers and not paid by a vendor whose product is in scope.
- The tester works on staging with synthetic data. Production testing only for infrastructure checks, with written approval.
- Go-live needs a retest letter showing no open high or critical findings.
- Medium findings get a fix date. Low findings go to the backlog.

---

## 9. Mobile and field testing

### 9.1 Device matrix (R2)

Minimum and reference devices are assumptions until operations surveys contractors' phones (Q-09, AS-08).

| Tier | Specification | Purpose |
|---|---|---|
| Minimum | 2 GB RAM, Android 8.0 `[TO VERIFY]`, 16 GB storage, mid-range camera | Must pass all P1 tests; NFR-PERF-05 measured here |
| Reference | 3 GB RAM, Android 11 `[TO VERIFY]`, a common phone brand among Ghanaian contractors `[TO VERIFY]` | Main test device |
| Current | Recent Android version, mid-range | Compatibility with new OS behaviour on permissions, background work and storage |
| Low storage | Minimum device with under 500 MB free | Queue and capture behaviour when storage is short |
| Inspector tablet | `[TO VERIFY]` if inspectors use tablets | Layout and checklist use |

At least three physical devices are kept in Accra for testing. A cloud device farm is used for wider compatibility `[TO VERIFY]` budget.

### 9.2 Network simulation

| Profile | Settings (assumption) | Used for |
|---|---|---|
| Good 4G | 10 Mbps, 50 ms | Baseline |
| 3G | 1.6 Mbps down, 750 kbps up, 300 ms latency | Same profile as NFR-PERF-01 |
| Poor edge | 250 kbps, 600 ms, 5% packet loss | Upload resume |
| Dropping | Connection cut for 30 s every 2 minutes | Queue and retry |
| Captive portal | Network present but returns a login page | App must not mark items sent |
| Offline | Airplane mode for hours | Offline capture |

Tools: Android emulator network shaping, a network-shaping proxy on a test Wi-Fi access point `[TO VERIFY]`, and real sites with poor signal.

### 9.3 Mobile and field test cases

| ID | Test | Steps | Expected result | Auto | Rel |
|---|---|---|---|---|---|
| TC-FLD-01 | Queue survives app kill | Queue 20 items; force stop app | All items remain; upload resumes on reopen | Y | R2 |
| TC-FLD-02 | Queue survives reboot and battery death | Queue items; let battery run out; recharge | All items remain and upload | N | R2 |
| TC-FLD-03 | Queue survives app update | Queue items; install new version | Items remain; new version uploads them | Y | R2 |
| TC-FLD-04 | Low storage | Fill storage; capture | Clear warning before capture fails; no corrupt items | Y | R2 |
| TC-FLD-05 | Background limits | Queue items; lock screen; battery saver on | Upload continues under OS work rules or resumes on unlock; user sees queue state | Y | R2 |
| TC-FLD-06 | Large queue on poor network | 100 photos and 5 videos on poor edge profile | All arrive; no duplicate; order kept per milestone | Y | R2 |
| TC-FLD-07 | Captive portal | Connect to captive portal network | No item marked received until server confirms | Y | R2 |
| TC-FLD-08 | GPS cold start in rural area | Capture right after opening app | Accuracy shown; app waits or warns until accuracy within configured limit | N | R2 |
| TC-FLD-09 | Bright sunlight and dust | Use app outdoors at midday | Screens readable; buttons usable with one hand and gloves `[TO VERIFY]` | N | R2 |
| TC-FLD-10 | Shared phone | Second user signs in on same phone | First user's queue and evidence not visible | Y | R2 |
| TC-FLD-11 | Lost phone | Admin revokes device | Pending items cannot be uploaded under the revoked key; local data wiped on next start | Y | R2 |
| TC-FLD-12 | Memory pressure | Run on 2 GB device with other apps open | No crash during capture; app restores state | Y | R2 |
| TC-FLD-13 | Phone-browser tasks for runners (R1) | Runner completes task on 3G profile on a 2 GB device | Works without the app | Y | R1 |

### 9.4 Field trials

| Trial | When | Who | Where | Exit criterion |
|---|---|---|---|---|
| Internal field trial | R2 beta, first 4 weeks (assumption) | Fidero field staff, 2 surveyors, 2 runners | 3 sites in Greater Accra and Central Region with known poor signal `[TO VERIFY]` sites | All P1 mobile tests pass in the field; no lost evidence |
| Contractor pilot | After internal trial | 3 to 5 vetted contractors on real builds `[TO VERIFY]` | Real build sites | Each submits at least 2 milestones; time to submit recorded; contractor feedback logged |
| Inspector pilot | Same period | 2 to 3 independent inspectors | Same sites | Checklists completed in app; defects valued; no paper fallback needed |
| Fraud drill | During pilot | QA with operations | One site | Planted fraud attempts (gallery image, off-site capture, reused photo) are all flagged |

Field trial rules:

- Every field visit follows the risk screen (RUL-17). Trials do not use disputed plots.
- Test devices carry no personal data apart from the trial users' own sign-in.
- Contractors and inspectors in the trial sign a consent and data agreement.
- Findings become defects with photos and device logs attached.

---

## 10. Accessibility and usability

### 10.1 Accessibility testing (NFR-A11Y-01, WCAG 2.2 AA)

Scope: portal, back office and listing pages. The milestone app follows Android accessibility guidance and is checked with TalkBack and Accessibility Scanner, but WCAG conformance is claimed for the web only.

Method:

1. **Automated.** axe-core runs in every Playwright test on every page state. Serious and critical violations fail the build.
2. **Manual per release.** Keyboard only; screen readers (NVDA with Firefox or Chrome on Windows, VoiceOver on iPhone Safari, TalkBack on Android Chrome); zoom to 200% and reflow at 320 px; high contrast; reduced motion.
3. **Focus on WCAG 2.2 additions.**
   - 2.4.11 Focus not obscured: sticky headers and cookie banners must not cover focused items.
   - 2.5.7 Dragging movements: drawing or editing a plot polygon on a map must have a non-drag alternative, such as entering coordinates.
   - 2.5.8 Target size minimum: tap targets at least 24 by 24 CSS pixels, with larger targets preferred on the phone portal.
   - 3.2.6 Consistent help: help and contact link in the same place on every page.
   - 3.3.7 Redundant entry: order forms do not ask again for data already given.
   - 3.3.8 Accessible authentication: one-time codes can be pasted; no cognitive tests; password managers work.
4. **Content.** Verdict colours are never the only signal. Red, amber and green always carry a word and an icon. PDF reports are tagged and readable by screen readers `[TO VERIFY]` PDF library support.

Pass criterion: no open AA failure on any P1 journey. Other AA failures need a fix date before go-live.

### 10.2 Usability acceptance (NFR-USE-01)

| Item | Plan |
|---|---|
| Participants | 5 diaspora users who have never used Fidero, recruited through associations in at least two countries. Mix of ages and phone types. Not Fidero staff or relatives |
| Device | Participant's own phone, own network |
| Environment | staging with sandbox payment and a test card supplied in the session |
| Task | "You want a plot near Kasoa checked before you pay the seller. Order a report." Participant receives a fixture site plan and seller details beforehand |
| Moderation | Remote, recorded with consent. Moderator does not help. Any help given counts as a failure for that participant |
| Timer | From opening the portal link to seeing the order confirmation and case reference |
| Pass | Each of the 5 completes without help in under 10 minutes (proposed reading of NFR-USE-01, see section 16) |
| Also measured | Errors, hesitations over 30 seconds, understanding of tier choice, scope statement and price, confidence score (1 to 5) |
| When | Prototype stage (informal), R1 beta (formal), and after any change to the order flow |
| Output | Short report with times, issues, severity and fixes. Failures become S2 defects if they block the task |

Supporting checks: TC-NFR-USE-02-01 and TC-NFR-USE-02-02 for status message plain language.

---

## 11. User, operational and partner acceptance

### 11.1 UAT approach

- UAT runs on staging with a release candidate that has passed system test exit criteria.
- Real people act as each persona. Where a real partner is not yet signed, a Fidero staff member plays the role and this is noted on the sign-off.
- Participants follow scripted scenarios, then spend time on free use.
- Each scenario is accepted, accepted with minor issues, or rejected. A rejection needs a defect ID.
- UAT lasts 2 weeks per release (assumption). The product owner chairs a daily 15-minute triage.

### 11.2 UAT participants

| Persona | Who takes part | Releases |
|---|---|---|
| P-01 Diaspora buyer | 3 to 5 real diaspora clients from the R0 service, with consent | R1, R2 |
| P-02 Local buyer | 2 local clients from the R0 service | R1 |
| P-03 Case manager | Fidero operations staff | R1, R2, R3 |
| P-04 Reviewer | Fidero senior reviewer | R1, R2, R3 |
| P-05 Lawyer | Contracted lawyer from R0 | R1 |
| P-06 Surveyor | Contracted surveyor from R0 | R1 |
| P-07 Runner | Contracted runner from R0 | R1, R2 |
| P-08 Contractor | 2 to 3 pilot contractors | R2 |
| P-09 Inspector | 2 independent inspectors | R2 |
| P-10 Developer | 1 pilot developer `[TO VERIFY]` | R2 |
| P-11 Family head or stool secretary | 1 authority partner `[TO VERIFY]` | R3 |
| P-12 Bank credit officer | Partner bank staff `[TO VERIFY]` | R2 |
| P-13 Project fund owner | 1 or 2 diaspora clients | R2 |
| P-14 Administrator | Fidero administrator | R1, R2, R3 |

### 11.3 UAT scenarios

| ID | Scenario | Personas | Linked | Acceptance criteria | Rel |
|---|---|---|---|---|---|
| UAT-01 | Order and pay for a land report on your own phone | P-01 | J-01, NFR-USE-01 | Order placed and paid without help; price, scope and terms clear; receipt received | R1 |
| UAT-02 | Order and pay in cedis by mobile money | P-02 | J-01 | Price in GHS; mobile money works; receipt received | R1 |
| UAT-03 | Run a case from acceptance to report draft | P-03, P-05, P-06, P-07 | F-03 | Each person finds their tasks; evidence attached; overdue items visible; no spreadsheet needed | R1 |
| UAT-04 | Complete and sign report sections; review and release | P-04, P-05, P-06 | F-04, RUL-02, RUL-03, RUL-20 | Signers sign their sections only; green blocked with any red; two-person release works; PDF correct and readable | R1 |
| UAT-05 | Follow a case and read the report as a client | P-01 | F-06 | Status messages understood; next date clear; PDF downloads on phone; hash check understood | R1 |
| UAT-06 | Site visit on a disputed plot | P-03, P-06, P-07 | RUL-17 | Risk screen asked; one-person assignment blocked; incident log reachable from phone | R1 |
| UAT-07 | Open and run an escrow to release | P-01, P-03, P-04, seller | J-02 | Bank details correct; conditions match section 11; release needs two approvers with MFA; client sees each step | R1 |
| UAT-08 | Try to release with a problem | P-03, P-04 | RUL-06, RUL-07 | Open condition and stale search block release with clear reasons | R1 |
| UAT-09 | Verify an existing building | P-01, P-03 | J-08 | Extra building checks present; vacant possession condition carried to escrow | R1 |
| UAT-10 | Administer templates, prices, partners and configurable values | P-14 | F-11 | Changes made without a developer; versions kept; scope text change needs second admin and approvals | R1 |
| UAT-11 | Handle a data access request and a bulk export | P-14, P-04 | F-14 | Export of one person complete and limited; bulk export needs second approver | R1 |
| UAT-12 | Read the operating dashboard | P-03, P-14, founder | F-13 | Metrics match a hand count on a sample week | R1 |
| UAT-13 | Capture and submit a milestone on site | P-08 | J-03 | Evidence list clear; capture works offline; submission arrives; contractor understands flags | R2 |
| UAT-14 | Inspect a milestone and record defects | P-09 | J-03 | Checklist complete on site; defects valued; result reaches client dashboard | R2 |
| UAT-15 | Watch a build and approve a payment | P-01 | J-03, RUL-18 | Dashboard clear; re-priced amount clear; approval works; client cannot release alone | R2 |
| UAT-16 | Review fraud flags | P-04 | FR-MOB-011 | Flag reasons clear; evidence and metadata visible; decision recorded | R2 |
| UAT-17 | List an estate and see plots go live | P-10 | J-04 | Only green, in-date plots go live; badge and report link shown | R2 |
| UAT-18 | Buy a listed plot | P-01 | J-04 | Full report visible; reservation starts fresh search and escrow | R2 |
| UAT-19 | Fund a project and pay a supplier | P-13 | J-05 | Supplier paid directly; runner cannot be paid; stage evidence visible | R2 |
| UAT-20 | Check collateral through the partner API | P-12 | J-06 | Status returned with consent; nothing beyond "report exists" without consent; documentation usable | R2 |
| UAT-21 | Raise and decide a dispute | P-01, seller, P-04 | J-07 | Release frozen; deadlines shown; decision and reasons sent to all | R2 |
| UAT-22 | Off-plan stage payment | P-01, P-10, P-09 | F-17 | Stage released only with app evidence and inspector pass | R2 |
| UAT-23 | Capture traditional authority records and use them in a case | P-11, P-03 | F-25 | Records captured; matching case pre-filled; authority confirms own records | R3 |
| UAT-24 | Run a Nigerian pilot case end to end | P-03, P-14, Nigerian professionals `[TO VERIFY]` | F-28 | Nigerian template, currency, partners and data location used; no code change | R3 |

### 11.4 UAT sign-off form

```
FIDERO UAT SIGN-OFF

Release:              R_   Release candidate build: ________
Scenario ID(s):       UAT-__
Participant name:     __________________   Persona: P-__
Real user / staff acting as persona / partner: ________
Environment:          staging   Date(s): ____________

Result (tick one):
[ ] Accepted
[ ] Accepted with minor issues (list defect IDs, all S3 or S4): ________
[ ] Rejected (list defect IDs): ________

Comments:
________________________________________________

Participant signature: ____________  Date: ________
Product owner signature: ____________  Date: ________
```

Signed forms are stored as evidence in the release record. A scanned or electronic signature is fine.

### 11.5 Operational acceptance (OAT)

Runbooks and procedures are in document 06. OAT proves they work.

| ID | Test | Pass criterion | Rel |
|---|---|---|---|
| OAT-01 | Deploy release candidate to production-like staging using the pipeline; roll back | Deploy and rollback each complete without manual database edits; time recorded | R1 |
| OAT-02 | Restore database and evidence storage from backup into an isolated account | Meets NFR-AVL-02 (RPO 1 hour, RTO 4 hours); restored data passes integrity checks (evidence hashes, audit chain) | R1 |
| OAT-03 | Alert drills: error spike, latency, upload queue growth, job failure, failed release instruction send | Each alert reaches the on-call person within 5 minutes (assumption); runbook step followed | R1 |
| OAT-04 | Runbook walk-through by someone who did not write it: bank channel down, payment provider down, identity provider down, SMS provider down | Each fallback in 01 A8 works (manual entry, manual check, other channel) | R1 |
| OAT-05 | Secrets rotation | Database, provider and signing secrets rotated without downtime | R1 |
| OAT-06 | Data breach drill | Breach plan followed to the notification draft step within the time set `[TO VERIFY]` | R1 |
| OAT-07 | Audit hash-chain verification job and alert | Job runs daily; a planted break in a test copy alerts | R1 |
| OAT-08 | Retention job dry run on production metadata | Lists items that would be deleted; matches expected classes; nothing deleted in dry run | R1 |
| OAT-09 | App release, staged rollout and remote device revocation | Staged rollout works; revoked device cannot upload | R2 |
| OAT-10 | Statement file arrival monitoring | Missing or late file alerts | R2 |
| OAT-11 | Country-specific hosting and backup location | Each country's data and backups in its required location | R3 |

### 11.6 Partner acceptance with the escrow bank (PAT)

Run with the partner bank or licensed escrow agent once the agreement is signed (AS-02). Formats are `[TO VERIFY]` until the bank confirms them.

| ID | Test | Steps | Pass criterion | Rel |
|---|---|---|---|---|
| PAT-01 | Release instruction format | Fidero sends 5 test instructions in the agreed format on the bank's test channel | Bank's system or staff accepts all 5 with no manual correction | R1 |
| PAT-02 | Instruction signatures | Bank verifies approver signatures and names on each test instruction | Bank confirms the check works; a deliberately altered instruction is rejected by the bank | R1 |
| PAT-03 | Instruction channel and acknowledgement | Send by the agreed channel; bank acknowledges | Acknowledgement recorded within the agreed time `[TO VERIFY]`; duplicate send is recognised by the bank as a duplicate | R1 |
| PAT-04 | Deposit confirmation | Bank sends test deposit confirmations | Each matched to the right escrow; manual entry procedure accepted by the bank | R1 |
| PAT-05 | Refund and cancellation instruction | Send a test cancellation | Bank processes and confirms; Fidero records Cancelled | R1 |
| PAT-06 | Statement file reconciliation | Bank supplies statement files for 10 test days, including edge cases from section 2.7 | All matched lines correct; every unmatched line listed; totals reconcile to the bank's closing balances | R2 |
| PAT-07 | Bank API (if offered) | Run deposit and release status calls | Contract tests pass against bank sandbox; error and timeout handling agreed | R2 |
| PAT-08 | Partial releases | Send milestone partial instructions | Bank pays partial amounts and reports balances that match the tracker | R2 |
| PAT-09 | Cut-off times and holidays | Send instructions near cut-off and on a public holiday | Behaviour matches the agreement; client-facing dates correct | R1 |
| PAT-10 | Bank sign-off | Bank's operations and compliance review results | Written acceptance from the bank | R1, R2 |

Other partners get a shorter acceptance: the payment provider (sandbox to live switch, settlement file), the identity provider (pass, fail, manual review), messaging providers (delivery reports, sender ID), and partner API customers (UAT-20 plus their own integration test).

---

## 12. Defect management

### 12.1 Severity

| Severity | Definition | Examples |
|---|---|---|
| S1 critical | Money could move, or evidence or a report could change, without the rules; personal data exposed to the wrong person; service down for all users; data loss | Release sent with one approver; green verdict with a red section allowed; client sees another client's case; evidence overwritten; gallery photo accepted as evidence; audit entry editable |
| S2 high | A Must requirement fails with no workaround; a security control fails; a P1 journey is blocked for a group of users | Order cannot be paid by mobile money; offline queue loses items after reboot; lockout not applied; WCAG failure blocks a P1 journey |
| S3 medium | A requirement fails but a reasonable workaround exists; wrong but not harmful output | Dashboard filter wrong; reminder sent a day late; preview not generated but original available |
| S4 low | Cosmetic, wording or minor usability issue | Typo, alignment, unclear label that users still understand |

Escalation rules:

- Any failure of a `rul` test is at least S2. If it lets money move or evidence change, it is S1.
- Any defect in a very high risk module (section 2.2) is at least S3.
- A security finding rated high or critical by the penetration tester is S1 or S2 to match.

### 12.2 Priority

| Priority | Meaning |
|---|---|
| P1 | Fix now. Stops the current release or a live service |
| P2 | Fix in this release |
| P3 | Fix in a planned later release |
| P4 | Fix when convenient, or close |

Severity is how bad the defect is. Priority is when we fix it. The product owner sets priority in triage.

### 12.3 Triage

- **Who:** product owner (chair), engineering lead, QA lead; operations lead for workflow issues.
- **When:** daily during system test and UAT; twice a week otherwise; within 2 hours (assumption) for any new S1.
- **Steps:** confirm and reproduce; set severity and priority; assign an owner; link to the FR, RUL, NFR or TC; decide release impact.
- **Records:** every defect has steps, expected and actual result, environment, build, evidence (screenshot, log, trace ID), and the linked requirement.
- **Production S1:** follow the incident runbook in document 06. If money movement is involved, pause sending release instructions until the cause is known.

### 12.4 Service levels (assumptions)

| Severity | Acknowledge | Fix or workaround in production | Fix in test cycle |
|---|---|---|---|
| S1 | 1 hour, any day | 24 hours, or stop the affected function | Before any further test sign-off |
| S2 | 4 working hours | 5 working days | Before release |
| S3 | 2 working days | Next planned release | Planned |
| S4 | 5 working days | Backlog | Backlog |

### 12.5 Release blocking rules

Per 01 C9:

1. No open S1 or S2 defect at release.
2. Every Must requirement for the release passes its tests.
3. Every `rul` test for rules active in the release passes, with no skips.
4. The product owner signs off.

Also:

- A Should requirement may ship failing only with the product owner's written agreement (01 Priority table).
- Open S3 defects are allowed if listed in the release notes with a fix date. More than 20 open S3 (assumption) needs a product owner decision.
- A defect cannot be downgraded to pass a gate without the product owner's recorded reason.

---

## 13. Release acceptance criteria

### 13.1 R1 Escrow and portal

| Criterion | Evidence |
|---|---|
| All R1 Must FRs pass (ACC, ORD, PAY, CASE, RPT, GEO, ESC R1 items, EVD R1 items, NTF, ADM, AUD, ANL-003, DPR) | Test report against section 4 |
| All R1 business rules pass: RUL-01 to RUL-07, RUL-11 (staff side), RUL-15 (release block where a dispute flag exists), RUL-17, RUL-20 | `rul` suite report, zero skips |
| State-transition matrix for Case and Escrow passes | Section 5 report |
| J-01, J-02 and J-08 E2E pass, including unhappy paths | Section 6 report |
| R1 NFRs pass: PERF-01 to 04, AVL-01 to 03, SEC-01 to 05, PRIV-01 and 02, USE-01 and 02, ACC-01, OBS-01, MNT-01, LOC-01, AUD-01 | Section 7 report; NFR-AVL-01 confirmed after first live month |
| Penetration test retest letter: no open high or critical | Tester's letter |
| ASVS L2 checklist complete | Checklist |
| Usability test with 5 diaspora users passes | Usability report |
| UAT-01 to UAT-12 accepted | Signed forms |
| OAT-01 to OAT-08 pass | OAT report |
| PAT-01 to PAT-05, PAT-09 and PAT-10 pass with the escrow bank, or escrow features ship switched off with manual tracking (AS-02) | Bank acceptance letter or product owner decision |
| Insurer approves the platform report process (01 B4) | Insurer letter |
| Data location confirmed (Q-07) and Data Protection Commission registration in place `[TO VERIFY]` | Lawyer's note |
| Configurable values set and approved: fresh-search window (Q-04), retention periods (Q-08) | Configuration export signed by lawyer |
| No open S1 or S2 | Defect report |

### 13.2 R2 Construction

| Criterion | Evidence |
|---|---|
| All R2 Must FRs pass (MOB, BLD, ESC-010, EVD-006, LST Musts, DSP Musts, PTR-002, PRJ-005) and all R1 regression | Test report |
| R2 business rules pass: RUL-08, RUL-09, RUL-10, RUL-11, RUL-12, RUL-13, RUL-14, RUL-15, RUL-16, RUL-18, RUL-19, RUL-21, plus R1 rules regression | `rul` suite report |
| Milestone, Listing and Dispute state matrices pass; Escrow matrix re-run with partial releases and freezes | Section 5 report |
| J-03 to J-07 E2E pass | Section 6 report |
| NFR-PERF-05, NFR-MNT-02, NFR-SCL-01 pass; R1 NFRs regression | Section 7 report |
| Device matrix and TC-FLD tests pass; field trials meet exit criteria | Section 9 report; field trial notes |
| Penetration test covers app and partner API; no open high or critical | Tester's letter |
| UAT-13 to UAT-22 accepted | Signed forms |
| OAT-09 and OAT-10 pass | OAT report |
| PAT-06 to PAT-08 and PAT-10 pass | Bank acceptance letter |
| Act 1047 position known before listings go live (C-04, Q-06); badge validity set (Q-05) | Lawyer's note |
| Professional indemnity covers inspections and project funds (AS-09), or those lines stay off | Insurer letter |
| No open S1 or S2 | Defect report |

### 13.3 R3 Scale

| Criterion | Evidence |
|---|---|
| All R3 Must FRs pass (CTY) and R1 and R2 regression | Test report |
| Records module (REC) and family and stool listings tested; Should items failing have written agreement | Test report |
| Nigerian configuration passes the full RUL suite under Nigerian settings | `rul` suite report per country |
| Country data location tests pass (TC-CTY-002-01, -02; OAT-11) | Infrastructure audit |
| Nigeria manual verification phase and 90-day validation completed before software is localised (Fidero core design rule) | Validation report |
| Penetration test including country separation | Tester's letter |
| UAT-23 and UAT-24 accepted | Signed forms |
| Partner acceptance with the Nigerian escrow partner (PAT-01 to PAT-06 equivalents) | Partner letter |
| No open S1 or S2 | Defect report |

### 13.4 Go/no-go checklist

Used at the go/no-go meeting for every release. Chair: product owner. Attendees: engineering lead, QA lead, operations lead, reviewer lead. Each line is yes or no. Any "no" on lines 1 to 10 means no-go unless the product owner records a written exception that the rule allows (only Should items and S3 or lower defects).

| # | Check | Yes/No |
|---|---|---|
| 1 | All Must requirements for this release pass | |
| 2 | All active `rul` tests pass with zero skips | |
| 3 | No open S1 or S2 defects | |
| 4 | Penetration test retest: no open high or critical findings | |
| 5 | UAT scenarios for this release signed | |
| 6 | OAT passed, including a restore drill in the last 30 days (assumption) | |
| 7 | Partner acceptance signed by the escrow bank, or escrow features switched off by decision | |
| 8 | Release candidate on staging is the exact build going to production (same artefact hashes) | |
| 9 | Rollback plan tested for this release | |
| 10 | Required legal and insurer approvals on file (scope text, insurer, Act 843, Act 1047 where relevant) | |
| 11 | Configurable values set to approved numbers, exported and signed | |
| 12 | Support and operations staff trained; runbooks in document 06 updated | |
| 13 | Monitoring dashboards and alerts live in production | |
| 14 | Release notes list known S3 and S4 defects and Should items not delivered | |
| 15 | Communication to clients and partners ready | |

Decision: Go / No-go. Signed by product owner, date and time.

After go-live: production smoke tests within 1 hour; heightened monitoring for 7 days (assumption); first release instruction after go-live is watched end to end by the engineering lead and a reviewer.

---

## 14. Traceability matrix

Traceability runs BR → F → FR → US → TC. User stories are in document 04; `US-<MODULE>-nnn` implements `FR-<MODULE>-nnn`. Epics are `EP-<MODULE>`. Rules and NFRs have their own tables.

### 14.1 Functional requirements

Read each row left to right: business requirement, feature, functional requirement, user story in document 04, test cases. "Source in 01" is the Source column of document 01. Where that source is a rule or a constraint, the BR column gives the business requirement the rule serves. "Rule and security tests" lists tests in sections 3 and 8 that also cover the FR.


**ACC — Accounts and identity**

| BR | Source in 01 | F | FR | Pri | Rel | US | Test cases | Rule and security tests |
|---|---|---|---|---|---|---|---|---|
| BR-01 | BR-01 | F-01 | FR-ACC-001 | Must | R1 | US-ACC-001 | TC-ACC-001-01, TC-ACC-001-02, TC-ACC-001-03 | — |
| BR-01 | BR-01 | F-01 | FR-ACC-002 | Must | R1 | US-ACC-002 | TC-ACC-002-01, TC-ACC-002-02 | TC-SEC-18 |
| BR-15 | BR-15 | F-01 | FR-ACC-003 | Must | R1 | US-ACC-003 | TC-ACC-003-01, TC-ACC-003-02, TC-ACC-003-03 | TC-SEC-18 |
| BR-05 | BR-05 | F-01 | FR-ACC-004 | Must | R1 | US-ACC-004 | TC-ACC-004-01, TC-ACC-004-02, TC-ACC-004-03 | — |
| BR-02 | RUL-20 | F-01 | FR-ACC-005 | Must | R1 | US-ACC-005 | TC-ACC-005-01, TC-ACC-005-02 | TC-RUL-20-01, TC-RUL-20-02, TC-RUL-20-03, TC-RUL-20-04 |
| BR-03 | BR-03 | F-01 | FR-ACC-006 | Must | R1 | US-ACC-006 | TC-ACC-006-01, TC-ACC-006-02 | — |
| BR-15 | BR-15 | F-01 | FR-ACC-007 | Must | R1 | US-ACC-007 | TC-ACC-007-01, TC-ACC-007-02 | TC-SEC-11 |
| BR-01 | BR-01 | F-01 | FR-ACC-008 | Should | R1 | US-ACC-008 | TC-ACC-008-01, TC-ACC-008-02 | — |
| BR-15 | BR-15 | F-01 | FR-ACC-009 | Must | R1 | US-ACC-009 | TC-ACC-009-01, TC-ACC-009-02 | TC-SEC-19 |
| BR-01 | BR-01 | F-01 | FR-ACC-010 | Should | R1 | US-ACC-010 | TC-ACC-010-01 | — |
| BR-10 | BR-10 | F-01, F-19 | FR-ACC-011 | Should | R2 | US-ACC-011 | TC-ACC-011-01 | TC-SEC-31 |

**ORD — Orders and leads**

| BR | Source in 01 | F | FR | Pri | Rel | US | Test cases | Rule and security tests |
|---|---|---|---|---|---|---|---|---|
| BR-01 | BR-01 | F-02 | FR-ORD-001 | Must | R1 | US-ORD-001 | TC-ORD-001-01, TC-ORD-001-02, TC-ORD-001-03 | — |
| BR-01 | BR-01 | F-02 | FR-ORD-002 | Must | R1 | US-ORD-002 | TC-ORD-002-01, TC-ORD-002-02 | — |
| BR-02 | RUL-04 | F-02 | FR-ORD-003 | Must | R1 | US-ORD-003 | TC-ORD-003-01, TC-ORD-003-02 | TC-RUL-04-01, TC-RUL-04-02, TC-RUL-04-03 |
| BR-01 | BR-01 | F-02 | FR-ORD-004 | Must | R1 | US-ORD-004 | TC-ORD-004-01, TC-ORD-004-02, TC-ORD-004-03 | TC-SEC-20 |
| BR-16 | BR-16 | F-02 | FR-ORD-005 | Should | R1 | US-ORD-005 | TC-ORD-005-01 | — |
| BR-16 | BR-16 | F-02 | FR-ORD-006 | Could | R1 | US-ORD-006 | TC-ORD-006-01, TC-ORD-006-02 | — |
| BR-08 | BR-08 | F-16 | FR-ORD-007 | Should | R2 | US-ORD-007 | TC-ORD-007-01 | — |

**PAY — Payments for Fidero fees**

| BR | Source in 01 | F | FR | Pri | Rel | US | Test cases | Rule and security tests |
|---|---|---|---|---|---|---|---|---|
| BR-01 | BR-01 | F-02 | FR-PAY-001 | Must | R1 | US-PAY-001 | TC-PAY-001-01, TC-PAY-001-02 | TC-SEC-20 |
| BR-15 | BR-15 | F-02 | FR-PAY-002 | Must | R1 | US-PAY-002 | TC-PAY-002-01, TC-PAY-002-02 | — |
| BR-01 | BR-01 | F-02 | FR-PAY-003 | Must | R1 | US-PAY-003 | TC-PAY-003-01, TC-PAY-003-02 | — |
| BR-01 | BR-01 | F-02 | FR-PAY-004 | Should | R1 | US-PAY-004 | TC-PAY-004-01, TC-PAY-004-02 | — |
| BR-05 | RUL-01 | F-02 | FR-PAY-005 | Must | R1 | US-PAY-005 | TC-PAY-005-01, TC-PAY-005-02 | TC-RUL-01-01, TC-RUL-01-02, TC-RUL-01-03, TC-RUL-01-04 |
| BR-16 | BR-16 | F-02 | FR-PAY-006 | Should | R1 | US-PAY-006 | TC-PAY-006-01, TC-PAY-006-02 | — |
| BR-10 | BR-10 | F-19 | FR-PAY-007 | Should | R2 | US-PAY-007 | TC-PAY-007-01 | — |

**CASE — Verification case workflow**

| BR | Source in 01 | F | FR | Pri | Rel | US | Test cases | Rule and security tests |
|---|---|---|---|---|---|---|---|---|
| BR-03 | BR-03 | F-03 | FR-CASE-001 | Must | R1 | US-CASE-001 | TC-CASE-001-01, TC-CASE-001-02, TC-CASE-001-03 | — |
| BR-03 | BR-03 | F-03 | FR-CASE-002 | Must | R1 | US-CASE-002 | TC-CASE-002-01, TC-CASE-002-02 | — |
| BR-03 | BR-03 | F-03 | FR-CASE-003 | Must | R1 | US-CASE-003 | TC-CASE-003-01, TC-CASE-003-02 | — |
| BR-06 | BR-06 | F-03 | FR-CASE-004 | Must | R1 | US-CASE-004 | TC-CASE-004-01, TC-CASE-004-02 | — |
| BR-03 | BR-03 | F-03 | FR-CASE-005 | Must | R1 | US-CASE-005 | TC-CASE-005-01, TC-CASE-005-02 | — |
| BR-03 | BR-03 | F-03 | FR-CASE-006 | Must | R1 | US-CASE-006 | TC-CASE-006-01, TC-CASE-006-02 | — |
| BR-01 | BR-01 | F-03, F-06 | FR-CASE-007 | Must | R1 | US-CASE-007 | TC-CASE-007-01, TC-CASE-007-02 | — |
| BR-03 | BR-03 | F-03, F-06 | FR-CASE-008 | Must | R1 | US-CASE-008 | TC-CASE-008-01, TC-CASE-008-02 | — |
| BR-03 | RUL-17 | F-03 | FR-CASE-009 | Must | R1 | US-CASE-009 | TC-CASE-009-01, TC-CASE-009-02 | TC-RUL-17-01, TC-RUL-17-02, TC-RUL-17-03, TC-RUL-17-04 |
| BR-03 | RUL-17 | F-03 | FR-CASE-010 | Must | R1 | US-CASE-010 | TC-CASE-010-01, TC-CASE-010-02 | TC-RUL-17-01, TC-RUL-17-02, TC-RUL-17-03, TC-RUL-17-04, TC-SEC-29 |
| BR-16 | BR-16 | F-03 | FR-CASE-011 | Should | R1 | US-CASE-011 | TC-CASE-011-01 | — |
| BR-03 | BR-03 | F-03 | FR-CASE-012 | Should | R1 | US-CASE-012 | TC-CASE-012-01, TC-CASE-012-02 | — |
| BR-07 | BR-07 | F-09 | FR-CASE-013 | Should | R1 | US-CASE-013 | TC-CASE-013-01 | — |
| BR-05 | RUL-07 | F-03, F-08 | FR-CASE-014 | Must | R1 | US-CASE-014 | TC-CASE-014-01, TC-CASE-014-02 | TC-RUL-07-01, TC-RUL-07-02, TC-RUL-07-03, TC-RUL-07-04 |
| BR-01 | BR-01 | F-06 | FR-CASE-015 | Should | R1 | US-CASE-015 | TC-CASE-015-01 | TC-SEC-23 |

**RPT — Report builder**

| BR | Source in 01 | F | FR | Pri | Rel | US | Test cases | Rule and security tests |
|---|---|---|---|---|---|---|---|---|
| BR-02 | BR-02 | F-04 | FR-RPT-001 | Must | R1 | US-RPT-001 | TC-RPT-001-01, TC-RPT-001-02 | — |
| BR-02 | BR-02 | F-04 | FR-RPT-002 | Must | R1 | US-RPT-002 | TC-RPT-002-01, TC-RPT-002-02 | — |
| BR-02 | RUL-02 | F-04 | FR-RPT-003 | Must | R1 | US-RPT-003 | TC-RPT-003-01, TC-RPT-003-02 | TC-RUL-02-01, TC-RUL-02-02, TC-RUL-02-03, TC-RUL-02-04, TC-RUL-02-05 |
| BR-02 | RUL-04 | F-04 | FR-RPT-004 | Must | R1 | US-RPT-004 | TC-RPT-004-01, TC-RPT-004-02 | TC-RUL-04-01, TC-RUL-04-02, TC-RUL-04-03 |
| BR-02 | RUL-20 | F-04 | FR-RPT-005 | Must | R1 | US-RPT-005 | TC-RPT-005-01, TC-RPT-005-02 | TC-RUL-20-01, TC-RUL-20-02, TC-RUL-20-03, TC-RUL-20-04 |
| BR-02 | RUL-03 | F-04 | FR-RPT-006 | Must | R1 | US-RPT-006 | TC-RPT-006-01, TC-RPT-006-02 | TC-RUL-03-01, TC-RUL-03-02, TC-RUL-03-03, TC-RUL-03-04 |
| BR-06 | BR-06 | F-04 | FR-RPT-007 | Must | R1 | US-RPT-007 | TC-RPT-007-01, TC-RPT-007-02 | — |
| BR-06 | BR-06 | F-04 | FR-RPT-008 | Should | R1 | US-RPT-008 | TC-RPT-008-01, TC-RPT-008-02 | TC-SEC-25 |
| BR-05 | BR-05 | F-04, F-08 | FR-RPT-009 | Must | R1 | US-RPT-009 | TC-RPT-009-01, TC-RPT-009-02 | — |
| BR-02 | BR-02 | F-04 | FR-RPT-010 | Must | R1 | US-RPT-010 | TC-RPT-010-01, TC-RPT-010-02 | — |
| BR-15 | BR-15 | F-04 | FR-RPT-011 | Could | R1 | US-RPT-011 | TC-RPT-011-01, TC-RPT-011-02 | — |

**GEO — Geospatial checks**

| BR | Source in 01 | F | FR | Pri | Rel | US | Test cases | Rule and security tests |
|---|---|---|---|---|---|---|---|---|
| BR-04 | BR-04 | F-05 | FR-GEO-001 | Must | R1 | US-GEO-001 | TC-GEO-001-01, TC-GEO-001-02 | — |
| BR-04 | BR-04 | F-05 | FR-GEO-002 | Must | R1 | US-GEO-002 | TC-GEO-002-01, TC-GEO-002-02 | — |
| BR-04 | BR-04 | F-05 | FR-GEO-003 | Must | R1 | US-GEO-003 | TC-GEO-003-01, TC-GEO-003-02 | — |
| BR-04 | BR-04 | F-05 | FR-GEO-004 | Must | R1 | US-GEO-004 | TC-GEO-004-01, TC-GEO-004-02 | — |
| BR-04 | BR-04 | F-05 | FR-GEO-005 | Should | R1 | US-GEO-005 | TC-GEO-005-01 | — |
| BR-02 | BR-02 | F-05 | FR-GEO-006 | Should | R1 | US-GEO-006 | TC-GEO-006-01 | — |
| BR-10 | RUL-13 | F-24 | FR-GEO-007 | Could | R2 | US-GEO-007 | TC-GEO-007-01 | TC-RUL-13-01, TC-RUL-13-02, TC-RUL-13-03 |
| BR-04 | BR-04 | F-05 | FR-GEO-008 | Could | R1 | US-GEO-008 | TC-GEO-008-01 | — |

**ESC — Escrow tracking**

| BR | Source in 01 | F | FR | Pri | Rel | US | Test cases | Rule and security tests |
|---|---|---|---|---|---|---|---|---|
| BR-05 | BR-05 | F-08 | FR-ESC-001 | Must | R1 | US-ESC-001 | TC-ESC-001-01, TC-ESC-001-02 | — |
| BR-05 | BR-05 | F-08 | FR-ESC-002 | Must | R1 | US-ESC-002 | TC-ESC-002-01, TC-ESC-002-02 | — |
| BR-05 | RUL-01 | F-08 | FR-ESC-003 | Must | R1 | US-ESC-003 | TC-ESC-003-01, TC-ESC-003-02 | TC-RUL-01-01, TC-RUL-01-02, TC-RUL-01-03, TC-RUL-01-04, TC-SEC-21 |
| BR-05 | BR-05 | F-08 | FR-ESC-004 | Must | R1 | US-ESC-004 | TC-ESC-004-01, TC-ESC-004-02 | TC-SEC-05 |
| BR-05 | BR-05 | F-08 | FR-ESC-005 | Must | R1 | US-ESC-005 | TC-ESC-005-01, TC-ESC-005-02 | — |
| BR-05, BR-12 | RUL-06, RUL-07, RUL-15 | F-08 | FR-ESC-006 | Must | R1 | US-ESC-006 | TC-ESC-006-01, TC-ESC-006-02, TC-ESC-006-03, TC-ESC-006-04 | TC-RUL-06-01, TC-RUL-06-02, TC-RUL-06-03, TC-RUL-06-04, TC-RUL-07-01, TC-RUL-07-02, TC-RUL-07-03, TC-RUL-07-04, TC-RUL-15-01, TC-RUL-15-02, TC-RUL-15-03, TC-RUL-15-04 |
| BR-05 | RUL-05 | F-08 | FR-ESC-007 | Must | R1 | US-ESC-007 | TC-ESC-007-01, TC-ESC-007-02 | TC-RUL-05-01, TC-RUL-05-02, TC-RUL-05-03, TC-RUL-05-04, TC-RUL-05-05, TC-SEC-01 |
| BR-05 | BR-05 | F-08 | FR-ESC-008 | Must | R1 | US-ESC-008 | TC-ESC-008-01, TC-ESC-008-02, TC-ESC-008-03 | TC-SEC-04 |
| BR-05 | BR-05 | F-08 | FR-ESC-009 | Must | R1 | US-ESC-009 | TC-ESC-009-01, TC-ESC-009-02 | TC-SEC-05 |
| BR-08, BR-09 | BR-08, BR-09 | F-08, F-16, F-17, F-18 | FR-ESC-010 | Must | R2 | US-ESC-010 | TC-ESC-010-01, TC-ESC-010-02 | — |
| BR-05 | BR-05 | F-23 | FR-ESC-011 | Should | R2 | US-ESC-011 | TC-ESC-011-01, TC-ESC-011-02 | — |
| BR-05 | BR-05 | F-23 | FR-ESC-012 | Could | R2 | US-ESC-012 | TC-ESC-012-01 | — |
| BR-05 | RUL-05 | F-08 | FR-ESC-013 | Must | R1 | US-ESC-013 | TC-ESC-013-01, TC-ESC-013-02 | TC-RUL-05-01, TC-RUL-05-02, TC-RUL-05-03, TC-RUL-05-04, TC-RUL-05-05 |

**EVD — Evidence store**

| BR | Source in 01 | F | FR | Pri | Rel | US | Test cases | Rule and security tests |
|---|---|---|---|---|---|---|---|---|
| BR-06 | BR-06 | F-07 | FR-EVD-001 | Must | R1 | US-EVD-001 | TC-EVD-001-01, TC-EVD-001-02 | — |
| BR-06 | BR-06 | F-07 | FR-EVD-002 | Must | R1 | US-EVD-002 | TC-EVD-002-01, TC-EVD-002-02, TC-EVD-002-03 | — |
| BR-15 | BR-15 | F-07 | FR-EVD-003 | Must | R1 | US-EVD-003 | TC-EVD-003-01, TC-EVD-003-02 | TC-SEC-12 |
| BR-06 | C-08 | F-07 | FR-EVD-004 | Must | R1 | US-EVD-004 | TC-EVD-004-01, TC-EVD-004-02 | — |
| BR-15 | BR-15 | F-07 | FR-EVD-005 | Must | R1 | US-EVD-005 | TC-EVD-005-01, TC-EVD-005-02 | TC-SEC-22 |
| BR-08 | RUL-08 | F-07, F-15 | FR-EVD-006 | Must | R2 | US-EVD-006 | TC-EVD-006-01, TC-EVD-006-02 | TC-RUL-08-01, TC-RUL-08-02, TC-RUL-08-03, TC-RUL-08-04 |

**MOB — Milestone app**

| BR | Source in 01 | F | FR | Pri | Rel | US | Test cases | Rule and security tests |
|---|---|---|---|---|---|---|---|---|
| BR-08 | BR-08 | F-15 | FR-MOB-001 | Must | R2 | US-MOB-001 | TC-MOB-001-01, TC-MOB-001-02 | — |
| BR-08 | RUL-08 | F-15 | FR-MOB-002 | Must | R2 | US-MOB-002 | TC-MOB-002-01, TC-MOB-002-02 | TC-RUL-08-01, TC-RUL-08-02, TC-RUL-08-03, TC-RUL-08-04, TC-SEC-07 |
| BR-08 | BR-08 | F-15 | FR-MOB-003 | Must | R2 | US-MOB-003 | TC-MOB-003-01, TC-MOB-003-02 | TC-SEC-08 |
| BR-06 | BR-06 | F-15 | FR-MOB-004 | Must | R2 | US-MOB-004 | TC-MOB-004-01, TC-MOB-004-02 | TC-SEC-06, TC-SEC-10 |
| BR-08 | C-08 | F-15 | FR-MOB-005 | Must | R2 | US-MOB-005 | TC-MOB-005-01, TC-MOB-005-02, TC-MOB-005-03 | — |
| BR-08 | BR-08 | F-15 | FR-MOB-006 | Must | R2 | US-MOB-006 | TC-MOB-006-01, TC-MOB-006-02 | — |
| BR-08 | RUL-09 | F-15 | FR-MOB-007 | Must | R2 | US-MOB-007 | TC-MOB-007-01, TC-MOB-007-02 | TC-RUL-09-01, TC-RUL-09-02, TC-RUL-09-03, TC-RUL-09-04 |
| BR-08 | C-08 | F-15 | FR-MOB-008 | Must | R2 | US-MOB-008 | TC-MOB-008-01, TC-MOB-008-02 | — |
| BR-15 | BR-15 | F-15 | FR-MOB-009 | Must | R2 | US-MOB-009 | TC-MOB-009-01, TC-MOB-009-02 | — |
| BR-06 | BR-06 | F-15 | FR-MOB-010 | Should | R2 | US-MOB-010 | TC-MOB-010-01 | — |
| BR-08 | BR-08 | F-15 | FR-MOB-011 | Must | R2 | US-MOB-011 | TC-MOB-011-01, TC-MOB-011-02 | TC-SEC-06, TC-SEC-08, TC-SEC-09 |

**BLD — Construction, off-plan and buildings**

| BR | Source in 01 | F | FR | Pri | Rel | US | Test cases | Rule and security tests |
|---|---|---|---|---|---|---|---|---|
| BR-08 | BR-08 | F-16 | FR-BLD-001 | Must | R2 | US-BLD-001 | TC-BLD-001-01, TC-BLD-001-02 | — |
| BR-08 | BR-08 | F-16 | FR-BLD-002 | Must | R2 | US-BLD-002 | TC-BLD-002-01, TC-BLD-002-02 | — |
| BR-08 | BR-08 | F-16 | FR-BLD-003 | Must | R2 | US-BLD-003 | TC-BLD-003-01, TC-BLD-003-02 | — |
| BR-08 | RUL-10 | F-16 | FR-BLD-004 | Must | R2 | US-BLD-004 | TC-BLD-004-01, TC-BLD-004-02 | TC-RUL-10-01, TC-RUL-10-02, TC-RUL-10-03, TC-RUL-10-04 |
| BR-08 | BR-08 | F-16 | FR-BLD-005 | Must | R2 | US-BLD-005 | TC-BLD-005-01, TC-BLD-005-02 | — |
| BR-08 | RUL-09 | F-16 | FR-BLD-006 | Must | R2 | US-BLD-006 | TC-BLD-006-01, TC-BLD-006-02 | TC-RUL-09-01, TC-RUL-09-02, TC-RUL-09-03, TC-RUL-09-04 |
| BR-08 | RUL-18 | F-16 | FR-BLD-007 | Must | R2 | US-BLD-007 | TC-BLD-007-01, TC-BLD-007-02 | TC-RUL-18-01, TC-RUL-18-02, TC-RUL-18-03 |
| BR-08 | RUL-19 | F-16 | FR-BLD-008 | Must | R2 | US-BLD-008 | TC-BLD-008-01, TC-BLD-008-02 | TC-RUL-19-01, TC-RUL-19-02, TC-RUL-19-03 |
| BR-08 | BR-08 | F-16 | FR-BLD-009 | Must | R2 | US-BLD-009 | TC-BLD-009-01, TC-BLD-009-02 | — |
| BR-12 | BR-12 | F-16 | FR-BLD-010 | Must | R2 | US-BLD-010 | TC-BLD-010-01, TC-BLD-010-02 | — |
| BR-09 | BR-09 | F-17 | FR-BLD-011 | Should | R2 | US-BLD-011 | TC-BLD-011-01, TC-BLD-011-02 | — |
| BR-08 | BR-08 | F-16 | FR-BLD-012 | Must | R2 | US-BLD-012 | TC-BLD-012-01, TC-BLD-012-02 | — |
| BR-08 | BR-08 | F-27 | FR-BLD-013 | Could | R3 | US-BLD-013 | TC-BLD-013-01 | — |

**PRJ — Project funds**

| BR | Source in 01 | F | FR | Pri | Rel | US | Test cases | Rule and security tests |
|---|---|---|---|---|---|---|---|---|
| BR-09 | BR-09 | F-18 | FR-PRJ-001 | Should | R2 | US-PRJ-001 | TC-PRJ-001-01 | — |
| BR-09 | BR-09 | F-18 | FR-PRJ-002 | Should | R2 | US-PRJ-002 | TC-PRJ-002-01, TC-PRJ-002-02 | — |
| BR-09 | RUL-21 | F-18 | FR-PRJ-003 | Should | R2 | US-PRJ-003 | TC-PRJ-003-01, TC-PRJ-003-02 | TC-RUL-21-01, TC-RUL-21-02, TC-RUL-21-03, TC-RUL-21-04 |
| BR-09 | BR-09 | F-18 | FR-PRJ-004 | Should | R2 | US-PRJ-004 | TC-PRJ-004-01 | — |
| BR-09 | BR-09 | F-18 | FR-PRJ-005 | Must | R2 | US-PRJ-005 | TC-PRJ-005-01, TC-PRJ-005-02 | — |

**LST — Verified listings**

| BR | Source in 01 | F | FR | Pri | Rel | US | Test cases | Rule and security tests |
|---|---|---|---|---|---|---|---|---|
| BR-10 | BR-10 | F-19 | FR-LST-001 | Should | R2 | US-LST-001 | TC-LST-001-01 | TC-SEC-23 |
| BR-10 | RUL-12 | F-19 | FR-LST-002 | Must | R2 | US-LST-002 | TC-LST-002-01, TC-LST-002-02 | TC-RUL-12-01, TC-RUL-12-02, TC-RUL-12-03, TC-RUL-12-04 |
| BR-10 | RUL-14 | F-19 | FR-LST-003 | Must | R2 | US-LST-003 | TC-LST-003-01, TC-LST-003-02 | TC-RUL-14-01, TC-RUL-14-02 |
| BR-10 | BR-10 | F-19 | FR-LST-004 | Should | R2 | US-LST-004 | TC-LST-004-01 | — |
| BR-10 | BR-10 | F-19 | FR-LST-005 | Should | R2 | US-LST-005 | TC-LST-005-01, TC-LST-005-02 | — |
| BR-10 | RUL-13 | F-19 | FR-LST-006 | Must | R2 | US-LST-006 | TC-LST-006-01, TC-LST-006-02 | TC-RUL-13-01, TC-RUL-13-02, TC-RUL-13-03 |
| BR-10 | BR-10 | F-19 | FR-LST-007 | Should | R2 | US-LST-007 | TC-LST-007-01 | — |
| BR-12 | BR-12 | F-19 | FR-LST-008 | Must | R2 | US-LST-008 | TC-LST-008-01, TC-LST-008-02 | — |
| BR-13 | BR-13 | F-26 | FR-LST-009 | Could | R3 | US-LST-009 | TC-LST-009-01 | — |
| BR-10 | BR-10 | F-19 | FR-LST-010 | Should | R2 | US-LST-010 | TC-LST-010-01, TC-LST-010-02 | — |

**RAT — Track records and ratings**

| BR | Source in 01 | F | FR | Pri | Rel | US | Test cases | Rule and security tests |
|---|---|---|---|---|---|---|---|---|
| BR-12 | BR-12 | F-20 | FR-RAT-001 | Should | R2 | US-RAT-001 | TC-RAT-001-01 | — |
| BR-12 | BR-12 | F-20 | FR-RAT-002 | Should | R2 | US-RAT-002 | TC-RAT-002-01, TC-RAT-002-02 | — |
| BR-12 | BR-12 | F-20 | FR-RAT-003 | Should | R2 | US-RAT-003 | TC-RAT-003-01 | — |
| BR-12 | BR-12 | F-20 | FR-RAT-004 | Should | R2 | US-RAT-004 | TC-RAT-004-01 | — |

**DSP — Disputes**

| BR | Source in 01 | F | FR | Pri | Rel | US | Test cases | Rule and security tests |
|---|---|---|---|---|---|---|---|---|
| BR-12 | BR-12 | F-21 | FR-DSP-001 | Must | R2 | US-DSP-001 | TC-DSP-001-01, TC-DSP-001-02 | — |
| BR-05, BR-12 | RUL-15 | F-21 | FR-DSP-002 | Must | R2 | US-DSP-002 | TC-DSP-002-01, TC-DSP-002-02 | TC-RUL-15-01, TC-RUL-15-02, TC-RUL-15-03, TC-RUL-15-04 |
| BR-12 | BR-12 | F-21 | FR-DSP-003 | Must | R2 | US-DSP-003 | TC-DSP-003-01, TC-DSP-003-02 | — |
| BR-12 | BR-12 | F-21 | FR-DSP-004 | Must | R2 | US-DSP-004 | TC-DSP-004-01, TC-DSP-004-02 | — |
| BR-12 | BR-12 | F-21 | FR-DSP-005 | Should | R2 | US-DSP-005 | TC-DSP-005-01 | — |

**PTR — Partner API**

| BR | Source in 01 | F | FR | Pri | Rel | US | Test cases | Rule and security tests |
|---|---|---|---|---|---|---|---|---|
| BR-11 | BR-11 | F-22 | FR-PTR-001 | Should | R2 | US-PTR-001 | TC-PTR-001-01, TC-PTR-001-02 | TC-SEC-16 |
| BR-11 | RUL-16 | F-22 | FR-PTR-002 | Must | R2 | US-PTR-002 | TC-PTR-002-01, TC-PTR-002-02 | TC-RUL-16-01, TC-RUL-16-02, TC-RUL-16-03, TC-SEC-15 |
| BR-11 | BR-11 | F-22 | FR-PTR-003 | Could | R2 | US-PTR-003 | TC-PTR-003-01 | — |
| BR-11 | BR-11 | F-22 | FR-PTR-004 | Should | R2 | US-PTR-004 | TC-PTR-004-01 | TC-SEC-16 |

**NTF — Notifications**

| BR | Source in 01 | F | FR | Pri | Rel | US | Test cases | Rule and security tests |
|---|---|---|---|---|---|---|---|---|
| BR-01 | BR-01 | F-10 | FR-NTF-001 | Must | R1 | US-NTF-001 | TC-NTF-001-01, TC-NTF-001-02 | — |
| BR-01 | BR-01 | F-10 | FR-NTF-002 | Must | R1 | US-NTF-002 | TC-NTF-002-01, TC-NTF-002-02 | — |
| BR-03 | BR-03 | F-10, F-03 | FR-NTF-003 | Must | R1 | US-NTF-003 | TC-NTF-003-01, TC-NTF-003-02 | — |
| BR-15 | BR-15 | F-10 | FR-NTF-004 | Must | R1 | US-NTF-004 | TC-NTF-004-01, TC-NTF-004-02 | TC-SEC-17 |
| BR-15 | BR-15 | F-10 | FR-NTF-005 | Should | R1 | US-NTF-005 | TC-NTF-005-01 | — |

**ADM — Administration**

| BR | Source in 01 | F | FR | Pri | Rel | US | Test cases | Rule and security tests |
|---|---|---|---|---|---|---|---|---|
| BR-03 | BR-03 | F-11 | FR-ADM-001 | Must | R1 | US-ADM-001 | TC-ADM-001-01, TC-ADM-001-02 | — |
| BR-01 | BR-01 | F-11 | FR-ADM-002 | Must | R1 | US-ADM-002 | TC-ADM-002-01, TC-ADM-002-02 | — |
| BR-03 | BR-03 | F-11 | FR-ADM-003 | Must | R1 | US-ADM-003 | TC-ADM-003-01, TC-ADM-003-02 | TC-SEC-21 |
| BR-02 | RUL-04 | F-11 | FR-ADM-004 | Must | R1 | US-ADM-004 | TC-ADM-004-01, TC-ADM-004-02 | TC-RUL-04-01, TC-RUL-04-02, TC-RUL-04-03 |
| BR-05, BR-10 | RUL-07, RUL-13 | F-11 | FR-ADM-005 | Must | R1 | US-ADM-005 | TC-ADM-005-01, TC-ADM-005-02 | TC-RUL-07-01, TC-RUL-07-02, TC-RUL-07-03, TC-RUL-07-04, TC-RUL-13-01, TC-RUL-13-02, TC-RUL-13-03 |

**AUD — Audit**

| BR | Source in 01 | F | FR | Pri | Rel | US | Test cases | Rule and security tests |
|---|---|---|---|---|---|---|---|---|
| BR-15 | BR-15 | F-12 | FR-AUD-001 | Must | R1 | US-AUD-001 | TC-AUD-001-01, TC-AUD-001-02 | — |
| BR-15 | BR-15 | F-12 | FR-AUD-002 | Must | R1 | US-AUD-002 | TC-AUD-002-01, TC-AUD-002-02 | TC-SEC-13 |
| BR-15 | BR-15 | F-12 | FR-AUD-003 | Should | R1 | US-AUD-003 | TC-AUD-003-01 | — |
| BR-15 | BR-15 | F-12 | FR-AUD-004 | Should | R1 | US-AUD-004 | TC-AUD-004-01, TC-AUD-004-02 | TC-SEC-14 |

**ANL — Analytics**

| BR | Source in 01 | F | FR | Pri | Rel | US | Test cases | Rule and security tests |
|---|---|---|---|---|---|---|---|---|
| BR-16 | BR-16 | F-13 | FR-ANL-001 | Should | R1 | US-ANL-001 | TC-ANL-001-01 | — |
| BR-16 | BR-16 | F-13 | FR-ANL-002 | Should | R1 | US-ANL-002 | TC-ANL-002-01 | TC-SEC-28 |
| BR-15 | BR-15 | F-13 | FR-ANL-003 | Must | R1 | US-ANL-003 | TC-ANL-003-01, TC-ANL-003-02 | — |

**DPR — Data protection and retention**

| BR | Source in 01 | F | FR | Pri | Rel | US | Test cases | Rule and security tests |
|---|---|---|---|---|---|---|---|---|
| BR-15 | C-02 | F-14 | FR-DPR-001 | Must | R1 | US-DPR-001 | TC-DPR-001-01, TC-DPR-001-02 | — |
| BR-15 | C-02 | F-14 | FR-DPR-002 | Must | R1 | US-DPR-002 | TC-DPR-002-01, TC-DPR-002-02 | — |
| BR-15 | C-02 | F-14 | FR-DPR-003 | Must | R1 | US-DPR-003 | TC-DPR-003-01, TC-DPR-003-02 | — |
| BR-15 | C-02 | F-14 | FR-DPR-004 | Must | R1 | US-DPR-004 | TC-DPR-004-01, TC-DPR-004-02 | — |
| BR-15 | C-02 | F-14 | FR-DPR-005 | Must | R1 | US-DPR-005 | TC-DPR-005-01, TC-DPR-005-02 | TC-SEC-28 |

**REC — Records programme**

| BR | Source in 01 | F | FR | Pri | Rel | US | Test cases | Rule and security tests |
|---|---|---|---|---|---|---|---|---|
| BR-13 | BR-13 | F-25 | FR-REC-001 | Should | R3 | US-REC-001 | TC-REC-001-01 | — |
| BR-13 | BR-13 | F-25 | FR-REC-002 | Should | R3 | US-REC-002 | TC-REC-002-01, TC-REC-002-02 | — |
| BR-13 | BR-13 | F-25 | FR-REC-003 | Should | R3 | US-REC-003 | TC-REC-003-01 | — |
| BR-13 | BR-13 | F-25 | FR-REC-004 | Should | R3 | US-REC-004 | TC-REC-004-01 | — |

**CTY — Multi-country**

| BR | Source in 01 | F | FR | Pri | Rel | US | Test cases | Rule and security tests |
|---|---|---|---|---|---|---|---|---|
| BR-14 | BR-14 | F-28 | FR-CTY-001 | Must | R3 | US-CTY-001 | TC-CTY-001-01, TC-CTY-001-02 | — |
| BR-14 | BR-14 | F-28 | FR-CTY-002 | Must | R3 | US-CTY-002 | TC-CTY-002-01, TC-CTY-002-02 | TC-SEC-32 |
| BR-14 | BR-14 | F-28 | FR-CTY-003 | Must | R3 | US-CTY-003 | TC-CTY-003-01, TC-CTY-003-02 | — |

### 14.2 Business rules

| RUL | BR | F | FR | Rule tests | Other tests |
|---|---|---|---|---|---|
| RUL-01 | BR-05 | F-02, F-08 | FR-PAY-005, FR-ESC-003 | TC-RUL-01-01, TC-RUL-01-02, TC-RUL-01-03, TC-RUL-01-04 | TC-E2E-J02-01 |
| RUL-02 | BR-02 | F-04 | FR-RPT-003 | TC-RUL-02-01, TC-RUL-02-02, TC-RUL-02-03, TC-RUL-02-04, TC-RUL-02-05 | TC-E2E-J01-05 |
| RUL-03 | BR-02 | F-04 | FR-RPT-006 | TC-RUL-03-01, TC-RUL-03-02, TC-RUL-03-03, TC-RUL-03-04 | TC-STM-CASE-07, TC-STM-CASE-12 |
| RUL-04 | BR-02 | F-04, F-11 | FR-ORD-003, FR-RPT-004, FR-ADM-004 | TC-RUL-04-01, TC-RUL-04-02, TC-RUL-04-03 | TC-SEC-24 |
| RUL-05 | BR-05 | F-08 | FR-ESC-007, FR-ESC-013 | TC-RUL-05-01, TC-RUL-05-02, TC-RUL-05-03, TC-RUL-05-04, TC-RUL-05-05 | TC-STM-ESC-04, TC-STM-ESC-18, TC-SEC-01, TC-SEC-02, TC-SEC-03 |
| RUL-06 | BR-05 | F-08 | FR-ESC-006 | TC-RUL-06-01, TC-RUL-06-02, TC-RUL-06-03, TC-RUL-06-04 | TC-STM-ESC-13, TC-E2E-J02-02 |
| RUL-07 | BR-05 | F-03, F-08 | FR-CASE-014, FR-ESC-006, FR-ADM-005 | TC-RUL-07-01, TC-RUL-07-02, TC-RUL-07-03, TC-RUL-07-04 | TC-E2E-J02-03 |
| RUL-08 | BR-08 | F-15 | FR-EVD-006, FR-MOB-002 | TC-RUL-08-01, TC-RUL-08-02, TC-RUL-08-03, TC-RUL-08-04 | TC-SEC-07, TC-E2E-J03-04 |
| RUL-09 | BR-08 | F-15, F-16 | FR-MOB-007, FR-BLD-006 | TC-RUL-09-01, TC-RUL-09-02, TC-RUL-09-03, TC-RUL-09-04 | TC-STM-MIL-14, TC-E2E-J03-03 |
| RUL-10 | BR-08 | F-16 | FR-BLD-004 | TC-RUL-10-01, TC-RUL-10-02, TC-RUL-10-03, TC-RUL-10-04 | TC-SEC-27, TC-E2E-J03-05 |
| RUL-11 | BR-05, BR-08 | F-08, F-16 | FR-ESC-007, FR-BLD-005 | TC-RUL-11-01, TC-RUL-11-02, TC-RUL-11-03 | TC-STM-MIL-16 |
| RUL-12 | BR-10 | F-19 | FR-LST-002 | TC-RUL-12-01, TC-RUL-12-02, TC-RUL-12-03, TC-RUL-12-04 | TC-STM-LST-03, TC-E2E-J04-02 |
| RUL-13 | BR-10 | F-19, F-24 | FR-GEO-007, FR-LST-006, FR-ADM-005 | TC-RUL-13-01, TC-RUL-13-02, TC-RUL-13-03 | TC-STM-LST-06, TC-E2E-J04-03 |
| RUL-14 | BR-10 | F-19 | FR-LST-003 | TC-RUL-14-01, TC-RUL-14-02 | TC-LST-003-01 |
| RUL-15 | BR-05, BR-12 | F-08, F-21 | FR-ESC-006, FR-DSP-002 | TC-RUL-15-01, TC-RUL-15-02, TC-RUL-15-03, TC-RUL-15-04 | TC-STM-ESC-06, TC-STM-ESC-07, TC-STM-ESC-14, TC-E2E-J07-01 |
| RUL-16 | BR-11 | F-22 | FR-PTR-002 | TC-RUL-16-01, TC-RUL-16-02, TC-RUL-16-03 | TC-SEC-15, TC-E2E-J06-02 |
| RUL-17 | BR-03 | F-03 | FR-CASE-009, FR-CASE-010 | TC-RUL-17-01, TC-RUL-17-02, TC-RUL-17-03, TC-RUL-17-04 | TC-E2E-J01-08 |
| RUL-18 | BR-08 | F-16 | FR-BLD-007 | TC-RUL-18-01, TC-RUL-18-02, TC-RUL-18-03 | TC-E2E-J03-06 |
| RUL-19 | BR-08 | F-16 | FR-BLD-008 | TC-RUL-19-01, TC-RUL-19-02, TC-RUL-19-03 | TC-BLD-008-02 |
| RUL-20 | BR-02 | F-01, F-04 | FR-ACC-005, FR-RPT-005 | TC-RUL-20-01, TC-RUL-20-02, TC-RUL-20-03, TC-RUL-20-04 | TC-SEC-26 |
| RUL-21 | BR-09 | F-18 | FR-PRJ-003 | TC-RUL-21-01, TC-RUL-21-02, TC-RUL-21-03, TC-RUL-21-04 | TC-E2E-J05-03 |

### 14.3 Non-functional requirements

| NFR | BR | Rel | Tests | Other evidence |
|---|---|---|---|---|
| NFR-PERF-01 | BR-01 | R1 | TC-NFR-PERF-01-01 | TC-E2E-J01-07, TC-LST-010-01 |
| NFR-PERF-02 | BR-01 | R1 | TC-NFR-PERF-02-01 | — |
| NFR-PERF-03 | BR-01 | R1 | TC-NFR-PERF-03-01, TC-NFR-PERF-03-02 | — |
| NFR-PERF-04 | BR-01 | R1 | TC-NFR-PERF-04-01 | — |
| NFR-PERF-05 | BR-01 | R2 | TC-NFR-PERF-05-01 | TC-FLD-12 |
| NFR-AVL-01 | BR-15 | R1 | TC-NFR-AVL-01-01, TC-NFR-AVL-01-02 | — |
| NFR-AVL-02 | BR-15 | R1 | TC-NFR-AVL-02-01 | OAT-02 |
| NFR-AVL-03 | BR-15 | R1 | TC-NFR-AVL-03-01 | — |
| NFR-SEC-01 | BR-15 | R1 | TC-NFR-SEC-01-01 | — |
| NFR-SEC-02 | BR-15 | R1 | TC-NFR-SEC-02-01 | — |
| NFR-SEC-03 | BR-15 | R1 | TC-NFR-SEC-03-01 | Section 8.5 |
| NFR-SEC-04 | BR-15 | R1 | TC-NFR-SEC-04-01 | TC-SEC-30, OAT-05 |
| NFR-SEC-05 | BR-15 | R1 | TC-NFR-SEC-05-01 | Section 8.3, TC-SEC-01 to TC-SEC-32 |
| NFR-PRIV-01 | BR-15 | R1 | TC-NFR-PRIV-01-01 | TC-CTY-002-01, OAT-11 |
| NFR-PRIV-02 | BR-15 | R1 | TC-NFR-PRIV-02-01 | — |
| NFR-USE-01 | BR-01 | R1 | TC-NFR-USE-01-01 | UAT-01, section 10.2 |
| NFR-USE-02 | BR-01 | R1 | TC-NFR-USE-02-01, TC-NFR-USE-02-02 | — |
| NFR-A11Y-01 | BR-01 | R1 | TC-NFR-A11Y-01-01, TC-NFR-A11Y-01-02 | Section 10.1 |
| NFR-OBS-01 | BR-15 | R1 | TC-NFR-OBS-01-01 | OAT-03 |
| NFR-MNT-01 | BR-14 | R1 | TC-NFR-MNT-01-01 | — |
| NFR-MNT-02 | BR-14 | R2 | TC-NFR-MNT-02-01 | TC-CTY-001-01 |
| NFR-SCL-01 | BR-10, BR-08 | R2 | TC-NFR-SCL-01-01 | — |
| NFR-LOC-01 | BR-14 | R1 | TC-NFR-LOC-01-01 | — |
| NFR-AUD-01 | BR-15 | R1 | TC-NFR-AUD-01-01 | TC-AUD-004-01, OAT-07 |

### 14.4 Journeys

| Journey | Features | E2E tests | UAT |
|---|---|---|---|
| J-01 Order a land report | F-01, F-02, F-03, F-04, F-05, F-06, F-07, F-10 | TC-E2E-J01-01 to TC-E2E-J01-08 | UAT-01 to UAT-06 |
| J-02 Buy through escrow | F-08, F-03 (fresh search) | TC-E2E-J02-01 to TC-E2E-J02-07 | UAT-07, UAT-08 |
| J-03 Build with milestone payments | F-15, F-16, F-08 | TC-E2E-J03-01 to TC-E2E-J03-07 | UAT-13 to UAT-16 |
| J-04 Buy a verified listing | F-19, F-08 | TC-E2E-J04-01 to TC-E2E-J04-04 | UAT-17, UAT-18 |
| J-05 Fund a project | F-18 | TC-E2E-J05-01 to TC-E2E-J05-04 | UAT-19 |
| J-06 Bank collateral check | F-22 | TC-E2E-J06-01 to TC-E2E-J06-04 | UAT-20 |
| J-07 Raise and resolve a dispute | F-21 | TC-E2E-J07-01 to TC-E2E-J07-04 | UAT-21 |
| J-08 Verify an existing building | F-09, F-08 | TC-E2E-J08-01 to TC-E2E-J08-03 | UAT-09 |

### 14.5 Coverage summary

Counts are of test cases written in this version of the document.

| Item | In document 01 | Covered by at least one test | Notes |
|---|---|---|---|
| Functional requirements | 159 (108 Must, 43 Should, 8 Could) | 159 | Every Must FR has at least one positive and one negative test |
| Business rules | 21 | 21 | Every rule has 2 to 5 tests; 78 in total |
| Non-functional requirements | 24 | 24 | 28 tests |
| State models | 5 | 5 | 79 named tests plus the generated matrix test per model |
| Journeys | 8 | 8 | 41 E2E tests |
| Business requirements | 16 | 16 | Through FRs in section 14.1 |

| Test type | Count |
|---|---|
| Functional (`TC-<MODULE>-nnn-xx`) | 295 |
| Business rule (`TC-RUL-nn-xx`) | 78 |
| State transition (`TC-STM-…`) | 79 |
| End-to-end journey (`TC-E2E-J0n-xx`) | 41 |
| Non-functional (`TC-NFR-…`) | 28 |
| Security threat (`TC-SEC-nn`) | 32 |
| Mobile and field (`TC-FLD-nn`) | 13 |
| User acceptance (`UAT-nn`) | 24 |
| Operational acceptance (`OAT-nn`) | 11 |
| Partner acceptance (`PAT-nn`) | 10 |
| **Total** | **611** |

Functional test cases by release: R1 182, R2 100, R3 13.

Functional coverage by module:

| Module | FRs | Must FRs | FRs with a test | Functional test cases | Automated (Y) |
|---|---|---|---|---|---|
| ACC | 11 | 8 | 11 | 23 | 22 |
| ORD | 7 | 4 | 7 | 14 | 14 |
| PAY | 7 | 4 | 7 | 13 | 13 |
| CASE | 15 | 11 | 15 | 28 | 28 |
| RPT | 11 | 9 | 11 | 22 | 21 |
| GEO | 8 | 4 | 8 | 12 | 11 |
| ESC | 13 | 11 | 13 | 28 | 28 |
| EVD | 6 | 6 | 6 | 13 | 13 |
| MOB | 11 | 10 | 11 | 22 | 19 |
| BLD | 13 | 11 | 13 | 25 | 25 |
| PRJ | 5 | 1 | 5 | 8 | 8 |
| LST | 10 | 4 | 10 | 16 | 16 |
| RAT | 4 | 0 | 4 | 5 | 5 |
| DSP | 5 | 4 | 5 | 9 | 9 |
| PTR | 4 | 1 | 4 | 6 | 6 |
| NTF | 5 | 4 | 5 | 9 | 9 |
| ADM | 5 | 5 | 5 | 10 | 10 |
| AUD | 4 | 2 | 4 | 7 | 7 |
| ANL | 3 | 1 | 3 | 4 | 4 |
| DPR | 5 | 5 | 5 | 10 | 10 |
| REC | 4 | 0 | 4 | 5 | 5 |
| CTY | 3 | 3 | 3 | 6 | 4 |
| **Total** | **159** | **108** | **159** | **295** | **287** |

### 14.6 Keeping traceability current

- Each automated test carries markers for its TC ID and the FR, RUL or NFR it covers (for example `@pytest.mark.req("FR-ESC-006")`).
- A CI script builds this matrix from the markers and from document 01. It fails when an FR or RUL in 01 has no test, or when a test points to an ID that does not exist.
- When document 01 or document 04 changes, the QA lead updates this document in the same pull request.

---

## 15. Test metrics and reporting

### 15.1 Metrics

| Metric | Definition | Target (assumption) | Source |
|---|---|---|---|
| Requirement coverage | Share of FRs, RULs and NFRs for the release with at least one passing test | 100% of Must; 100% of RUL | Traceability script |
| Rule suite health | `rul` tests passing, skipped, failing | 100% pass, 0 skipped | CI |
| Line coverage, core API | Lines covered by automated tests | At least 80% (NFR-MNT-01) | coverage.py |
| Mutation score on release and verdict code | Killed mutants divided by all mutants | No surviving mutants in decision functions | Mutation tool |
| Test pass rate per cycle | Passed divided by executed | Trend up; 100% of P1 at exit | Test management |
| Defects found by severity and module | Count per week | Trend down before release | Defect tracker |
| Defect escape rate | Defects found in production divided by all defects for the release | Under 10% `[TO VERIFY]` after first release | Defect tracker |
| Defect age | Days open, by severity | Within SLAs in 12.4 | Defect tracker |
| Flaky test rate | Tests that pass and fail on the same code | Under 2% of tests; none in `rul` | CI history |
| Pipeline time | PR gate duration | Under 15 minutes (assumption) | CI |
| Automation share | Automated test cases divided by all test cases | About 85% of functional cases (section 14.5 shows 287 of 295 marked Y) | This document |
| Performance trend | p75 page time on 3G, p95 API latency | Within NFR-PERF targets every night | Lighthouse CI, k6 |
| Field evidence loss | Evidence items captured but never received | Zero | App telemetry and server |
| Fraud flag accuracy | Flags upheld by reviewers divided by all flags | Watched, no target until R2 data `[TO VERIFY]` | Reviewer decisions |

### 15.2 Reports

| Report | Audience | Frequency | Content |
|---|---|---|---|
| CI dashboard | Developers | Every run | Gate status, failing tests, coverage, security findings |
| Weekly quality report | Product owner, engineering lead | Weekly during build | Coverage by module, defects by severity, risks, blocked tests, rule suite status |
| Test cycle exit report | Product owner | End of each system test cycle | Executed, passed, failed, blocked; open defects; exit criteria met or not |
| UAT report | Product owner, participants | End of UAT | Scenarios accepted or rejected, defects, signed forms |
| Release readiness report | Go/no-go meeting | Before each release | Section 13 criteria with evidence links; go/no-go checklist |
| Post-release review | Founder, team | 30 days after go-live | Escaped defects, incidents, metrics against targets, lessons |

All reports state that figures are working numbers from the test tools, not audited data.

---

## 16. Issues found in document 01

These points make a requirement ambiguous, untestable or inconsistent. Document 01 is not changed here. The product owner decides each point. Until then, tests use the "test assumption" column and are marked for review.

| # | Where in 01 | Issue | Effect on testing | Test assumption until resolved |
|---|---|---|---|---|
| 1 | RUL-02, FR-RPT-003 vs `docs/operations/verification-report-template.md` | 01 says green is blocked if any section 4 to 10 is red. The template says sections 4 to 9. | Section 10 (occupation and ground conditions) behaviour is unclear | Use 01 (4 to 10). TC-RUL-02-03 tests section 10. Template should be aligned |
| 2 | RUL-07, Q-04; RUL-12, RUL-13, Q-05; FR-ADM-005 | Fresh-search window, listing report age and badge validity are `[TO VERIFY]`. It is also unclear whether "within N days" includes day N. | Boundary tests cannot use fixed numbers | Tests read the configured value; limit is inclusive |
| 3 | RUL-12 vs RUL-13, FR-LST-002 | RUL-12 uses "less than N days old" for publishing. RUL-13 and FR-LST-006 use a separate badge validity. It is unclear whether these are one value or two. | Expiry and publish tests may conflict | Treat as two configurable values |
| 4 | FR-ESC-006 (R1) vs DSP module (R2) | FR-ESC-006 blocks release on an open dispute in R1, but disputes are built in R2. | RUL-15 cannot be fully tested in R1 | R1 has a simple "dispute flag" on an escrow, set by a reviewer; full DSP in R2 |
| 5 | C8 Escrow model | No transition for a dispute raised after "Release approved" and before the bank pays. No "Frozen to Cancelled" path when a dispute ends in cancellation. No state for partial releases (FR-ESC-010). Cancellation from "Ready to release" is not listed. | Invalid-transition tests may reject behaviour the business wants | TC-STM-ESC-17 expects send blocked and state Frozen; partial releases tracked per milestone, escrow stays Funded |
| 6 | C8 Milestone model vs FR-BLD-005 | FR-BLD-005 lists "inspection scheduled"; C8 does not. C8 has no "Returned to Submitted" (resubmit) transition, no Frozen state for disputes, and no defect holdback or retention states. | Matrix test cannot match both | TC-STM-MIL-11 expects resubmission allowed; freeze applies as a flag |
| 7 | C8 Milestone: "approval window lapses" vs RUL-11 | A lapsed window counts as client approval. RUL-11 says a client approves. The window length is `[TO VERIFY]`. | Unclear whether a payment can go without explicit client approval | Lapse is recorded as a distinct approval type and shown to the client |
| 8 | RUL-11 vs C8 Escrow and FR-ESC | RUL-11 says "a client approves" before release, but the purchase escrow model and ESC FRs have no client approval step. | Cannot test client approval on purchase escrows | Client acceptance of escrow terms counts; ask whether a client approval step is needed before purchase release |
| 9 | Milestone schedule (mobilisation) vs RUL-09 | Mobilisation is released on contract signing and site handover. RUL-09 says no milestone release without an inspector's pass. | Mobilisation release would fail RUL-09 tests | Ask whether mobilisation needs a site handover inspection or is exempt |
| 10 | C8 Listing model | No path for a reserved listing whose fresh search fails (only "lapses or fails" back to Live). A failed fresh search probably should suspend the listing, not return it to Live. No path for expiry or suspension while Reserved. | TC-STM-LST-10 and TC-E2E-J04-04 expectations conflict | Failed fresh search suspends the listing |
| 11 | C8 Dispute model | "Evidence to Decision" only on deadline, so a dispute with all evidence in must wait. "Any to Referred" could include Closed. No state for a missed decision deadline. | Early decision and post-closure tests unclear | Early move not allowed; Closed cannot be referred |
| 12 | RUL-15, FR-DSP-002 | "Every release linked to it" is not defined. A dispute on one milestone may or may not freeze later milestones or the whole project. | TC-RUL-15-03 expectation unclear | Freeze the disputed item only; reviewer can widen the freeze |
| 13 | FR-NTF-004 | "Money amounts above a threshold": threshold not set, and not in FR-ADM-005's configurable values. | Leakage test needs a number | Configurable; default is no amounts in SMS or WhatsApp |
| 14 | FR-MOB-011 | "Large gap" between device and server time and "inconsistent image metadata" are not defined. Not in FR-ADM-005. | Fraud flag tests need thresholds | Configurable gap value; metadata rules listed in document 02 `[TO VERIFY]` |
| 15 | FR-PRJ-004 | "Configurable amount" for enhanced checks is not in FR-ADM-005. | Boundary test needs the setting | Treat as configurable in ADM |
| 16 | FR-ACC-003 | "Any user who approves a release": unclear whether a client who approves a milestone is such a user. | MFA tests for clients unclear | Clients approving milestones or conditions need MFA |
| 17 | FR-ACC-007 vs C2 roles and FR-CASE-005 | "Each user sees only assigned or owned items" conflicts with case managers' queues and reviewers' cross-case work. | Authorisation matrix needs per-role scope | Case managers and reviewers see all cases in their country; others only assigned or owned |
| 18 | FR-ESC-004, FR-ESC-009 | A single case manager can mark an escrow Funded or Released by manual entry. This is a high-risk single-person action. | Threat TC-SEC-05 has no requirement to test against | Recommend second-person check on manual bank entries |
| 19 | FR-ESC-008 | "Signed by the approvers" does not say how (digital signature, certificate, the bank's portal). | Signature tests depend on the method | Server-side signature with per-approver keys; confirm with the bank (PAT-02) |
| 20 | FR-ADM-003 | Changing a partner's bank account details is a fraud risk but has no two-person rule. | TC-ADM-003-02 has no requirement to test against | Recommend second admin approval and alert |
| 21 | FR-RPT-006 | Says "a second Fidero reviewer" though only one Fidero reviewer is involved alongside the lawyer. RUL-03 does not say whether the lawyer can be a Fidero employee. | Separation tests unclear | Two different persons; lawyer and reviewer roles cannot be held by one person on the same case |
| 22 | FR-ACC-005, RUL-20 | No rule for a licence that expires between signing and release. | TC-RUL-20-04 expectation unclear | Signature valid if licence valid at signing |
| 23 | NFR-PERF-03 | "10 times the expected R1 load": expected load is not quantified. | No load model | Derive from R1 targets (300 reports, 50 escrows) and staff count `[TO VERIFY]` |
| 24 | NFR-USE-01 | Unclear whether all 5 users must finish under 10 minutes, or the median. | Pass criterion ambiguous | All 5, unaided |
| 25 | NFR-USE-02 | "Reading age of 12" does not name a measure. | Automated check needs a formula | Pick one formula and confirm with a manual review |
| 26 | NFR-PERF-05 | Cold or warm start not stated. "Install size" could mean download or installed size. | Measurement ambiguous | Cold start; installed size |
| 27 | FR-LST-010 vs NFR-PERF-01 | FR-LST-010 says "under 3 seconds on 3G" without a percentile or network profile. | Two different targets | Use NFR-PERF-01 profile and p75 |
| 28 | FR-NTF-003, FR-DSP-003 | "Working days" has no holiday calendar named (Ghana public holidays, later Nigeria). | Deadline maths untestable without it | Holiday calendar as configuration per country |
| 29 | FR-RPT-008 | "Anyone" can check a hash. No limit on what the checker reveals or how often it can be used. | Privacy and enumeration risk | Match result only; rate limited (TC-RPT-008-02, TC-SEC-25) |
| 30 | FR-PTR-002 vs FR-PTR-001, J-06 | FR-PTR-002 mentions returning the full report with specific consent, but no FR defines how a full report is delivered through the API. J-06 says without consent only "report exists" is returned, while FR-PTR-001 also has "report in progress". | API contract tests unclear | Without consent: exists or in progress only; full report by signed link with specific consent |
| 31 | NFR-AVL-01 | "Announced maintenance" has no limit. | Availability could be met by announcing long windows | Cap maintenance at a set number of hours per month `[TO VERIFY]` |
| 32 | NFR-MNT-01 | "Core API" is not defined. | Coverage scope unclear | All Django apps in the core API repository, excluding migrations and generated code |
| 33 | RUL-10, FR-BLD-004 | "Recorded link" between inspector and contractor: sources of link data not defined. | Conflict tests need fixtures | Employment, payee, shared bank account, shared phone, declared relationship |
| 34 | RUL-17, FR-CASE-009 | The content of the risk screen and who sets the "disputed" flag are not defined. | Tests can only check that a screen exists | Screen is a configurable checklist; case manager or reviewer sets the flag |
| 35 | FR-CTY-002, NFR-PRIV-01, Q-07 | Data location rules are unknown. | Location tests cannot pass or fail | Tests check the data location register only until rules are set |
| 36 | FR-DPR-004, C5.2, Q-08 | Retention periods are `[TO VERIFY]`. | Retention job tests use placeholder periods | Configurable per data class |

