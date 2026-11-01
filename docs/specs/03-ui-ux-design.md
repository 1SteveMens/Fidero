# 03 — UI/UX Design Specification

Information architecture, user flows, wireframes, interaction and content rules, design system and accessibility for the three Fidero front ends: the `portal` web app, the `backoffice` web app and the Android field app (called the milestone app in R2 planning; it serves contractors, inspectors, runners, surveyors, carers and errand agents).

| Item | Value |
|---|---|
| Document | 03 of 6 in `docs/specs/` |
| Version | 0.2 |
| Date | 1 November 2026 |
| Status | Draft. For review. Not yet baselined |
| Owner | Product designer, for the founder as product owner |
| Source of truth | `01-requirements-and-product-specification.md` v0.3 (personas, features, journeys, rules, FR and NFR IDs, state models) |
| Other sources | `README.md`, `docs/decisions/2026-11-01-diaspora-platform.md`, `docs/operations/verification-report-template.md`, `docs/operations/milestone-schedule.md`, `docs/product/architecture.md` |
| Companion | `03-prototype/index.html`, a clickable prototype with sample data |

Every figure in this document is a working assumption, not verified data. Unknown numbers are marked `[TO VERIFY]`. Names, places, prices, dates and references in wireframes and the prototype are samples.

### Change history

| Version | Date | Change |
|---|---|---|
| 0.1 | 31 October 2026 | First draft against 01 v0.1. |
| 0.2 | 1 November 2026 | Redesign for 01 v0.3 and the decision record `docs/decisions/2026-11-01-diaspora-platform.md`: Fidero is the diaspora's trusted agent at home. Adds the principles "Pay the institution, not the relative" and "Country is configuration"; the unified home dashboard (F-35) as the portal home with sections for Property, Family, and Projects and errands; a country selector at onboarding; screens SCR-PTL-36 to SCR-PTL-54, SCR-BO-27 to SCR-BO-32 and SCR-MOB-14 to SCR-MOB-18; flows for J-09 to J-12 with error states; wireframes W-25 to W-36; content rules for who gets paid (RUL-22), rent (RUL-24) and insurer products (RUL-25); components CMP-25 to CMP-32; prototype flows G and H. Client approval added to the escrow flow and tracker (01 v0.2 Escrow state model). Section 11.2 refreshed against 01 v0.3: I-01, I-02, I-03, I-04, I-06, I-07, I-08, I-09, I-10, I-12, I-13 and I-14 closed; I-17 to I-24 added. Design assumptions DA-07 to DA-10 added; DA-06 retired. |

## 0. How this document traces to 01

- Every screen has a stable ID: `SCR-PTL-nn` (portal), `SCR-BO-nn` (back office), `SCR-MOB-nn` (Android app). IDs are never reused.
- Every reusable component has an ID: `CMP-nn`.
- Every screen lists the 01 IDs it satisfies: functional requirements (`FR-`), features (`F-`), journeys (`J-`) and rules (`RUL-`). This document creates no new requirement IDs.
- Section 10 holds the full screen-to-requirement table. Document 05 can test each screen against it.
- Where 01 is unclear or inconsistent, this document makes a design assumption, marks it `DA-nn`, and lists the gap in section 11.2. It does not edit 01.

### Design assumptions used in this document

| ID | Assumption | Why |
|---|---|---|
| DA-01 | Clients confirm approvals (escrow terms, milestone approval, cedi re-pricing) with a one-time code. This is the client's step, not a release. | FR-ACC-003 asks for MFA for "any user who approves a release". RUL-11 says the client approves. See issue I-05. |
| DA-02 | Prices show in the client's chosen display currency, but the charge is made in USD for cards and GHS for mobile money. | Confirmed by FR-ORD-002 in 01 v0.3 (issue I-09 closed). Kept as the display rule. |
| DA-03 | Money uses ISO codes (`USD 450.00`, `GHS 5,400.00`), not symbols. | `$` is ambiguous for clients in the US and Canada. Screen readers read codes reliably. |
| DA-04 | The hash check computes the PDF hash in the browser. The PDF never leaves the user's device. | Privacy. FR-RPT-008 says "anyone" can check. |
| DA-05 | The back office is used on laptops by office staff, and on phones by runners, surveyors and lawyers for their own tasks. | FR-CASE-006. |
| DA-06 | Retired. 01 v0.3 NFR-A11Y-01 now holds the field app to WCAG 2.2 AA from R2. | Issue I-06 closed. The ID is not reused. |
| DA-07 | A family member who confirms a care visit does not need an account. They get a one-time link by SMS or WhatsApp that opens a page with one button and a 4-digit code the carer reads out. A call to Fidero is the fallback. | FR-CARE-004 allows "a one-tap code, a call or the app". Many elderly relatives will not install an app. See issue I-19. |
| DA-08 | The held balance for institution payments, care visits and errands (FR-ESC-014) is shown as "held at Partner Bank for you", with a running statement. It is never called a wallet or a Fidero balance. | RUL-01 and B2.2. The money is at the bank. |
| DA-09 | The country chosen at onboarding is the country where the things are (the plot, the hospital, the parent), not where the client lives. A client can add a second country later and the dashboard groups by country. | FR-CTY-001: every case, payment and user belongs to one country. Clients abroad live elsewhere by definition. |
| DA-10 | When a runner pays an institution in person (FR-FEE-006), the client's screen says so plainly: "Paid in person by a Fidero runner to [institution]. Receipt attached. Cash drawn from Partner Bank against a signed voucher." | It is the one place where cash moves. The client must see it is an exception, not the rule. See issue I-20. |

---

## 1. Design principles

The principles come from 01 section B2. Each one changes what a user sees.

| Principle (01 B2) | What it means in the UI | Where it shows |
|---|---|---|
| **Evidence before money** (B2.1) | No money action without the evidence shown beside it. A release button is never live while a gate is open. Every gate says what is missing in words. | Escrow tracker (SCR-PTL-17), release approval (SCR-BO-12), milestone approval (SCR-PTL-23), condition checklist (CMP-08) |
| **Fidero never holds the money** (B2.2) | Purchase, build and project money screens show only the partner bank's name and account. Fidero's own payment page is only for Fidero fees and says so. A fixed line on every money screen: "Your money is held by [bank], not by Fidero." | Bank instructions (SCR-PTL-18), payment (SCR-PTL-10), money display (CMP-17) |
| **Plain status, always** (B2.3) | Every case, escrow, milestone, listing and dispute has one status sentence at the top: what happened, when, what comes next and by when. Reading age 12. | Status timeline (CMP-06), all trackers |
| **Built for a slow phone** (B2.4) | Phone layout first. System fonts. Small pages. Static map first, live map on tap. Thumbnails before full images. Forms save as you go. The app works offline. | Performance budgets (section 7.2), offline banner (CMP-13) |
| **One engine** (B2.5) | Land, building, construction, off-plan, project funds, institution payments, care visits, property management, errands and events share the same components: tracker, conditions, evidence, approvals, statement. A new line is new content, not a new screen design. | Shared components in section 6.4; home dashboard (SCR-PTL-36) |
| **People stay in the loop** (B2.6) | Licensed people sign their sections with name and licence number shown. Two named Fidero approvers on every release, visible to the client. | Report viewer (SCR-PTL-14), approval card (CMP-10) |
| **Safety first** (B2.7) | A risk screen blocks assignment to a disputed plot until two people are named. Field staff can log an incident from any task in two taps. The app never shows the client's personal data to field staff. | Risk screen (SCR-BO-05), task detail (SCR-BO-04), app task (SCR-MOB-12) |
| **Pay the institution, not the relative** (B2.8) | Every payment screen names the payee and its verified account: "Paid to Komfo Anokye Teaching Hospital, account ending 4471." There is no screen on which a relative, a carer or an agent can be chosen as a payee. Verified institutions carry a visible verified status with the date. A payment to an unverified payee is blocked in words. | Institution card (CMP-26), payee line (CMP-30), pay an invoice (SCR-PTL-40), institution verification (SCR-BO-27) |
| **Country is configuration** (B2.9) | The client picks a country at onboarding. Currency, holiday calendar, institution types, errand catalogue, partner bank and legal texts follow from it. No screen hard-codes "Ghana", "GHS" or "Lands Commission"; they come from the country record. The dashboard shows the country on every item. | Country selector (CMP-29, SCR-PTL-37), country configuration (SCR-BO-29), home dashboard (SCR-PTL-36) |

### Design rules that follow

1. One primary action per screen.
2. Status first, detail second. The answer to "what is happening?" is above the fold on a 360 px wide phone.
3. Never colour alone. Verdicts and states use icon, word and colour together.
4. Never a dead end. Every error, empty and blocked state says what to do next.
5. No hidden money. Every amount shows its currency code and who holds it.
6. Irreversible actions need a clear summary and a deliberate confirm (section 5.3). Reversible actions use undo.
7. Name who gets paid. Every released or planned payment shows the payee's name and the last four digits of its verified account (RUL-22). Rent says it goes to the owner's own account (RUL-24). Insurance says whose policy it is (RUL-25).
8. Country on every object. Each case, payment, property and visit shows its country and currency, taken from configuration.

---

## 2. Information architecture

### 2.1 Portal sitemap (Next.js, phone first)

```text
portal
├── Public
│   ├── Home ................................ SCR-PTL-01
│   ├── How it works / prices ............... SCR-PTL-01 (sections)
│   ├── Check a report (hash check) ......... SCR-PTL-15
│   ├── Listings search and map (R2) ........ SCR-PTL-26
│   │   └── Listing detail (R2) ............. SCR-PTL-27
│   ├── Insurer product pages (R2) .......... SCR-PTL-51
│   ├── Sign up ............................. SCR-PTL-02
│   │   └── Choose a country ................ SCR-PTL-37
│   ├── Sign in ............................. SCR-PTL-03
│   └── Confirm a visit (one-time link) ..... SCR-PTL-45
└── Signed in
    ├── Home dashboard (F-35) ............... SCR-PTL-36
    │   (sections: Property · Family · Projects and errands;
    │    SCR-PTL-05 "Home: my things" is superseded by this screen)
    ├── Identity check ...................... SCR-PTL-04
    ├── PROPERTY
    │   ├── Order a report (4 steps) ........ SCR-PTL-06 to 09
    │   ├── Pay Fidero's fee ................ SCR-PTL-10
    │   ├── Payment result and receipt ...... SCR-PTL-11
    │   ├── Case tracker .................... SCR-PTL-12
    │   │   ├── Document request ............ SCR-PTL-13
    │   │   ├── Messages .................... SCR-PTL-19
    │   │   ├── Report viewer ............... SCR-PTL-14
    │   │   └── Rate this case (R2) ......... SCR-PTL-33
    │   ├── Escrow offer and terms .......... SCR-PTL-16
    │   ├── Escrow tracker .................. SCR-PTL-17
    │   ├── Bank payment instructions ....... SCR-PTL-18
    │   ├── Start a build (R2) .............. SCR-PTL-25
    │   ├── Build dashboard (R2) ............ SCR-PTL-22
    │   │   ├── Milestone detail and approval SCR-PTL-23
    │   │   └── Variation approval .......... SCR-PTL-24
    │   ├── Listings: reserve (R2) .......... SCR-PTL-28
    │   ├── Selling (R2): list, my listings . SCR-PTL-31, 32
    │   └── Property management (R2)
    │       ├── Register a property, inspection  SCR-PTL-46
    │       ├── Property dashboard: tenancy, rent, repairs  SCR-PTL-47
    │       ├── Repair quotes and approval .. SCR-PTL-48
    │       └── Tenant view (tenant role) ... SCR-PTL-54
    ├── FAMILY
    │   ├── Add a family member ............. SCR-PTL-38
    │   ├── Add an institution, verification status  SCR-PTL-39
    │   ├── Pay an invoice .................. SCR-PTL-40
    │   ├── Recurring fee schedule .......... SCR-PTL-41
    │   ├── Family-member statement ......... SCR-PTL-42
    │   ├── Care plan setup (R2) ............ SCR-PTL-43
    │   ├── Care visits and alerts (R2) ..... SCR-PTL-44
    │   ├── Insurer product page (R2) ....... SCR-PTL-51
    │   └── Policy wallet (R2) .............. SCR-PTL-52
    ├── PROJECTS AND ERRANDS
    │   ├── Project fund dashboard (R2) ..... SCR-PTL-30
    │   ├── Errand catalogue (R2) ........... SCR-PTL-49
    │   ├── Errand checklist and progress (R2)  SCR-PTL-50
    │   └── Event budget (R3) ............... SCR-PTL-53
    ├── Disputes (R2) ....................... SCR-PTL-29
    ├── Records confirmation (R3) ........... SCR-PTL-35
    └── Account
        ├── Profile, notifications, representative, countries .. SCR-PTL-20
        ├── Sharing and consent ............. SCR-PTL-21
        └── My data ......................... SCR-PTL-34
```

The three capitalised groups are the product families in the decision record. The dashboard shows one section per family; a section appears only when the client has something in it. Family lines are offered to every client from R1 (the decision record, "Customer to lead with").

### 2.2 Back office sitemap (web, laptop first, phone for field roles)

```text
backoffice
├── Sign in with second factor .............. SCR-BO-01
├── My work (queue) ......................... SCR-BO-02
├── Cases
│   ├── Case detail with tasks .............. SCR-BO-03
│   ├── Task detail (phone friendly) ........ SCR-BO-04
│   ├── Risk screen and assignment .......... SCR-BO-05
│   ├── Map and overlay results ............. SCR-BO-07
│   ├── Report builder ...................... SCR-BO-08
│   └── Report review and release ........... SCR-BO-09
├── Safety: incident log (restricted) ....... SCR-BO-06
├── Escrow
│   ├── Escrow list ......................... SCR-BO-10
│   ├── Escrow detail and conditions ........ SCR-BO-11
│   ├── Release approval .................... SCR-BO-12
│   └── Bank and fee reconciliation ......... SCR-BO-13
├── Builds (R2)
│   ├── Milestone review and fraud flags .... SCR-BO-14
│   └── Panel: contractors and inspectors ... SCR-BO-15
├── Listings moderation (R2) ................ SCR-BO-16
├── Disputes (R2) ........................... SCR-BO-17
├── Family lines
│   ├── Institution verification ............ SCR-BO-27
│   ├── Invoice check and payment queue ..... SCR-BO-30
│   └── Carer and agent panel, visit monitoring (R2)  SCR-BO-28
├── Property management desk (R2) ........... SCR-BO-31
├── Errands desk (R2) ....................... SCR-BO-32
├── Records programme (R3) .................. SCR-BO-26
├── Dashboard and exports ................... SCR-BO-23
├── Audit log ............................... SCR-BO-22
└── Admin
    ├── Country configuration ............... SCR-BO-29
    ├── Templates and configuration ......... SCR-BO-18
    ├── Prices, tiers, currencies ........... SCR-BO-19
    ├── Users, roles, licences .............. SCR-BO-20
    ├── Partners and API keys ............... SCR-BO-21
    ├── Notification templates and log ...... SCR-BO-25
    └── Data requests and retention ......... SCR-BO-24
```

The back office carries a country switcher in the top bar for staff who work in more than one country. Everything below it is filtered by the chosen country (FR-ACC-007, FR-CTY-003).

### 2.3 Android field app map (R2, offline first)

```text
field app
├── Sign in and register this phone ......... SCR-MOB-01
├── My jobs ................................. SCR-MOB-02
│   ├── Project and milestone overview ...... SCR-MOB-03
│   │   ├── Evidence checklist .............. SCR-MOB-04
│   │   │   ├── Camera ...................... SCR-MOB-05
│   │   │   └── Check this capture .......... SCR-MOB-06
│   │   └── Submit milestone ................ SCR-MOB-07
│   ├── Inspection checklist (inspector) .... SCR-MOB-09
│   │   ├── Add a defect .................... SCR-MOB-10
│   │   └── Result and submit ............... SCR-MOB-11
│   ├── Case task (runner, surveyor) ........ SCR-MOB-12
│   ├── Care visit (carer)
│   │   ├── Check in at the address ......... SCR-MOB-14
│   │   ├── Plan items and photos ........... SCR-MOB-15
│   │   └── Check out, raise a concern ...... SCR-MOB-16
│   ├── Errand steps and receipts (agent) ... SCR-MOB-17
│   └── Property inspection (inspector) ..... SCR-MOB-18
├── Upload queue ............................ SCR-MOB-08
└── Account, storage, help .................. SCR-MOB-13
```

### 2.4 Navigation model

| Front end | Phone | Laptop | Notes |
|---|---|---|---|
| Portal, public | Top bar: logo, "Listings", "Check a report", "Sign in". Menu button for the rest. | Same items in a horizontal top bar. | Public pages are server rendered and indexable (FR-LST-010). |
| Portal, signed in | Bottom tab bar with up to 5 tabs: **Home** (the dashboard, SCR-PTL-36), **Property**, **Family**, **Projects** (projects and errands), **Account**. | Left side bar with the same items. | A family tab appears only when the client has something in it, or on first use as a prompt. A first-time user sees Home, Property, Family, Account. The old tabs Orders, Escrow and Build become sections inside Property. |
| Back office | Field roles (lawyer, surveyor, runner) get a single "My tasks" list and a top bar. No side bar. | Left side bar grouped by work area. Items filtered by role (FR-ACC-007) and by the chosen country. Global search for case, escrow, listing, institution and person references. | Staff session times out after 30 minutes idle with a warning at 25 (NFR-SEC-02). |
| Android field app | Bottom bar: **Jobs**, **Queue** (with a count badge), **Account**. Linear task flows with a back arrow. A carer sees only today's visits; an errand agent sees only assigned errands. | n/a | Upload state is visible on every screen through the offline banner (CMP-13). |

Wayfinding rules:

- Every signed-in page has a heading that names the object and its reference, such as "Plot 14, Kasoa Millennium City · FID-2027-0142" or "Comfort Mensah · Komfo Anokye Teaching Hospital · FEE-2027-0412".
- Every object shows its country and currency in the reference line, from configuration. A client with one country sees it once, in the dashboard header.
- Breadcrumbs on laptop only. On phone, a back link names the parent: "← Case FID-2027-0142".
- Help is in the same place on every page: a "Get help" link in the page footer and in the account menu (WCAG 2.2 SC 3.2.6).

### 2.5 Screen inventory

Release follows 01. "Roles" uses 01 C2 role names.

#### Portal

| Screen | Name | Purpose | Roles | Rel. | Satisfies |
|---|---|---|---|---|---|
| SCR-PTL-01 | Home and prices | Explain Fidero, show tiers and sample report, start an order | Public | R1 | F-02, FR-ORD-002, FR-ORD-005 |
| SCR-PTL-02 | Sign up | Create account with email and phone, both confirmed by code; privacy notice | Public | R1 | F-01, FR-ACC-001, FR-DPR-001, J-01 |
| SCR-PTL-03 | Sign in | Password or one-time code; lockout message | All portal users | R1 | FR-ACC-002, FR-ACC-009 |
| SCR-PTL-04 | Identity check | Ghana Card or passport check through the provider, or manual upload | Client | R1 | FR-ACC-004, J-01, J-02 |
| SCR-PTL-05 | Home: my things | Superseded by SCR-PTL-36, the home dashboard, in v0.2. ID retired, not reused | - | - | - |
| SCR-PTL-06 | Order step 1: what to check | Land or building; tier; price in display currency | Client | R1 | F-02, F-09, FR-ORD-001, FR-ORD-002, J-01, J-08 |
| SCR-PTL-07 | Order step 2: the plot | Locality, plot number, site plan reference, Ghana Post GPS | Client | R1 | FR-ORD-001, FR-GEO-008, J-01 |
| SCR-PTL-08 | Order step 3: documents and seller | Upload site plan and documents; seller name and contact | Client | R1 | FR-ORD-001, FR-EVD-001, FR-EVD-005, J-01 |
| SCR-PTL-09 | Order step 4: check and agree | Summary, scope statement, terms, lead source, referral code | Client | R1 | FR-ORD-003, FR-ORD-005, FR-ORD-006, RUL-04 |
| SCR-PTL-10 | Pay Fidero's fee | Card or mobile money for the fee only | Client | R1 | FR-PAY-001, FR-PAY-002, FR-PAY-005, RUL-01 |
| SCR-PTL-11 | Payment result | Receipt, case reference, what happens next; failure recovery | Client | R1 | FR-PAY-003, FR-ORD-004, J-01 |
| SCR-PTL-12 | Case tracker | Status sentence, plain-language timeline, requests, messages | Client, representative | R1 | F-06, FR-CASE-007, FR-CASE-008, FR-NTF-001, FR-ACC-008, J-01, J-08 |
| SCR-PTL-13 | Document request | Upload what Fidero asked for | Client | R1 | FR-CASE-008, FR-EVD-001 |
| SCR-PTL-14 | Report viewer | Verdict, reasons, conditions, section verdicts, signatures, PDF, hash, versions | Client | R1 | F-04, FR-RPT-005, FR-RPT-007, FR-RPT-008, FR-RPT-010, J-01 |
| SCR-PTL-15 | Check a report | Anyone checks a PDF against the stored hash | Public | R1 | FR-RPT-008 |
| SCR-PTL-16 | Escrow offer and terms | Offer escrow on green or amber; show conditions from section 11; accept terms | Client, seller | R1 | F-08, FR-ESC-001, FR-ESC-002, FR-RPT-009, J-02 |
| SCR-PTL-17 | Escrow tracker | Deposit, conditions, fresh search, approvals, bank confirmation | Client, seller | R1 | F-08, FR-ESC-004 to FR-ESC-009, RUL-06, RUL-07, J-02 |
| SCR-PTL-18 | Bank payment instructions | The partner bank's details for the purchase price | Client | R1 | FR-ESC-003, RUL-01 |
| SCR-PTL-19 | Messages | Case thread with Fidero | Client | R1 | FR-CASE-015 |
| SCR-PTL-20 | Profile and notifications | Channels, preferences, representative | All portal users | R1 | FR-ACC-008, FR-ACC-010, FR-NTF-001 |
| SCR-PTL-21 | Sharing and consent | Grant and withdraw sharing with partners; case study consent | Client | R1 (case study), R2 (partners) | FR-PTR-002, FR-RPT-011, RUL-16, J-06 |
| SCR-PTL-22 | Build dashboard | Budget against actual, milestones, photo timeline, inspector results, payments | Client, representative | R2 | F-16, FR-BLD-009, J-03 |
| SCR-PTL-23 | Milestone detail and approval | Evidence, inspector result, defects held back, cedi re-pricing, approve | Client | R2 | FR-BLD-005, FR-BLD-006, FR-BLD-007, RUL-09, RUL-11, RUL-18 |
| SCR-PTL-24 | Variation approval | Approve or reject a scope change before work | Client, contractor | R2 | FR-BLD-008, RUL-19 |
| SCR-PTL-25 | Start a build | Pick verified plot, see bill of quantities, pick contractor with track record | Client | R2 | FR-BLD-001, FR-BLD-002, FR-BLD-003, FR-RAT-003 |
| SCR-PTL-26 | Listings search and map | Search, filter, list and map views | Public | R2 | F-19, FR-LST-004, FR-LST-010, J-04 |
| SCR-PTL-27 | Listing detail | Badge, check date, expiry, full report link, track record, reserve | Public; reserve needs sign in | R2 | FR-LST-003, FR-LST-005, FR-RAT-003, RUL-12, RUL-13, RUL-14, J-04 |
| SCR-PTL-28 | Reserve a listing | Start fresh search and escrow | Client | R2 | FR-LST-005, FR-CASE-014, J-04 |
| SCR-PTL-29 | Dispute | Open a dispute; see frozen releases, deadlines, statements, decision | Client, seller, developer, contractor | R2 | F-21, FR-DSP-001 to FR-DSP-004, RUL-15, J-07 |
| SCR-PTL-30 | Project fund dashboard | Budget by stage, checked suppliers, invoices, payments | Client | R2 | F-18, FR-PRJ-001 to FR-PRJ-005, RUL-21, J-05 |
| SCR-PTL-31 | List a property | Submit asset and pay listing fee | Seller, developer | R2 | FR-LST-001, FR-ACC-011, FR-PAY-007 |
| SCR-PTL-32 | My listings | Status, badge expiry, re-verify, sold | Seller, developer | R2 | FR-LST-006, FR-LST-007 |
| SCR-PTL-33 | Rate this case | 1 to 5 rating and comment | Client | R2 | FR-RAT-002 |
| SCR-PTL-34 | My data | See what Fidero holds; ask for a copy or a correction | All portal users | R1 | FR-DPR-003 |
| SCR-PTL-35 | Records confirmation | Authority representative views and confirms records | Authority representative | R3 | FR-REC-004, F-25 |
| SCR-PTL-36 | Home dashboard | Everything the client has running at home in one view: sections for Property, Family, and Projects and errands; one status sentence per item; country shown | Client | R1 | F-35, FR-ACC-012, FR-CASE-007, FR-CTY-001 |
| SCR-PTL-37 | Choose a country | At onboarding: pick the country where the things are; sets currency, calendar and partners | Public (during sign-up), client | R1 | F-28, FR-CTY-001, FR-ACC-001 |
| SCR-PTL-38 | Add a family member | Name, relationship, address, phone; who may confirm visits | Client | R1 | FR-ACC-012, FR-CARE-001 (R2 fields) |
| SCR-PTL-39 | Add an institution | Pick or propose a school, hospital, clinic, pharmacy, agency or utility; see verification status and the verified account | Client | R1 | F-29, FR-FEE-001, RUL-22, J-09 |
| SCR-PTL-40 | Pay an invoice | Upload an invoice or open one the institution sent; see the checks; approve; pay into the partner bank; payee named | Client | R1 | F-29, FR-FEE-002, FR-FEE-003, FR-ESC-014, FR-ESC-015, RUL-11, RUL-22, J-09 |
| SCR-PTL-41 | Recurring fee schedule | Per term or per month; reminder; approve before each payment; enrolment confirmation | Client | R1 | FR-FEE-005, FR-FEE-004, J-09 |
| SCR-PTL-42 | Family-member statement | Invoices, payments, receipts, held balance, running statement; who was paid | Client, representative | R1 | FR-FEE-007, FR-FEE-004, FR-ESC-014, RUL-22, J-09 |
| SCR-PTL-43 | Care plan setup | Address, visits per week, tasks, agreed photos, who confirms | Client | R2 | F-30, FR-CARE-001, J-10 |
| SCR-PTL-44 | Care visits and alerts | Visit cards with check-in and out times, photos, confirmation state; missed, late and unconfirmed alerts; carer concerns | Client, representative | R2 | FR-CARE-003, FR-CARE-005, FR-CARE-006, RUL-23, J-10 |
| SCR-PTL-45 | Confirm a visit | One-time link for the family member: one button plus the carer's code; or "this visit did not happen" | Family member (no account, DA-07) | R2 | FR-CARE-004, RUL-23, J-10 |
| SCR-PTL-46 | Register a property | Address, type, documents; book the condition inspection; see its photos | Client (owner) | R2 | F-31, FR-PMG-001, J-11 |
| SCR-PTL-47 | Property dashboard | Tenancy and rent record, rent due and received into the owner's own account, repairs, inspections, photo timeline | Client (owner), representative | R2 | FR-PMG-002, FR-PMG-003, FR-PMG-006, RUL-24, J-11 |
| SCR-PTL-48 | Repair quotes and approval | Two or more quotes from vetted contractors; approve one; money held; inspection; payment to contractor | Client (owner) | R2 | FR-PMG-004, FR-PMG-005, RUL-11, RUL-22, J-11 |
| SCR-PTL-49 | Errand catalogue | Errands for the country, each with checklist, official fees, Fidero's charge and target time | Client | R2 | F-32, FR-TSK-001, FR-CTY-001, J-12 |
| SCR-PTL-50 | Errand checklist and progress | Upload checklist documents; pay fees into the partner bank; steps with receipts; completion by the resulting document; handover | Client, representative | R2 | FR-TSK-002 to FR-TSK-005, RUL-22, RUL-23, J-12 |
| SCR-PTL-51 | Insurer product page | Health or funeral cover from a named licensed insurer; terms; "A policy from [insurer]. Fidero does not hold the risk."; apply | Public, client | R2 | F-33, FR-INS-001, FR-INS-002, RUL-25 |
| SCR-PTL-52 | Policy wallet | Policy documents, renewal dates, insurer's claim contact; start a claim and track the insurer's response | Client | R2 | FR-INS-003, FR-INS-004, RUL-25 |
| SCR-PTL-53 | Event budget | Event, date, budget, verified vendors, payments against invoices and delivery evidence, receipts | Client | R3 | F-34, FR-EVT-001 to FR-EVT-003, RUL-22 |
| SCR-PTL-54 | Tenant view | The tenant's agreement and rent record; report a repair | Tenant | R2 | FR-PMG-002, FR-PMG-004 |

#### Back office

| Screen | Name | Purpose | Roles | Rel. | Satisfies |
|---|---|---|---|---|---|
| SCR-BO-01 | Sign in | Password plus second factor; idle timeout | All staff and professionals | R1 | FR-ACC-003, FR-ACC-009, NFR-SEC-02 |
| SCR-BO-02 | My work | Queue of cases and tasks by due date; overdue first | Case manager, reviewer, professionals | R1 | FR-CASE-005, FR-NTF-003, J-01 |
| SCR-BO-03 | Case detail | Steps as tasks, owners, due dates, evidence, client status, costs, pause or cancel | Case manager, reviewer | R1 | F-03, FR-CASE-001 to FR-CASE-004, FR-CASE-007, FR-CASE-008, FR-CASE-011, FR-CASE-012, FR-CASE-013 |
| SCR-BO-04 | Task detail | Do one task on a phone: evidence, notes, done; log incident | Lawyer, surveyor, runner | R1 | FR-CASE-004, FR-CASE-006, FR-CASE-010, FR-EVD-001 |
| SCR-BO-05 | Risk screen and assignment | Risk questions; two-person rule on disputed plots | Case manager | R1 | FR-CASE-009, RUL-17 |
| SCR-BO-06 | Incident log | Restricted safety log | Reviewer, administrator | R1 | FR-CASE-010 |
| SCR-BO-07 | Map and overlays | Plot polygon, layer results, overlaps with verified plots, satellite image | Case manager, surveyor | R1 | F-05, FR-GEO-001 to FR-GEO-006 |
| SCR-BO-08 | Report builder | Sections 1 to 14, section verdicts, evidence, signatures, locked scope, conditions | Case manager, lawyer, surveyor | R1 | F-04, FR-RPT-001 to FR-RPT-005, FR-RPT-009, RUL-02, RUL-04, RUL-20 |
| SCR-BO-09 | Report review and release | Two-person review, return with comments, release, new version | Lawyer, reviewer | R1 | FR-RPT-006, FR-RPT-007, FR-RPT-010, RUL-03 |
| SCR-BO-10 | Escrow list | All escrows by state; blocked first | Case manager, reviewer | R1 | F-08, FR-ESC-001, FR-ESC-006 |
| SCR-BO-11 | Escrow detail | Parties, terms, deposit, conditions, fresh search, freeze | Case manager, reviewer | R1 | FR-ESC-001, FR-ESC-002, FR-ESC-004, FR-ESC-005, FR-ESC-006, RUL-06, RUL-07, RUL-15 |
| SCR-BO-12 | Release approval | Two-person approval with gates and second factor; send; bank confirmation | Reviewer with release rights | R1 | FR-ESC-006 to FR-ESC-009, FR-ESC-013, RUL-05, RUL-06, RUL-07 |
| SCR-BO-13 | Reconciliation | Fee settlements against orders; bank statement lines against escrows | Case manager | R1 (fees), R2 (bank file) | FR-PAY-004, FR-PAY-006, FR-ESC-011, F-23 |
| SCR-BO-14 | Milestone review | Submissions, server flags, evidence check, inspector result, approve | Case manager, reviewer | R2 | FR-BLD-005, FR-BLD-010, FR-MOB-011, FR-EVD-006, J-03 |
| SCR-BO-15 | Panel | Contractors and inspectors, documents, conflicts, track record | Case manager, administrator | R2 | FR-BLD-003, FR-BLD-004, FR-RAT-001, RUL-10 |
| SCR-BO-16 | Listings moderation | Publish, suspend, remove; monitoring alerts | Reviewer | R2 | FR-LST-002, FR-LST-006, FR-LST-008, FR-GEO-007, FR-RAT-004 |
| SCR-BO-17 | Dispute management | Deadlines, statements, decision, mediation | Reviewer | R2 | FR-DSP-002 to FR-DSP-005 |
| SCR-BO-18 | Templates and configuration | Versioned templates, condition sets, schedules, locked scope, configurable values | Administrator | R1 | F-11, FR-ADM-001, FR-ADM-004, FR-ADM-005, FR-CTY-001 |
| SCR-BO-19 | Prices and currencies | Tiers, prices, exchange-rate guides | Administrator | R1 | FR-ADM-002 |
| SCR-BO-20 | Users, roles, licences | Invite, assign roles, verify licences | Administrator | R1 | FR-ACC-005, FR-ACC-006, FR-ACC-007 |
| SCR-BO-21 | Partners and API | Banks, professionals, suppliers, API partners, keys, metering | Administrator | R1, R2 | FR-ADM-003, FR-PTR-004 |
| SCR-BO-22 | Audit log | Search the append-only log; chain check | Reviewer, administrator | R1 | F-12, FR-AUD-001 to FR-AUD-004 |
| SCR-BO-23 | Dashboard and exports | A9 metrics; CSV export | Case manager, reviewer, administrator | R1 | F-13, FR-ANL-001 to FR-ANL-003 |
| SCR-BO-24 | Data requests and retention | Access and correction requests; retention; bulk export with two approvals | Administrator | R1 | F-14, FR-DPR-003 to FR-DPR-005 |
| SCR-BO-25 | Notifications | Templates per language and channel; send log | Administrator | R1 | FR-NTF-002, FR-NTF-004, FR-NTF-005 |
| SCR-BO-26 | Records programme | Capture allocation records; revenue share | Case manager, administrator | R3 | F-25, FR-REC-001 to FR-REC-003 |
| SCR-BO-27 | Institution verification | Registration, bank account in the institution's name, named contact; verify, reject, re-verify; second person checks the account | Case manager, reviewer | R1 | FR-FEE-001, FR-ESC-015, FR-ADM-003, RUL-22, J-09 |
| SCR-BO-28 | Carer and agent panel | Vetted carers and errand agents: identity, references, background check, training, track record; live visit monitoring; missed and unconfirmed visits; concerns | Case manager, reviewer, administrator | R2 | FR-CARE-002, FR-CARE-005, FR-CARE-006, FR-TSK-003, RUL-23 |
| SCR-BO-29 | Country configuration | One record per country: currency, holiday calendar, templates, scope statement, overlay layers, partners, licence bodies, legal texts, errand catalogue, data location; copy a country to open a new one | Administrator | R1 (edit), R2 (copy) | F-28, FR-CTY-001, FR-CTY-002, FR-CTY-004, FR-ADM-005 |
| SCR-BO-30 | Invoice check and payment queue | Invoices waiting for checks; institution and family member match; amount; approve for release; runner in-person payment with voucher and receipt | Case manager, reviewer | R1 | FR-FEE-002, FR-FEE-003, FR-FEE-006, FR-ESC-014, FR-ESC-015, RUL-22, J-09 |
| SCR-BO-31 | Property management desk | Managed properties; rent due and late; repair requests and quotes; inspection schedule | Case manager | R2 | FR-PMG-003, FR-PMG-004, FR-PMG-006, RUL-24, J-11 |
| SCR-BO-32 | Errands desk | Errands by step; agency fees paid; receipts; completion check of the resulting document; handover record | Case manager | R2 | FR-TSK-003, FR-TSK-004, FR-TSK-005, J-12 |

#### Android field app

| Screen | Name | Purpose | Roles | Rel. | Satisfies |
|---|---|---|---|---|---|
| SCR-MOB-01 | Sign in | Sign in; register the phone's signing key | Contractor, inspector, runner, surveyor, carer, errand agent | R2 | FR-MOB-001, FR-MOB-004 |
| SCR-MOB-02 | My jobs | Assigned projects, inspections and tasks | Same | R2 | FR-MOB-001 |
| SCR-MOB-03 | Milestone overview | Milestone, status, what is needed | Contractor | R2 | FR-BLD-005, J-03 |
| SCR-MOB-04 | Evidence checklist | Required items from the schedule; progress | Contractor | R2 | FR-MOB-006 |
| SCR-MOB-05 | Camera | In-app capture only; position check | All app roles | R2 | FR-MOB-002, FR-MOB-003, FR-MOB-004, RUL-08 |
| SCR-MOB-06 | Check this capture | Preview, metadata, retake | All app roles | R2 | FR-MOB-003, FR-MOB-004, FR-MOB-008 |
| SCR-MOB-07 | Submit milestone | Confirm and queue | Contractor | R2 | FR-MOB-005, FR-MOB-006, J-03 |
| SCR-MOB-08 | Upload queue | What is waiting, sending, sent | All app roles | R2 | FR-MOB-005, FR-MOB-008, FR-MOB-009 |
| SCR-MOB-09 | Inspection checklist | Milestone checklist items | Inspector | R2 | FR-MOB-007, RUL-09, RUL-10 |
| SCR-MOB-10 | Add a defect | Photos, description, value | Inspector | R2 | FR-MOB-007, FR-BLD-006 |
| SCR-MOB-11 | Inspection result | Pass, pass with defects, fail; submit | Inspector | R2 | FR-MOB-007, RUL-09 |
| SCR-MOB-12 | Case task | Runner or surveyor task with in-app capture | Runner, surveyor | R2 | FR-MOB-010, FR-CASE-010 |
| SCR-MOB-13 | Account and storage | Storage used, encrypted items, help | All app roles | R2 | FR-MOB-008, FR-MOB-009 |
| SCR-MOB-14 | Care visit: check in | Today's visit; check in at the registered address with GPS; distance warning | Carer | R2 | FR-MOB-012, FR-CARE-003, RUL-23, J-10 |
| SCR-MOB-15 | Care visit: plan items | Tick each plan item; agreed photos and readings captured in app | Carer | R2 | FR-CARE-003, FR-MOB-002, FR-MOB-010, J-10 |
| SCR-MOB-16 | Care visit: check out | Check out; read the confirmation code to the family; raise a concern | Carer | R2 | FR-MOB-012, FR-CARE-004, FR-CARE-006, J-10 |
| SCR-MOB-17 | Errand steps | Assigned errand; steps; receipt or acknowledgement captured at each step; handover photo or signature | Errand agent | R2 | FR-TSK-003, FR-TSK-005, FR-MOB-010, J-12 |
| SCR-MOB-18 | Property inspection | Condition inspection or repair inspection with check-in, checklist and photos | Inspector | R2 | FR-PMG-001, FR-PMG-005, FR-MOB-012, J-11 |

---

## 3. User flows

Each flow follows a journey in 01 B6. Error and edge states are drawn as side branches. Rounded nodes are screens; diamonds are decisions; red-path nodes start with "Blocked" or "Failed". State names match 01 C8.

### 3.1 J-01 Order a land verification report (R1)

```mermaid
flowchart TD
    A0(["Ama opens portal on her phone · SCR-PTL-01"]) --> A1["Sign up: email and phone codes · SCR-PTL-02"]
    A1 --> A1c{"Codes confirmed?"}
    A1c -->|"No, code expired"| A1e["Resend code. After 5 failed sign-ins, 15-minute lock · FR-ACC-009"]
    A1e --> A1
    A1c -->|"Yes"| A2["Order step 1: land, tier, price · SCR-PTL-06"]
    A2 --> A3["Step 2: the plot · SCR-PTL-07"]
    A3 --> A3g{"Ghana Post GPS found?"}
    A3g -->|"No or service down"| A3n["Keep going without it. Surveyor confirms on site"]
    A3g -->|"Yes"| A4
    A3n --> A4["Step 3: site plan and seller · SCR-PTL-08"]
    A4 --> A4u{"Upload safe and readable?"}
    A4u -->|"Unsafe file"| A4x["Failed: file rejected by scan. Ask for another file · FR-EVD-005"]
    A4x --> A4
    A4u -->|"No site plan yet"| A4s["Allowed. Case tracker will show a document request"]
    A4u -->|"Yes"| A5
    A4s --> A5["Step 4: check, scope statement, terms · SCR-PTL-09"]
    A5 --> A6["Pay fee by card or mobile money · SCR-PTL-10"]
    A6 --> A6c{"Payment confirmed?"}
    A6c -->|"Declined"| A6d["Failed: card declined. Order saved as draft. Try again or switch to mobile money"]
    A6d --> A6
    A6c -->|"Pending, mobile money prompt not approved"| A6p["Waiting for approval on your phone. We check for 10 minutes · [TO VERIFY]"]
    A6p --> A6c
    A6c -->|"Yes"| A7["Receipt and case reference · SCR-PTL-11. Case state: Paid"]
    A7 --> A8["Operations accepts. Tasks created · SCR-BO-03. State: In progress"]
    A8 --> A9["Tracker shows each step with dates · SCR-PTL-12"]
    A9 --> A9d{"Fidero needs a document?"}
    A9d -->|"Yes"| A9r["Document request on tracker. State: On hold · SCR-PTL-13"]
    A9r --> A9
    A9d -->|"No"| A10{"Identity check passed?"}
    A10 -->|"Not yet"| A10b["Blocked: report ready but cannot be released until identity check passes · FR-ACC-004"]
    A10b --> A11i["Identity check · SCR-PTL-04"]
    A11i --> A10
    A10 -->|"Yes"| A11["Report reviewed by lawyer and reviewer, then released · SCR-BO-09"]
    A11 --> A12["Report viewer: verdict, PDF, hash · SCR-PTL-14"]
    A12 --> A13{"Verdict?"}
    A13 -->|"Green or amber"| A14(["Offer escrow · go to J-02"])
    A13 -->|"Red"| A15(["Explain why not to buy. Offer a check on another plot"])
```

Edge states: a reviewer returns the report (state goes back to In progress; the client sees "Our reviewer asked for one more check. New expected date: 9 April."); a case is cancelled with a refund decision (FR-CASE-012).

### 3.2 J-02 Buy through escrow (R1)

```mermaid
flowchart TD
    B0(["Green or amber report · SCR-PTL-14"]) --> B1["Escrow offer: conditions copied from section 11 · SCR-PTL-16"]
    B1 --> B2{"All parties accept terms?"}
    B2 -->|"Seller does not accept in 10 days · [TO VERIFY]"| B2x["Escrow stays Proposed. Case manager chases. Client can withdraw"]
    B2 -->|"Yes"| B3["State: Agreed. Bank opens escrow"]
    B3 --> B4["Bank payment instructions · SCR-PTL-18. Never Fidero's account"]
    B4 --> B5{"Bank confirms deposit?"}
    B5 -->|"Amount short or reference missing"| B5x["Failed: deposit not matched. Case manager checks with bank. Client told what to fix"]
    B5x --> B5
    B5 -->|"Yes"| B6["State: Funded. Tracker shows deposit date and amount · SCR-PTL-17"]
    B6 --> B7["Close each condition with evidence · SCR-BO-11"]
    B7 --> B7m{"Evidence complete?"}
    B7m -->|"Document missing"| B7r["Condition stays open. Named owner and date shown to client"]
    B7r --> B7
    B7m -->|"Yes"| B8["Fresh search and site check · FR-CASE-014"]
    B8 --> B8f{"Fresh search clear and in date?"}
    B8f -->|"New caveat found"| B8x["Blocked: release stopped. Report re-issued as new version. Client advised"]
    B8f -->|"Out of date"| B8o["Blocked: fresh search older than the window · RUL-07. Re-run"]
    B8o --> B8
    B8f -->|"Yes"| B9["State: Ready to release"]
    B9 --> B9c["Client approves the release with a one-time code · SCR-PTL-17 · RUL-11, DA-01"]
    B9c --> B9d{"Client approved?"}
    B9d -->|"No response"| B9r["Reminders on the configured period. Silence is never approval. Escrow stays Ready to release"]
    B9r --> B9c
    B9d -->|"Yes"| B9e["State: Client approved"]
    B9e --> B10["Approval 1 of 2 · SCR-BO-12"]
    B10 --> B11["Approval 2 of 2 by a different person, with second factor"]
    B11 --> B12["State: Release approved. Instruction sent to bank"]
    B12 --> B13{"Bank confirms payment?"}
    B13 -->|"Bank rejects instruction"| B13x["Failed: case manager contacts bank. Client sees 'Bank has queried the instruction'"]
    B13 -->|"Yes"| B14(["State: Released. All parties see bank confirmation"])
    B6 -.->|"Dispute opened"| BF["State: Frozen. Release button removed · RUL-15. Go to J-07"]
    B9 -.->|"Dispute opened"| BF
    B12 -.->|"Dispute opened before the bank pays"| BF
    BF -.->|"Dispute resolved"| B6
```

The client approval step follows the Escrow state model in 01 v0.2 and later (Ready to release → Client approved). It is the client's step, not a release: two Fidero staff still approve and the bank pays.

### 3.3 J-03 Build with milestone payments (R2)

```mermaid
flowchart TD
    C0(["Verified plot · SCR-PTL-25"]) --> C1["Bill of quantities and milestone split"]
    C1 --> C2["Pick vetted contractor with track record. Approve budget"]
    C2 --> C3["Inspector assigned by Fidero with no link to contractor · RUL-10"]
    C3 --> C3c{"Conflict found?"}
    C3c -->|"Yes"| C3x["Blocked: assignment refused. Pick another inspector · FR-BLD-004"]
    C3x --> C3
    C3c -->|"No"| C4["Construction money held at bank"]
    C4 --> C5["Contractor captures evidence in app · SCR-MOB-04 to 07"]
    C5 --> C5o{"Online?"}
    C5o -->|"No"| C5q["Queued on phone. Offline banner. Uploads when signal returns · FR-MOB-005"]
    C5q --> C6
    C5o -->|"Yes"| C6["Server checks signatures and flags · FR-MOB-011"]
    C6 --> C6f{"Flags raised?"}
    C6f -->|"Position outside plot, reused photo, time gap"| C6r["Reviewer checks flags · SCR-BO-14"]
    C6r --> C6d{"Reviewer decision"}
    C6d -->|"Reject"| C6x["Milestone Returned. Contractor told what to recapture"]
    C6x --> C5
    C6d -->|"Work not done"| C6z["Contractor removed from panel. Releases frozen · FR-BLD-010"]
    C6d -->|"Clear"| C7
    C6f -->|"No"| C7["Evidence checked. Inspection scheduled"]
    C7 --> C8["Inspector visit and checklist · SCR-MOB-09 to 11"]
    C8 --> C8r{"Result"}
    C8r -->|"Fail"| C8x["Returned. No release. Contractor fixes and resubmits"]
    C8x --> C5
    C8r -->|"Pass with defects"| C8d["Defect value held back · RUL-09"]
    C8r -->|"Pass"| C9
    C8d --> C9["Re-price in cedis against dollar guide · RUL-18"]
    C9 --> C9c{"Price changed?"}
    C9c -->|"Yes"| C9a["Client sees old and new amount before approving · SCR-PTL-23"]
    C9c -->|"No"| C10
    C9a --> C10["Client approves · SCR-PTL-23"]
    C10 --> C11["Two Fidero approvals · SCR-BO-12"]
    C11 --> C12(["Bank pays contractor. Dashboard updated · SCR-PTL-22"])
```

### 3.4 J-04 Buy a verified listing (R2)

```mermaid
flowchart TD
    D0(["Developer submits plot and pays listing fee · SCR-PTL-31"]) --> D1["Fidero verifies. Listing: In verification"]
    D1 --> D1v{"Report green and in date?"}
    D1v -->|"Amber or red"| D1x["Rejected. Not published · RUL-12"]
    D1v -->|"Yes"| D2["Live with Fidero Verified badge and check date"]
    D2 --> D3["Ama searches listings · SCR-PTL-26"]
    D3 --> D3e{"Results?"}
    D3e -->|"None"| D3n["Empty state: widen area or price. Save search"]
    D3e -->|"Yes"| D4["Listing detail · SCR-PTL-27"]
    D4 --> D4b{"Badge valid?"}
    D4b -->|"Expired"| D4x["Badge shown as Expired with date. Reserve button removed · RUL-13"]
    D4b -->|"Suspended by monitoring alert"| D4s["Listing hidden from search. Direct link shows 'Under review'"]
    D4b -->|"Yes"| D5["Open full report · RUL-14"]
    D5 --> D6["Reserve · SCR-PTL-28. Listing: Reserved"]
    D6 --> D7["Fresh search and site check"]
    D7 --> D7f{"Fresh search clear?"}
    D7f -->|"No"| D7x["Reservation fails. Listing suspended. Ama told plainly"]
    D7f -->|"Yes"| D8["Purchase follows J-02"]
    D8 --> D9(["Escrow released. Listing: Sold. Success fee invoiced"])
```

### 3.5 J-05 Fund a project at home (R2)

```mermaid
flowchart TD
    E0(["Owner sets up project: budget, stages, person running it, suppliers · SCR-PTL-30"]) --> E1["Fidero checks person and suppliers · FR-PRJ-002"]
    E1 --> E1c{"All checks passed?"}
    E1c -->|"Supplier fails check"| E1x["Supplier cannot be paid. Owner picks another"]
    E1x --> E1
    E1c -->|"Yes"| E2["Money held at bank. Above threshold: enhanced checks · FR-PRJ-004"]
    E2 --> E3["Supplier invoice plus receipts, photos, visit"]
    E3 --> E3c{"Stage confirmed?"}
    E3c -->|"Receipts missing"| E3r["Stage stays open. Owner sees what is missing"]
    E3r --> E3
    E3c -->|"Yes"| E4["Two Fidero approvals"]
    E4 --> E5(["Bank pays the supplier directly. Never cash to a person · RUL-21"])
```

### 3.6 J-06 Bank collateral check (R2)

```mermaid
flowchart TD
    F0(["Bank system calls partner API with plot reference"]) --> F1{"Report exists?"}
    F1 -->|"No"| F1n["Returns: no report"]
    F1 -->|"In progress"| F1p["Returns: report in progress"]
    F1 -->|"Yes"| F2{"Client consent for this partner? · SCR-PTL-21"}
    F2 -->|"No"| F2n["Returns only: a report exists · RUL-16"]
    F2 -->|"Verdict consent"| F3["Returns verdict and date"]
    F2 -->|"Full report consent"| F4["Returns verdict, date and full report link"]
    F2 -.->|"Consent withdrawn"| F2n
```

The client-facing part of J-06 is the consent screen SCR-PTL-21. Consent is per partner and per level. Withdrawal works the same way as granting.

### 3.7 J-07 Raise and resolve a dispute (R2)

```mermaid
flowchart TD
    G0(["Party opens dispute with reason and evidence · SCR-PTL-29"]) --> G1["Every linked release frozen · RUL-15. Escrow or milestone shows Frozen"]
    G1 --> G2["Other party notified. Response due in 5 working days"]
    G2 --> G2c{"Response by deadline?"}
    G2c -->|"No response"| G3
    G2c -->|"Yes"| G3["Evidence stage: 10 working days"]
    G3 --> G4["Reviewer decides within 10 working days · SCR-BO-17"]
    G4 --> G4r{"Refer to mediation?"}
    G4r -->|"Yes"| G5["Referred. Mediation outcome recorded"]
    G4r -->|"No"| G6["Decision and reasons recorded. All parties notified"]
    G5 --> G7(["Closed. Releases unfrozen or cancelled per decision"])
    G6 --> G7
```

Deadlines are the assumptions in FR-DSP-003. Each step shows its due date in Ghana time and in the user's time zone.

### 3.8 J-08 Verify an existing building (R1)

```mermaid
flowchart TD
    H0(["Order step 1: choose Building · SCR-PTL-06"]) --> H1["As J-01 steps 2 to 4"]
    H1 --> H2["Building template adds tasks: permit, structural inspection, occupants and tenancies, rates and bills · FR-CASE-013"]
    H2 --> H2c{"Occupants found?"}
    H2c -->|"Tenants in place"| H2t["Amber condition: vacant possession before release"]
    H2c -->|"No"| H3
    H2t --> H3["Report released with building sections"]
    H3 --> H4["Escrow as J-02, plus conditions: keys handed over and vacant possession"]
    H4 --> H4c{"Keys and vacant possession evidenced?"}
    H4c -->|"No"| H4x["Blocked: condition open. Release not possible · RUL-06"]
    H4c -->|"Yes"| H5(["Release as J-02"])
```

### 3.9 J-09 Pay a school or hospital directly (R1)

```mermaid
flowchart TD
    I0(["Kwabena opens Family on the dashboard · SCR-PTL-36"]) --> I1["Add his mother as a family member · SCR-PTL-38"]
    I1 --> I2["Add Komfo Anokye Teaching Hospital as an institution · SCR-PTL-39"]
    I2 --> I2k{"Already verified by Fidero?"}
    I2k -->|"Yes"| I3
    I2k -->|"No"| I2v["Fidero verifies: registration, bank account in the hospital's name, named contact · SCR-BO-27 · FR-FEE-001"]
    I2v --> I2r{"Verification result"}
    I2r -->|"Fails: account not in the institution's name, or registration not found"| I2x["Blocked: institution card shows 'Not verified' with the reason. No invoice can be paid to it · RUL-22. Fidero asks the institution for the right account"]
    I2x --> I2v
    I2r -->|"Passes"| I3["Institution card: Verified on [date], account ending 4471 · CMP-26"]
    I3 --> I4["Invoice arrives: Kwabena uploads it, or the hospital sends it to Fidero's reference · SCR-PTL-40 · FR-FEE-002"]
    I4 --> I5["Fidero checks: institution matches, patient matches the family member, amount and reference readable · SCR-BO-30"]
    I5 --> I5c{"Checks pass?"}
    I5c -->|"Mismatch: patient name or institution differs"| I5x["Blocked: 'The invoice names a different patient. Check with the hospital.' Kwabena can upload a corrected invoice. Nothing is paid"]
    I5x --> I4
    I5c -->|"Unreadable"| I5u["Document request: 'We could not read the amount. Please photograph the whole invoice.'"]
    I5u --> I4
    I5c -->|"Yes"| I6["Kwabena approves with a one-time code and pays into Partner Bank, or uses his held balance · FR-FEE-003, FR-ESC-014, RUL-11"]
    I6 --> I6d{"Bank confirms the money?"}
    I6d -->|"Not yet"| I6w["Waiting: 'Partner Bank has not confirmed your payment yet. We check every hour.'"]
    I6w --> I6d
    I6d -->|"Yes"| I7["Two Fidero staff approve. Instruction to pay the hospital's account only · FR-ESC-015, RUL-05"]
    I7 --> I7p{"Payee account matches the verified institution?"}
    I7p -->|"No"| I7x["Blocked by the system. Reviewer told. Nothing moves · FR-ESC-015"]
    I7p -->|"Yes"| I8["Bank pays. Status: 'Paid to Komfo Anokye Teaching Hospital, account ending 4471, on 15 Aug'"]
    I8 --> I9{"Direct payment possible?"}
    I9 -->|"No: institution takes cash only"| I9r["Runner pays in person against a signed voucher; receipt uploaded within 2 working days · FR-FEE-006, DA-10"]
    I9 -->|"Yes"| I10
    I9r --> I10["Receipt and, where allowed, discharge note returned to the statement · SCR-PTL-42 · FR-FEE-004"]
    I10 --> I11(["Statement updated: invoice, payment, receipt, balance held at Partner Bank · FR-FEE-007"])
    I3 -.->|"School fees"| I12["Recurring schedule per term with reminder and enrolment confirmation · SCR-PTL-41 · FR-FEE-005"]
    I12 -.-> I6
```

Edge states: an institution's verification lapses (bank account changed): the card turns to "Re-verifying" and payments pause until a second staff member confirms the new account (FR-ADM-003). A recurring payment is never taken without Kwabena's approval for that term (FR-FEE-005, RUL-11).

### 3.10 J-10 Arrange care visits (R2)

```mermaid
flowchart TD
    K0(["Kwabena sets up a care plan for his mother · SCR-PTL-43 · FR-CARE-001"]) --> K1["Fidero assigns a vetted carer from the panel · SCR-BO-28 · FR-CARE-002"]
    K1 --> K1c{"Vetted carer available in Kumasi?"}
    K1c -->|"No"| K1x["Plan saved as 'Waiting for a carer'. Expected date shown. Nothing is charged"]
    K1x --> K1
    K1c -->|"Yes"| K2["Family told who to expect: name, photo, carer ID · FR-NTF-001"]
    K2 --> K3["Carer checks in at the registered address · SCR-MOB-14 · FR-MOB-012"]
    K3 --> K3g{"Position within the address buffer?"}
    K3g -->|"No"| K3x["Check-in recorded as 'away from the address, 410 m'. Carer must explain. Visit flagged for review"]
    K3x --> K4
    K3g -->|"Yes"| K4["Plan items done, agreed photos and readings captured in app · SCR-MOB-15 · FR-CARE-003"]
    K4 --> K5["Check out. Carer reads the 4-digit code to the family · SCR-MOB-16"]
    K5 --> K6["Family member gets a one-time link: 'Did Grace visit today?' · SCR-PTL-45 · FR-CARE-004, DA-07"]
    K6 --> K6c{"Confirmed within 24 hours?"}
    K6c -->|"Yes, with code"| K7["Visit: Confirmed. Carer paid for this visit from the held balance after Fidero's approval · RUL-23"]
    K6c -->|"Family says it did not happen"| K6n["Visit: Disputed. Carer not paid. Reviewer compares check-in, photos and the family's account the same day"]
    K6c -->|"No answer after 24 hours"| K6u["Alert to Kwabena and Fidero: 'Visit on 15 Aug is not yet confirmed' · FR-CARE-005. Fidero calls the family. Carer not paid until confirmed"]
    K6u --> K6c
    K7 --> K8(["Visit card on Kwabena's dashboard: check-in 09:02, check-out 10:15, 3 photos, confirmed by Comfort · SCR-PTL-44 · CMP-27"])
    K3 -.->|"Carer does not check in by the planned time plus 60 minutes [TO VERIFY]"| K9["Missed-visit alert to Kwabena and Fidero · FR-CARE-005. Fidero reassigns or reschedules"]
    K4 -.->|"Carer raises a concern"| K10["Concern to Kwabena and a reviewer the same day · FR-CARE-006"]
```

Edge state: the family member cannot use a phone. DA-07's fallback is a call from Fidero to a second named family member; the confirmation records "confirmed by call with [name]".

### 3.11 J-11 Manage a property (R2)

```mermaid
flowchart TD
    L0(["Akosua registers her house in Tema · SCR-PTL-46 · FR-PMG-001"]) --> L1["Fidero inspects and records the condition with photos · SCR-MOB-18"]
    L1 --> L2["Tenant found or existing tenant verified; agreement checked · FR-PMG-002"]
    L2 --> L2c{"Agreement and tenant pass checks?"}
    L2c -->|"No"| L2x["Blocked: 'The agreement names a different landlord.' Management does not start until fixed"]
    L2x --> L2
    L2c -->|"Yes"| L3["Rent set to be paid by the tenant to Akosua's own account at Partner Bank. Fidero never receives rent · RUL-24"]
    L3 --> L4["Each month: rent due date on the dashboard · SCR-PTL-47 · FR-PMG-003"]
    L4 --> L4c{"Rent received by the due date?"}
    L4c -->|"Yes"| L4y["'Paid by tenant to your account at Partner Bank, 1 Sept, GHS 4,500.00'"]
    L4c -->|"No, 5 days late [TO VERIFY]"| L4x["Alert to Akosua and Fidero: 'Rent for September is late.' Fidero contacts the tenant. Record shows 'Late since 6 Sept'"]
    L4x --> L4c
    L4y --> L5
    L4c -.->|"Bank statement not yet matched"| L4m["Shown as 'Not yet confirmed by the bank', never as missing"]
    L4m --> L4c
    L5["Tenant or inspector reports a repair · SCR-PTL-54 · FR-PMG-004"] --> L6["Fidero collects at least two quotes from vetted contractors"]
    L6 --> L7["Akosua compares and approves one quote with a one-time code · SCR-PTL-48 · RUL-11"]
    L7 --> L7c{"Decision"}
    L7c -->|"Rejects both"| L7x["Quotes rejected with a reason. Fidero seeks new quotes. Repair stays 'Open: new quotes expected by [date]'"]
    L7x --> L6
    L7c -->|"Approves one"| L8["Repair money held at Partner Bank against the quote · FR-PMG-005"]
    L8 --> L9["Contractor does the work; inspector checks with photos · SCR-MOB-18"]
    L9 --> L9c{"Inspection result"}
    L9c -->|"Fail"| L9x["Not paid. Contractor fixes. Akosua sees the inspector's photos and reason"]
    L9x --> L9
    L9c -->|"Pass"| L10["Two Fidero approvals. Bank pays the contractor, account ending [nnnn] · RUL-22"]
    L10 --> L11(["Dashboard timeline: rent, repairs, inspections, photos · FR-PMG-006"])
```

### 3.12 J-12 Get paperwork done (R2)

```mermaid
flowchart TD
    M0(["Ama opens the errand catalogue for Ghana · SCR-PTL-49 · FR-TSK-001"]) --> M1["Picks 'Ghana Card renewal' and 'Land title application'. Sees checklist, official fees, Fidero's charge, target time"]
    M1 --> M2["Uploads checklist documents · SCR-PTL-50 · FR-TSK-002"]
    M2 --> M2c{"Checklist complete and readable?"}
    M2c -->|"No"| M2x["Errand stays 'Waiting for your documents: 2 missing'. Nothing is paid"]
    M2x --> M2
    M2c -->|"Yes"| M3["Pays official fees and Fidero's charge into Partner Bank"]
    M3 --> M4["Vetted agent assigned · SCR-BO-28, SCR-BO-32 · FR-TSK-003"]
    M4 --> M5["Agent lodges the application · SCR-MOB-17. Official fee paid to the agency's account only; receipt uploaded · RUL-22"]
    M5 --> M5c{"Agency accepts the application?"}
    M5c -->|"Rejected: document missing or out of date"| M5x["Step shows 'Rejected by the agency: passport photo out of date.' Document request to Ama. Agent retries when it arrives. Fidero's charge not taken twice"]
    M5x --> M2
    M5c -->|"Accepted"| M6["Each step shown in plain language with its receipt or acknowledgement"]
    M6 --> M7{"Resulting document ready?"}
    M7 -->|"Delayed past target time"| M7x["Status: 'The agency is late. New expected date [date]. We are chasing.' Target times are assumptions"]
    M7x --> M7
    M7 -->|"Yes"| M8["Agent collects it. Fidero checks the document · FR-TSK-004"]
    M8 --> M8c{"Document correct?"}
    M8c -->|"Wrong name or details"| M8x["Completion refused. Agent returns to the agency. Ama told plainly"]
    M8x --> M5
    M8c -->|"Yes"| M9["Handover to Ama's representative or courier, with signature or photo · FR-TSK-005"]
    M9 --> M10(["Errand: Complete. Fees, receipts and the document on the dashboard · RUL-23"])
```

Agent payment follows RUL-23: Fidero's charge is released to the agency only when the errand is complete and the document is checked.

---

## 4. Wireframes

Low fidelity. Phone wireframes are 40 characters wide, standing for a 360 px screen. Laptop wireframes are wider. `[ Button ]` is a button, `( )` a radio, `[x]` a checkbox, `___` an input, `<v>` a select, `(*)` an icon. All data is sample data.

Annotation keys: **Content**, **Actions**, **States**, **Rules**, **Satisfies**.

### W-01 Sign up · SCR-PTL-02

```text
+----------------------------------------+
| FIDERO                     Sign in     |
+----------------------------------------+
| Create your account                    |
| Step 1 of 2                            |
|                                        |
| Full name                              |
| [ Ama Serwaa Mensah____________ ]      |
| Email                                  |
| [ ama.mensah@example.com_______ ]      |
| Mobile number                          |
| [ +44 v ][ 7700 900123__________ ]     |
| Password (12 characters or more)       |
| [ ************_________ ] [Show]       |
|                                        |
| [x] I have read the privacy notice     |
|     (plain-language, 1 page) >         |
|                                        |
| [        Send my codes         ]       |
|                                        |
| We send one code by email and one by   |
| text message. Codes last 10 minutes.   |
+----------------------------------------+
| Step 2: [ _ _ _ _ _ _ ] email code     |
|         [ _ _ _ _ _ _ ] phone code     |
|         Resend codes (in 0:45)         |
+----------------------------------------+
```

- **Content.** One "full name" field, not first and last, because Ghanaian names do not always split that way. Country code picker defaults from the browser locale.
- **Actions.** Send codes; enter codes; resend after a 45-second wait (sample).
- **States.** Code wrong: "That code does not match. Check the latest message." Code expired: "That code has expired. We sent a new one." Email already used: offer sign in.
- **Rules.** Paste allowed in code and password fields; password managers work (WCAG 3.3.8). Privacy notice acceptance recorded with version.
- **Satisfies.** FR-ACC-001, FR-DPR-001, J-01.

### W-02 Identity check · SCR-PTL-04

```text
+----------------------------------------+
| <- Home                                |
| Confirm who you are                    |
|                                        |
| We must check your identity before we  |
| release a report or open an escrow.    |
| It takes about 3 minutes.              |
|                                        |
| Choose a document                      |
| ( ) Ghana Card                         |
| (*) Passport                           |
| ( ) I cannot do this online            |
|                                        |
| You will:                              |
|  1. Photograph the photo page          |
|  2. Take a short selfie video          |
|                                        |
| [      Start identity check      ]     |
|                                        |
| Who sees this: Fidero staff and our    |
| identity check provider. Why? >        |
+----------------------------------------+
| STATUS CARD (after submit)             |
| (i) Checking your passport. Most       |
|     checks finish within 1 hour.       |
+----------------------------------------+
```

- **Content.** Why, how long, what happens, who sees the data.
- **Actions.** Start the provider check; or choose manual check, which opens an upload form for staff review.
- **States.** Pending, passed, failed with reason and retry, manual review. If the provider is down: "Our identity check service is not working right now. You can carry on ordering. We will remind you."
- **Rules.** The check is not needed to order or pay. It is needed before report release and escrow (A10 in J-01).
- **Satisfies.** FR-ACC-004, J-01, J-02.

### W-03 Order step 1, what to check · SCR-PTL-06

```text
+----------------------------------------+
| <- Cancel        Order a check         |
| [1 What]-[2 Plot]-[3 Docs]-[4 Agree]   |
|  ======                                |
| What do you want checked?              |
| +------------------------------------+ |
| |(*) Land (a plot)                   | |
| +------------------------------------+ |
| |( ) A building on its land          | |
| |    Adds permit, structure, tenants | |
| +------------------------------------+ |
|                                        |
| How fast?                              |
| +------------------------------------+ |
| |(*) Standard                        | |
| |    USD 450.00   about 3-4 weeks    | |
| |( ) Rush                            | |
| |    USD 600.00   about 2 weeks      | |
| +------------------------------------+ |
| Show prices in  <USD v>                |
| Prices are samples. Final price shown  |
| before you pay.                        |
|                                        |
| [            Continue            ]     |
+----------------------------------------+
```

- **Content.** Product line and tier as large radio cards (44 px or more). Tiers come from admin configuration (FR-ORD-002). "Extra plot, same seller" appears only after the first plot is added.
- **Actions.** Continue. The draft saves after each step.
- **States.** Prices fail to load: show "Prices are not loading. Try again." with a retry button; never show a stale price as final.
- **Rules.** Display currency per DA-02. Local standard tier shown when the user's country is Ghana.
- **Satisfies.** FR-ORD-001, FR-ORD-002, F-09, J-01, J-08.

### W-04 Order step 2, the plot · SCR-PTL-07

```text
+----------------------------------------+
| <- Back          Order a check         |
| [1 What]-[2 Plot]-[3 Docs]-[4 Agree]   |
|           ======                       |
| Where is the plot?                     |
| Region                                 |
| [ Central                      v ]     |
| Town or area                           |
| [ Kasoa, Millennium City______ ]       |
| Plot number (if known)                 |
| [ 14_________ ]                        |
| Site plan reference (if known)         |
| [ CR/KS/2026/0391_____ ]               |
| Ghana Post GPS address (if known)      |
| [ CX-071-4420___ ]  Look up            |
| +------------------------------------+ |
| | Map preview (static image)         | |
| | Pin near Kasoa. Tap to adjust >    | |
| +------------------------------------+ |
| Don't know some of these? That's fine. |
| Our surveyor confirms on site.         |
| [            Continue            ]     |
+----------------------------------------+
```

- **Content.** Only locality is required. Ghana Post GPS format hint `AA-NNN-NNNN`.
- **Actions.** Look up GPS address; adjust pin on a live map loaded only on tap (keeps page weight down).
- **States.** Look up fails: "We could not find that address. Check it, or carry on without it." Never blocks.
- **Rules.** No redundant entry: fields filled earlier (for example from a listing) are pre-filled (WCAG 3.3.7).
- **Satisfies.** FR-ORD-001, FR-GEO-008, J-01.

### W-05 Order step 4, check and agree · SCR-PTL-09

```text
+----------------------------------------+
| <- Back          Order a check         |
| [1 What]-[2 Plot]-[3 Docs]-[4 Agree]   |
|                             =======    |
| Check your order                       |
| Land check, Standard ......... Change  |
| Plot 14, Kasoa Millennium City  Change |
| Site plan uploaded (1 file) .. Change  |
| Seller: Kofi Asante, +233 24.. Change  |
|                                        |
| What the report covers                 |
| +------------------------------------+ |
| | (lock) Scope and limitation        | |
| | statement, version 1.0             | |
| | "This report sets out the results  | |
| |  of the checks listed in section   | |
| |  3 ..."   Read it all >            | |
| +------------------------------------+ |
| [ ] I have read what the report covers |
|     and does not cover                 |
| [ ] I agree to the terms (v1.0) >      |
| How did you hear about us? <Select v>  |
| Referral code (optional) [_______]     |
|                                        |
| Total to pay        USD 450.00         |
| [      Continue to payment       ]     |
+----------------------------------------+
```

- **Content.** Summary with change links back to each step. Locked scope text shown in full on expand, with version number.
- **Actions.** Accept scope and terms (two separate checkboxes), choose lead source, enter referral code, continue.
- **States.** Referral code invalid: inline message, order still allowed. Unchecked boxes: error summary at top with links to each box.
- **Rules.** Acceptance recorded with time and version (FR-ORD-003). Scope text cannot be edited (RUL-04).
- **Satisfies.** FR-ORD-003, FR-ORD-005, FR-ORD-006, RUL-04.

### W-06 Pay Fidero's fee · SCR-PTL-10

```text
+----------------------------------------+
| <- Back             Pay                |
| You are paying Fidero's fee for        |
| a land check.                          |
|                                        |
| Fee                    USD 450.00      |
| (about GBP 355, guide only)            |
|                                        |
| How do you want to pay?                |
| (*) Card                               |
| ( ) Mobile money (GHS 6,975.00)        |
|                                        |
| +------------------------------------+ |
| | Payment provider's secure card     | |
| | form loads here                    | |
| +------------------------------------+ |
|                                        |
| [       Pay USD 450.00           ]     |
|                                        |
| (i) This page is only for Fidero's     |
| fee. We never take money for the land. |
| Land money goes to a licensed bank.    |
+----------------------------------------+
```

- **Content.** Amount, method, guide conversion, the "fee only" notice.
- **Actions.** Pay. Button repeats the amount.
- **States.** Processing (button disabled, "Paying... do not close this page"); declined (reason from provider in plain words, try again or switch method); mobile money pending ("Approve the payment on your phone. We will wait for up to 10 minutes."); timeout (order saved as draft, nothing charged twice).
- **Rules.** No card data stored (FR-PAY-002). Fee and escrow money never share a screen or flow (FR-PAY-005, RUL-01).
- **Satisfies.** FR-PAY-001, FR-PAY-002, FR-PAY-005, J-01.

### W-07 Case tracker · SCR-PTL-12

```text
+----------------------------------------+
| <- Home                                |
| Plot 14, Kasoa Millennium City         |
| Land check  FID-2027-0142              |
| +------------------------------------+ |
| | NOW: Searches lodged at the Lands  | |
| | Commission on 12 March. Results    | |
| | expected by 2 April.               | |
| +------------------------------------+ |
| ! We need one thing from you           |
|   Seller's ID copy [Upload] by 20 Mar  |
|                                        |
| Timeline                               |
| (v) Order paid ............. 3 Mar     |
| (v) Case accepted .......... 4 Mar     |
| (v) Searches lodged ........ 12 Mar    |
| (o) Site visit ...... planned 18 Mar   |
| ( ) Map checks ...... expected 20 Mar  |
| ( ) Consent meeting . expected 27 Mar  |
| ( ) Search results .. expected 2 Apr   |
| ( ) Legal review .... expected 7 Apr   |
| ( ) Report ready .... expected 10 Apr  |
|                                        |
| [ Message Fidero ]  Receipt >          |
+----------------------------------------+
```

- **Content.** One "Now" sentence (CMP-06 pattern), open requests first, then the timeline. Done steps show actual dates; future steps show expected dates.
- **Actions.** Upload requested document; message Fidero; view receipt; share read-only access with a representative.
- **States.** On hold: "Paused. We are waiting for the seller's ID copy. We will restart as soon as it arrives." Late: "Search results are late. We expected them by 2 April. We are chasing and will update you by 9 April." Cancelled with refund status.
- **Rules.** Messages come from templates (FR-CASE-007). No third-party personal data shown beyond what the client supplied.
- **Satisfies.** FR-CASE-007, FR-CASE-008, FR-CASE-015, FR-ACC-008, FR-NTF-001, F-06, J-01.

### W-08 Report viewer · SCR-PTL-14

```text
+----------------------------------------+
| <- Case FID-2027-0142                  |
| Your report                            |
| +------------------------------------+ |
| | [(!) AMBER]  Fix before you pay    | |
| | Issues found that can be resolved  | |
| | before purchase.                   | |
| +------------------------------------+ |
| Why                                    |
| - Two corner pillars missing           |
| - Family consent promised, not yet     |
|   recorded                             |
| Before you pay                         |
| [ ] Pillars re-set by surveyor         |
| [ ] Consent meeting recorded on video  |
|                                        |
| Section verdicts  (table, 4 to 10)     |
| 4 Plot identity ......... (!) Amber    |
| 5 Lands Commission ...... (v) Green    |
| 8 Seller authority ...... (!) Amber    |
| ...                                    |
| Signed by: Lawyer A. Darko, GBA-1234   |
|  Surveyor E. Tetteh, LS-0567           |
| [   Download PDF (1.2 MB)   ]          |
| Report v1 · 10 Apr 2027 · SHA-256:     |
| 9f2c 41ab ... e07d  [Copy] [Check >]   |
| [ Buy through escrow ]                 |
+----------------------------------------+
```

- **Content.** Verdict badge (CMP-07) with the template's meaning, 3 to 5 reasons, conditions, section table, signatures with licence numbers, PDF, version, hash.
- **Actions.** Download PDF; copy hash; check a file against the hash (in-browser, DA-04); offer escrow on green or amber.
- **States.** New version: banner "This report was corrected on 14 April. Reason: plot number typo. Version 2 replaces version 1." Older versions stay listed. Red: escrow button replaced by "Why we advise you not to buy" and "Check another plot".
- **Rules.** Released reports never change (FR-RPT-010). Hash shown in groups of 4 for reading aloud.
- **Satisfies.** FR-RPT-005, FR-RPT-007, FR-RPT-008, FR-RPT-010, RUL-02, J-01.

### W-09 Escrow tracker · SCR-PTL-17

```text
+----------------------------------------+
| <- Home                                |
| Escrow for Plot 14, Kasoa              |
| ESC-2027-0031 · Held by Partner Bank   |
| +------------------------------------+ |
| | NOW: All 4 conditions closed.      | |
| | Fresh search done 2 May. Release   | |
| | is waiting for a second Fidero     | |
| | approval.                          | |
| +------------------------------------+ |
| Money at the bank                      |
| USD 18,000.00  deposit confirmed 22 Apr|
| Your money is held by Partner Bank,    |
| not by Fidero.                         |
|                                        |
| Conditions (4 of 4 closed)             |
| [v] Pillars re-set ...... closed 25 Apr|
| [v] Consent recorded .... closed 28 Apr|
| [v] Indenture signed .... closed 30 Apr|
| [v] Seller's tax clearance closed 6 May|
| Fresh search (within window) [v] 2 May |
|                                        |
| Your approval                          |
| (v) You approved the release 6 May     |
|     14:00 GMT (code verified)          |
| Release approvals   [ 1 of 2 ]         |
| (v) K. Boateng, reviewer, 6 May 15:20  |
| ( ) Second approver                    |
| Then: bank pays seller, confirms.      |
+----------------------------------------+
```

- **Content.** Status sentence, bank and amount, conditions with closing dates, fresh search, the client's own approval, Fidero's two approvals, next step. An open condition shows its owner and due date instead of a closing date: "Seller's tax clearance. Owner: seller's lawyer. Due 6 May."
- **Actions.** Approve the release once every condition is closed (one-time code, DA-01, RUL-11); view evidence for a closed condition; open a dispute (R2); view bank instructions.
- **States.** Proposed (waiting for parties), Agreed (waiting for deposit), Funded (conditions closing; approvals show "Start when every condition is closed"), Ready to release ("Your approval is needed. Fidero staff approve after you."), Client approved, Release approved, Released, Frozen ("A dispute was opened on 4 May. No money can move until it is resolved."), Cancelled. No response from the client: reminders; silence is never approval.
- **Rules.** No approval or release while any condition is open (RUL-06); fresh search must be in date (RUL-07); client approves first and cannot release alone (RUL-11); approver names shown (RUL-05).
- **Satisfies.** FR-ESC-004 to FR-ESC-009, RUL-05, RUL-06, RUL-07, RUL-11, RUL-15, J-02.

### W-10 Bank payment instructions · SCR-PTL-18

```text
+----------------------------------------+
| <- Escrow ESC-2027-0031                |
| Pay the purchase price to the bank     |
| +------------------------------------+ |
| | (shield) These are the bank's      | |
| | details, not Fidero's. Fidero      | |
| | never asks you to pay land money   | |
| | to Fidero.                         | |
| +------------------------------------+ |
| Bank ............ Partner Bank [SAMPLE]|
| Account name .... Escrow account       |
| Account number .. 0000 0000 0000 [Copy]|
| SWIFT ........... XXXXGHAC     [Copy]  |
| Reference ....... ESC-2027-0031 [Copy] |
| Amount .......... USD 18,000.00        |
|                                        |
| Always use the reference. Without it   |
| the bank cannot match your payment.    |
| If anyone sends you different details, |
| do not pay. Call us first.             |
+----------------------------------------+
```

- **Content.** Bank details from the escrow record only. Warning about changed details.
- **Actions.** Copy each field; download as PDF; "Report suspicious details".
- **States.** Escrow not yet Agreed: details hidden with "The bank will open the escrow once everyone has accepted the terms."
- **Rules.** Never Fidero's account (FR-ESC-003, RUL-01). Details change only through a two-person admin change, logged.
- **Satisfies.** FR-ESC-003, RUL-01, J-02.

### W-11 Back office: my work queue · SCR-BO-02

```text
+------------------------------------------------------------------------------------+
| FIDERO back office   My work | Cases | Escrow | Reports | Admin     Esi M. (v)     |
+------------------------------------------------------------------------------------+
| My work (32 open)  Filter: [All types v] [All owners v] [Overdue first v]  Search  |
| OVERDUE (3)                                                                        |
| (!) FID-2027-0129  Search results  Runner: Yaw O.   Due 28 Mar  2 days late [Chase]|
| (!) FID-2027-0133 Consent meeting  Lawyer: A. Darko Due 29 Mar  1 day late  [Chase]|
| DUE THIS WEEK (7)                                                                  |
|     FID-2027-0142  Site visit      Surveyor: E.T.   Due 18 Mar  (risk: clear)      |
|     FID-2027-0150  Intake           Me              Due 31 Mar  New, unassigned    |
| WAITING ON OTHERS (22) ................................................ show >     |
+------------------------------------------------------------------------------------+
```

- **Content.** Tasks grouped by overdue, due this week, waiting. Each row: case, step, owner, due date, lateness in words and icon.
- **Actions.** Filter, search, open case, chase owner (sends templated reminder, logged), bulk reassign.
- **States.** Empty: "Nothing due. New cases appear here when paid." Loading: skeleton rows. Error: retry with last good list shown and its time.
- **Rules.** Sort by due date with overdue first (FR-CASE-005). Role filter (FR-ACC-007).
- **Satisfies.** FR-CASE-005, FR-NTF-003, J-01.

### W-12 Back office: case detail with tasks · SCR-BO-03

```text
+------------------------------------------------------------------------------------+
| <- My work   FID-2027-0142  Plot 14, Kasoa   Land v1.3   In progress   Risk: clear |
+--------------------------------------------+---------------------------------------+
| Tasks                                      | Client sees now                       |
| Step            Owner      Due     Status  | "Searches lodged at the Lands         |
| Intake          Esi M.     4 Mar   Done    |  Commission on 12 March. Results      |
| Searches lodged Yaw O.     6 Mar   Done    |  expected by 2 April."  [Change msg v]|
| Site visit      E.Tetteh+1 18 Mar  Open    |---------------------------------------|
| Overlay checks  System     20 Mar  Ready   | Requests to client                    |
| Consent meeting A. Darko   27 Mar  Open    | Seller's ID copy  due 20 Mar  Open    |
| Search results  Yaw O.     2 Apr   Waiting | [ + Request a document ]              |
| Legal review    A. Darko   7 Apr   -       |---------------------------------------|
| Second review   (reviewer) 9 Apr   -       | Costs   Lawyer GHS 1,500  Runner 300  |
| Release         Esi M.     10 Apr  -       | [ Pause ] [ Cancel case ]             |
+--------------------------------------------+---------------------------------------+
| Task: Site visit   Required evidence: coordinates [ ], photos [ ], video [ ]       |
| [ Mark done ] (disabled: 3 evidence items missing)  Change due date (reason needed)|
+------------------------------------------------------------------------------------+
```

- **Content.** Template version, state, risk flag, tasks, the current client message, requests, costs.
- **Actions.** Assign, change due date with reason, request document, pick next client message from templates, pause, cancel with refund decision.
- **States.** Mark done disabled with a reason until evidence is attached (FR-CASE-004). On hold banner with reason.
- **Rules.** Building cases show four extra steps (FR-CASE-013).
- **Satisfies.** FR-CASE-001 to FR-CASE-004, FR-CASE-007, FR-CASE-008, FR-CASE-011, FR-CASE-012, FR-CASE-013.

### W-13 Risk screen and assignment · SCR-BO-05

```text
+--------------------------------------------------+
| Site visit: risk screen   FID-2027-0129          |
| 1. Any report of threats on this plot?  (Yes) No |
| 2. Occupied by someone claiming it?      Yes (No)|
| 3. Known dispute area (overlay)?        (Yes) No |
| Result: (!) DISPUTED. Two people needed.         |
| Visitors  [ E. Tetteh, surveyor      v ]         |
|           [ Yaw Owusu, runner         v ]        |
| [x] Lawyer told the family head of the visit     |
| [ Assign visit ]                                 |
+--------------------------------------------------+
```

- **Content.** Short risk questions, computed result in words and icon, named visitors.
- **Actions.** Answer, assign, cancel visit.
- **States.** Fewer than two people on a disputed plot: Assign disabled, message "Disputed plot: add a second person (RUL-17)."
- **Rules.** RUL-17; the incident link sits on every field task.
- **Satisfies.** FR-CASE-009, FR-CASE-010.

### W-14 Report builder · SCR-BO-08

```text
+------------------------------------------------------------------------------------+
| Report builder  FID-2027-0142  Template land v1.3   Draft   Autosaved 10:41 GMT    |
+----------------------+-------------------------------------------------------------+
| Sections             | 8. Seller authority and consent        Owner: A. Darko      |
| 1 Cover        auto  | Findings  [ Family head confirmed seller's allocation ...  ]|
| 2 Summary      -     | Evidence  [doc] Allocation note  [vid] Consent 27 Mar (v)   |
| 3 Scope        auto  | Section verdict  ( ) Green  (*) Amber  ( ) Red              |
| 4 Plot identity Amber|   Amber means: consent promised but not yet recorded.       |
| 5 Searches   Green |---------------------------------------------------------------|
| 6 Surveyor     Green | 11. Verdict and conditions                                  |
| 7 Overlays     Green |   Allowed overall: Green blocked (no red, 2 amber) -> Amber |
| 8 Seller       Amber |   Conditions (copied to escrow):                            |
| 9 Chain        Green |   1 Pillars re-set   owner: surveyor  evidence: photos      |
| 10 Occupation  Green |   [ + Add condition ]                                       |
| 11 Verdict   Amber |---------------------------------------------------------------|
| 12 Scope (lock) v1.0 | 12. Scope and limitation  (lock) Locked text v1.0. Cannot   |
| 13 Signatures  0 of 3|     be edited here. Changes go through admin (FR-ADM-004).  |
| 14 Appendices auto  | 13. Sign  [ Sign legal section ] needs licence GBA-1234 valid|
+----------------------+-------------------------------------------------------------+
| [ Preview PDF ]   [ Send for review ] (disabled: summary empty, 3 signatures due)  |
+------------------------------------------------------------------------------------+
```

- **Content.** Section list with verdict per section in icon and word, the active section, computed allowed verdict, conditions as structured items, locked scope block.
- **Actions.** Enter findings, attach evidence from the case store, choose section verdict, add conditions, sign own section, preview, send for review.
- **States.** Green chosen while any section 4 to 10 is red: option disabled with "Overall cannot be green: section 7 is red (RUL-02)." Licence expired: sign button disabled with "Your licence expired on 31 Jan. Upload the renewed licence." Conflict: someone else editing the section, shown with name, read-only.
- **Rules.** RUL-02, RUL-04, RUL-20.
- **Satisfies.** FR-RPT-001 to FR-RPT-005, FR-RPT-009, FR-GEO-003.

### W-15 Two-person release approval · SCR-BO-12

```text
+------------------------------------------------------------------------------------+
| Release approval  ESC-2027-0031  Plot 14, Kasoa              Ready to release      |
+------------------------------------------------------------------------------------+
| Pay USD 18,000.00 from escrow at Partner Bank to Kofi Asante (seller), acct ..4471 |
+------------------------------------------------------------------------------------+
| Gates (all must pass)                                                              |
| (v) All 4 conditions closed with evidence ......................... view evidence  |
| (v) Fresh search 2 May, inside 14-day window [TO VERIFY] ......... view            |
| (v) No open dispute                                                                |
| (v) Deposit confirmed by bank 22 Apr, USD 18,000.00                                |
| (v) Payee matches escrow terms v1.0                                                |
+------------------------------------------------------------------------------------+
| Approval 1 of 2                         | Approval 2 of 2                          |
| (v) Kofi Boateng, reviewer              | You: Abena Owusu, reviewer               |
|     6 May 2027 15:20 GMT, code verified | [x] I checked the evidence for each      |
|                                         |     condition myself                     |
|                                         | Code from your authenticator [______]    |
|                                         | [ Approve and send instruction ]         |
+------------------------------------------------------------------------------------+
| After approval: instruction signed by both approvers and sent to the bank.         |
| Status changes to Release approved, then Released when the bank confirms.          |
+------------------------------------------------------------------------------------+
```

- **Content.** One sentence saying who gets how much from where. Gates. Two approval slots with names and times.
- **Actions.** Approve with second factor; return with comment; view each piece of evidence.
- **States.** Any gate failing: approve area replaced by "Release blocked: 1 condition open (seller's tax clearance)." Same person as approver 1: "You gave approval 1. A different person must give approval 2 (RUL-05)." Frozen by dispute: whole screen read-only with the dispute link. Bank rejects: banner with bank's reason.
- **Rules.** RUL-05, RUL-06, RUL-07, RUL-15. Refund and cancellation use the same screen with "Refund" wording (FR-ESC-013).
- **Satisfies.** FR-ESC-006 to FR-ESC-009, FR-ESC-013.

### W-16 Admin: templates and configuration · SCR-BO-18

```text
+------------------------------------------------------------------------------------+
| Admin > Configuration          Country: Ghana v                                    |
| Templates      Version  Status     | Values (Ghana)                 Current        |
| Land case      1.3      Live      | Fresh-search window      14 days [TO VERIFY]   |
| Building case  1.1      Live      | Listing badge validity   90 days [TO VERIFY]   |
| Land report    1.3      Live      | Plot buffer distance     50 m [TO VERIFY]      |
| Milestones std 1.0      Live       | Dispute response        5 working days        |
| Land case     1.4      Draft >    | [ Edit values ] (change logged, takes effect   |
|                                    |  for new cases only)                          |
| Locked scope statement v1.0 (lock)                                                 |
| Change needs: 2 administrators + lawyer approval file + insurer approval file      |
| [ Propose new version ]   Pending: none                                            |
+------------------------------------------------------------------------------------+
```

- **Content.** Versioned templates and values per country.
- **Actions.** Draft, compare, publish a version; edit values; propose scope change.
- **States.** Publishing a template shows a diff and "Running cases keep version 1.3." Scope proposal waits for a second admin.
- **Rules.** RUL-04, FR-ADM-004. Values marked `[TO VERIFY]` show a warning chip until confirmed by the owner in 01 B9.
- **Satisfies.** FR-ADM-001, FR-ADM-004, FR-ADM-005, FR-CTY-001.

### W-17 Android: contractor milestone submission with offline queue · SCR-MOB-07

```text
+--------------------------------+
| (!) Offline. 7 items saved on  |
|     this phone. They upload    |
|     when you have signal.      |
+--------------------------------+
| <- Foundation   House, Kasoa   |
| Milestone 1 of 6               |
| Evidence (6 of 6 done)         |
| [v] Cleared site, setting out  |
| [v] Trenches with tape (2)     |
| [v] Reinforcement, 2 angles    |
| [v] Video: trench line         |
| [v] Cured foundation           |
| [v] Delivery notes (3)         |
|                                |
| All taken with this app.       |
| Position checked: on plot.     |
|                                |
| [ Submit milestone          ]  |
|                                |
| Submitted offline: it will be  |
| sent automatically. Keep the   |
| app installed.                 |
+--------------------------------+
| Jobs     Queue (7)    Account  |
+--------------------------------+
```

- **Content.** Offline banner with item count, checklist from the milestone schedule, capture summary.
- **Actions.** Open an item to capture or retake; submit (queues when offline).
- **States.** Item missing: Submit disabled with "2 items still needed." Capture off plot: item marked "(!) Taken 340 m from the plot" and the contractor must explain or retake. Sending: progress per item. Sent: "Received by Fidero 14:22 GMT." Upload failed: retried automatically with backoff; never lost.
- **Rules.** Camera only, no gallery (RUL-08). Queue survives restart (FR-MOB-005). Originals kept until server confirms (FR-MOB-008).
- **Satisfies.** FR-MOB-002 to FR-MOB-006, FR-MOB-008, FR-MOB-009, J-03.

### W-18 Android: inspector checklist · SCR-MOB-09 and SCR-MOB-11

```text
+--------------------------------+
| <- Inspection: Blocks          |
| House, Kasoa. You have no link |
| to this contractor.            |
| 3 of 8 checked                 |
| Walls match drawing   Yes  No  |
|   (*)                [ Photo ] |
| Walls plumb, level    Yes  No  |
|   (*)                [ Photo ] |
| Block quality         Yes (No) |
|   Note: crumbling, east wall   |
|   [ Add as defect ]            |
| Mortar joints filled  ...      |
| ...                            |
| Result                         |
| ( ) Pass                       |
| (*) Pass with defects          |
|     1 defect, GHS 2,400 held   |
| ( ) Fail                       |
| [ Submit result ]              |
+--------------------------------+
```

- **Content.** Checklist from the milestone schedule, one item per row, yes/no as large toggles.
- **Actions.** Answer, photo, add defect with value (SCR-MOB-10), choose result, submit.
- **States.** Unanswered items block submit. Fail needs a reason. Offline: same queue as W-17.
- **Rules.** RUL-09 (defect value held), RUL-10 (conflict message at top).
- **Satisfies.** FR-MOB-007, FR-BLD-006, J-03.

### W-19 Build dashboard · SCR-PTL-22

```text
+----------------------------------------+
| House on Plot 14, Kasoa   BLD-2027-0007|
| NOW: Blocks passed inspection 14 Aug   |
| with 1 defect. Waiting for your        |
| approval by 21 Aug.  [ Review ]        |
| Budget                                 |
| Planned  USD 42,000 ######----  spent  |
| Released USD 12,600 (30%)              |
| Held at bank USD 29,400                |
| Milestones                             |
| (v) Mobilisation  paid 2 Jun           |
| (v) Foundation    paid 9 Jul           |
| (!) Blocks        pass w/ defects      |
| ( ) Lintel ... ( ) Roof ... ( ) Finish |
| Photo timeline                         |
| [img][img][img][img]  14 Aug >         |
| [img][img][img]       2 Jul  >         |
| Inspector: P. Quaye, 14 Aug, report >  |
+----------------------------------------+
```

- **Content.** Status sentence with the client's next action, budget against actual, milestone list, photo timeline grouped by milestone, inspector results.
- **Actions.** Review milestone, order an extra inspection (FR-ORD-007), approve a variation, open a dispute.
- **States.** No photos yet: "The contractor has not sent photos yet. Foundation photos are due by 30 June." Release frozen: banner with dispute link.
- **Rules.** Thumbnails are 320 px previews; full image on tap (FR-EVD-004).
- **Satisfies.** FR-BLD-009, FR-ORD-007, J-03.

### W-20 Milestone approval with cedi re-pricing · SCR-PTL-23

```text
+----------------------------------------+
| <- Build   Milestone 2: Blocks         |
| (!) PASS WITH DEFECTS  14 Aug          |
| 1 defect: crumbling blocks, east wall  |
| Price check (in cedis)                 |
| Agreed       GHS 98,000.00             |
| Re-priced    GHS 101,500.00 (+3.6%)    |
| Why: cement price guide rose. Source > |
| Defect held  GHS 2,400.00              |
| To pay now   GHS 99,100.00             |
| = USD 6,394 at guide rate (guide only) |
| [x] I have seen the new price          |
| Code sent to your phone [______]       |
| [ Approve this milestone ]             |
| [ Question it ]  [ Open a dispute ]    |
| After you approve, two Fidero staff    |
| approve and the bank pays.             |
+----------------------------------------+
```

- **Content.** Inspector result, re-pricing with old and new amounts, reason, defect hold-back, amount to pay now.
- **Actions.** Approve (with one-time code, DA-01), question, dispute.
- **States.** Approval window: "If you do nothing by 21 Aug, we remind you. Nothing is paid until you approve." (01 v0.2 Milestone model: silence is never approval; issue I-14 closed.) Fail result: no approve button; "No payment. The contractor must fix and resubmit."
- **Rules.** RUL-18 change shown before approval; RUL-11 client approval does not release on its own.
- **Satisfies.** FR-BLD-005 to FR-BLD-007, RUL-09, RUL-11, RUL-18.

### W-21 Listings search and map · SCR-PTL-26

```text
+----------------------------------------+
| Verified listings                      |
| [ Tema, East Legon, Kasoa... ] Search  |
| Filters (3)  Sort: newest check v      |
| [ List ]  [ Map ]                      |
| +------------------------------------+ |
| | [plot img] Plot, 100 x 70 ft       | |
| | Community 25, Tema                 | |
| | USD 24,000                         | |
| | (v) Fidero Verified, checked 3 Jun | |
| +------------------------------------+ |
| | [plot img] 3-bed, off-plan unit    | |
| | Oyarifa Gardens [SAMPLE ESTATE]    | |
| | USD 61,500                         | |
| | (v) Fidero Verified, checked 20 May| |
| +------------------------------------+ |
| Showing 2 of 2. Prices set by sellers. |
+----------------------------------------+
```

- **Content.** Card per listing with price, size, locality, badge with check date. Map view shows numbered pins plus the same list below; no information only on the map.
- **Actions.** Search, filter (region, locality, price, size, type, verification date), toggle list or map, open detail.
- **States.** Empty with suggestions; map fails to load: list stays usable.
- **Rules.** Only Live listings appear (FR-LST-002). Map pan and zoom have button alternatives (WCAG 2.5.7).
- **Satisfies.** FR-LST-004, FR-LST-010, J-04.

### W-22 Listing detail · SCR-PTL-27

```text
+----------------------------------------+
| <- Listings                            |
| [ photo placeholder ]                  |
| Plot, 100 x 70 ft, Community 25, Tema  |
| USD 24,000                             |
| +------------------------------------+ |
| | (v) FIDERO VERIFIED                | |
| | Checks done 3 June 2027            | |
| | Badge valid until 1 Sept 2027      | |
| | [ Read the full report ]           | |
| +------------------------------------+ |
| Seller: Sample Estates Ltd             |
| Track record: 12 sales, 0 disputes >   |
| Before you pay, Fidero runs a fresh    |
| search and site check. Your money is   |
| held by a licensed bank.               |
| [ Reserve this plot ]  [ Ask Fidero ]  |
+----------------------------------------+
```

- **Content.** Badge (CMP-23) with check date and expiry, full report link, seller track record, what happens on reserve.
- **Actions.** Read report (always available, RUL-14), reserve (sign in needed), enquire through Fidero.
- **States.** Expired: badge shows "(x) Badge expired 1 Sept 2027. Checks are out of date." and reserve is removed. Suspended: "Under review. This listing cannot be reserved now." Reserved by someone else: "Reserved. Check back after 30 Sept."
- **Rules.** RUL-12, RUL-13, RUL-14.
- **Satisfies.** FR-LST-003, FR-LST-005, FR-LST-006, FR-RAT-003, J-04.

### W-23 Dispute · SCR-PTL-29

```text
+----------------------------------------+
| <- Escrow ESC-2027-0031                |
| Dispute DSP-2027-0004                  |
| NOW: Waiting for the seller's response |
| by 11 May (5 working days).            |
| (lock) Release frozen. No money can    |
| move until this is decided.            |
| Steps                                  |
| (v) Opened by you ........ 4 May       |
| (o) Seller response ...... by 11 May   |
| ( ) Evidence ............. by 25 May   |
| ( ) Decision ............. by 8 Jun    |
| Your statement   Read >                |
| Evidence (3 files)  [ + Add ]          |
| [ Withdraw dispute ]                   |
+----------------------------------------+
```

- **Content.** Status sentence, frozen notice, step deadlines, statements, evidence, decision with reasons when made.
- **Actions.** Open (reason picker plus free text plus evidence), add evidence before the deadline, withdraw.
- **States.** Referred to mediation; decided (outcome, reasons, decider name, what happens to the money).
- **Rules.** RUL-15; FR-DSP-003 deadlines in working days.
- **Satisfies.** FR-DSP-001 to FR-DSP-005, J-07.

### W-24 Partner sharing and consent · SCR-PTL-21

```text
+----------------------------------------+
| <- Account   Sharing                   |
| Who can see your reports               |
| Sample Bank Ghana [SAMPLE]             |
| asked about Plot 14, Kasoa on 2 Sept   |
| What may they see?                     |
| ( ) Nothing beyond "a report exists"   |
| (*) Verdict and date only              |
| ( ) Full report                        |
| [ Save my choice ]                     |
| You can change this at any time. We    |
| keep a record of each choice.          |
| Case studies                           |
| [ ] Fidero may use an anonymised       |
|     version of my report               |
+----------------------------------------+
```

- **Content.** Partner name, what they asked, three plain levels.
- **Actions.** Choose, save, withdraw (same control).
- **States.** Saved with time; withdrawn takes effect for the next API call.
- **Rules.** RUL-16; default is the most private level.
- **Satisfies.** FR-PTR-002, FR-RPT-011, J-06.

### W-25 Home dashboard · SCR-PTL-36

```text
+----------------------------------------+
| FIDERO            Ghana · GHS   Ama (v)|
+----------------------------------------+
| At home                                |
| 2 things need you. 5 running.          |
|                                        |
| PROPERTY (3)                     See > |
| +------------------------------------+ |
| | Plot 14, Kasoa · Land check        | |
| | Searches lodged 12 Mar. Results    | |
| | expected by 2 Apr.                 | |
| +------------------------------------+ |
| | Escrow ESC-2027-0031 · Partner Bank| |
| | ! Your approval is needed.         | |
| +------------------------------------+ |
| | House, Tema · Rent due 1 Sept      | |
| | Paid by tenant to your account at  | |
| | Partner Bank, 1 Aug, GHS 4,500.00  | |
| +------------------------------------+ |
| FAMILY (3)                       See > |
| +------------------------------------+ |
| | Mother · Komfo Anokye Teaching     | |
| | Hospital                           | |
| | ! Invoice GHS 3,850.00 waiting for | |
| |   your approval.                   | |
| +------------------------------------+ |
| | Kofi and Yaw · Sample School, fees | |
| | Term 1 paid to Sample School,      | |
| | account ending 2210. Term 2 due    | |
| | 5 Jan.                             | |
| +------------------------------------+ |
| | Mother · care visits (2 a week)    | |
| | Visit confirmed Tue 09:02-10:15.   | |
| | Next: Fri 15 Aug.                  | |
| +------------------------------------+ |
| PROJECTS AND ERRANDS (1)         See > |
| +------------------------------------+ |
| | Ghana Card renewal · Errand        | |
| | Lodged at the agency 11 Aug.       | |
| | Card expected by 9 Sept.           | |
| +------------------------------------+ |
| Held at Partner Bank for you           |
| GHS 5,000.00  Statement >              |
| [ + Add something at home ]            |
+----------------------------------------+
| Home   Property   Family  Projects Acct|
+----------------------------------------+
```

- **Content.** Country and currency in the header (from configuration, DA-09). One line that counts what needs the client. One section per product family, in the order Property, Family, Projects and errands. Each item is a card with the object's name and one status sentence (CMP-06 pattern). Items that need the client come first in their section and carry "!" with the word. The held balance (FR-ESC-014) shows as money at the bank with a statement link, never as a wallet (DA-08).
- **Actions.** Open any item; "See" per section; add something at home (opens a chooser: a check on land or a building, a family member, an institution, a property, an errand, a project).
- **States.** Empty section: hidden. First use: one card, "Nothing running yet. Start with a check on a plot, or add a family member to pay a school or hospital directly." Two countries: a country chip on each card and a grouping control. Error: last good data with its time.
- **Rules.** Every money line names who was paid and where it is held (RUL-22, RUL-24, rule 7). No amounts in push, SMS or WhatsApp above the threshold (FR-NTF-004). Status sentences from templates (FR-CASE-007).
- **Satisfies.** F-35, FR-ACC-012, FR-CASE-007, FR-ESC-014, FR-CTY-001, RUL-22, RUL-24.

### W-26 Add an institution · SCR-PTL-39

```text
+----------------------------------------+
| <- Family                              |
| Add a school, hospital or agency       |
| Search Fidero's verified list          |
| [ Komfo Anokye_________________ ] Find |
| +------------------------------------+ |
| | (v) VERIFIED by Fidero 12 Jan 2027 | |
| | Komfo Anokye Teaching Hospital     | |
| | Kumasi · Hospital                  | |
| | Registration checked               | |
| | Bank account in the hospital's     | |
| | name, ending 4471                  | |
| | Contact: Accounts office           | |
| | [ Use this institution ]           | |
| +------------------------------------+ |
| Not listed?                            |
| [ Propose an institution ]             |
| We verify it before any payment:       |
| registration, an account in its own    |
| name, and a named contact. About 5     |
| working days (sample).                 |
+----------------------------------------+
| PROPOSED (status card)                 |
| (o) Sample Clinic, Tema                |
|     Checking. Started 3 Aug. Expected  |
|     by 10 Aug. No payment until done.  |
+----------------------------------------+
| NOT VERIFIED (status card)             |
| (x) Sample Pharmacy, Kumasi            |
|     The bank account given is in a     |
|     person's name, not the pharmacy's. |
|     We cannot pay it. We have asked    |
|     the pharmacy for its own account.  |
+----------------------------------------+
```

- **Content.** Institution card (CMP-26) with verified status and date, type, what was checked, the account's last four digits, named contact role (not a person's name, NFR-PRIV-02).
- **Actions.** Search the verified list; use an institution; propose a new one (name, type, town, contact, any invoice).
- **States.** Verified, Checking (with expected date), Not verified (with the reason in words and what Fidero is doing), Re-verifying (account changed; payments paused).
- **Rules.** No payment to an institution that is not Verified (RUL-22, FR-ESC-015). Account changes need a second staff member (FR-ADM-003).
- **Satisfies.** FR-FEE-001, RUL-22, J-09.

### W-27 Pay an invoice · SCR-PTL-40

```text
+----------------------------------------+
| <- Mother's statement                  |
| Pay an invoice                         |
| Komfo Anokye Teaching Hospital         |
| (v) Verified · account ending 4471     |
| For: Comfort Mensah (your mother)      |
|                                        |
| Invoice                                |
| (*) Sent by the hospital to Fidero     |
|     KATH-2027-08812 · 14 Aug           |
| ( ) Upload an invoice [ Choose file ]  |
| +------------------------------------+ |
| | Patient ......... Comfort Mensah   | |
| | Ward, 3 nights; medicines; tests   | |
| | Amount .......... GHS 3,850.00     | |
| | Due ............. 20 Aug           | |
| +------------------------------------+ |
| Our checks                             |
| (v) Hospital matches the verified      |
|     institution                        |
| (v) Patient matches your family member |
| (v) Amount and reference readable      |
|                                        |
| How to pay                             |
| (*) From the money held for you at     |
|     Partner Bank (GHS 5,000.00)        |
| ( ) Pay GHS 3,850.00 into Partner Bank |
|     now (card or mobile money)         |
| Fidero's charge   GHS 40.00 (sample)   |
|                                        |
| Who gets paid                          |
| GHS 3,850.00 to Komfo Anokye Teaching  |
| Hospital, account ending 4471. Nobody  |
| else can be paid from this invoice.    |
|                                        |
| [x] I have checked this invoice        |
| Code sent to your phone [______]       |
| [ Approve: pay GHS 3,850.00 to Komfo   |
|   Anokye Teaching Hospital ]           |
| After you approve, two Fidero staff    |
| approve and Partner Bank pays. The     |
| receipt comes back to your statement.  |
+----------------------------------------+
```

- **Content.** Institution and family member on top with verified status. Invoice source (institution-sent or uploaded). Invoice details. The three checks in words. Payment source: held balance or a new payment into the bank. The payee line (CMP-30) before the button. Fidero's charge shown separately.
- **Actions.** Choose invoice source; upload; approve with one-time code (DA-01); question the invoice.
- **States.** Check fails: that line turns to "(x) The patient on this invoice is Kwame Mensah, not Comfort Mensah. Check with the hospital." and the approve button is replaced by "Upload a corrected invoice" and "Ask Fidero". Unreadable: document request. Held balance short: "GHS 1,150.00 more is needed. Pay the difference into Partner Bank." Approved: receipt state "You approved GHS 3,850.00 on 15 Aug 09:40 GMT. Next: Fidero approvals, then Partner Bank pays the hospital."
- **Rules.** Payee is fixed to the verified institution's account (RUL-22, FR-ESC-015). Client approval alone releases nothing (RUL-11). Money is at the bank (RUL-01).
- **Satisfies.** FR-FEE-002, FR-FEE-003, FR-ESC-014, FR-ESC-015, RUL-11, RUL-22, J-09.

### W-28 Family-member statement · SCR-PTL-42

```text
+----------------------------------------+
| <- Family                              |
| Comfort Mensah (your mother)           |
| Kumasi · Ghana · GHS                   |
| +------------------------------------+ |
| | NOW: Partner Bank paid Komfo       | |
| | Anokye Teaching Hospital on 15 Aug | |
| | at 10:12 GMT. Receipt attached.    | |
| +------------------------------------+ |
| Held at Partner Bank for you           |
| GHS 1,150.00     [ Add money ]         |
|                                        |
| Statement                              |
| 15 Aug  Paid to Komfo Anokye Teaching  |
|         Hospital, acct ending 4471     |
|         Invoice KATH-2027-08812        |
|         -GHS 3,850.00   Receipt (pdf) >|
|         Discharge note (hospital) >    |
| 15 Aug  Fidero's charge                |
|         -GHS 40.00      Receipt >      |
| 2 Aug   You paid into Partner Bank     |
|         +GHS 5,000.00   Bank ref >     |
| 14 Jul  Paid to Sample Pharmacy, acct  |
|         ending 0932 · in person by a   |
|         Fidero runner, receipt attached|
|         -GHS 210.00     Receipt >      |
| Balance held 1 Jul .... GHS 1,360.00   |
|                                        |
| Care visits (R2)   Insurance (R2) >    |
| [ Download statement (PDF) ]           |
+----------------------------------------+
```

- **Content.** Status sentence. Held balance at the bank. Statement rows (CMP-25): date, payee with account ending, invoice reference, amount with sign, links to receipt and any confirmation the institution agreed to share. The in-person exception (FR-FEE-006) is spelled out on its row (DA-10).
- **Actions.** Add money (bank instructions, SCR-PTL-18 pattern); open receipts; download PDF; filter by institution.
- **States.** Payment pending: row shows "Approved by you 15 Aug. Waiting for Fidero approvals." in place of the receipt link. Receipt not yet returned: "Receipt expected from the hospital by 18 Aug." Empty: "No payments yet. Add an institution to start."
- **Rules.** Every row names the payee (RUL-22). The balance is described as held by the bank (RUL-01, DA-08). Health details appear only where the institution agreed and the client asked (FR-FEE-004, NFR-PRIV-02).
- **Satisfies.** FR-FEE-004, FR-FEE-006, FR-FEE-007, FR-ESC-014, RUL-22, J-09.

### W-29 Care plan setup · SCR-PTL-43

```text
+----------------------------------------+
| <- Family                              |
| Care visits for Comfort Mensah         |
| Address                                |
| [ House 12, Ahodwo, Kumasi______ ]     |
| Ghana Post GPS (if known) [AK-___-___] |
| How often?                             |
| ( ) Weekly  (*) Twice a week ( ) Daily |
| Days  [x] Tue [x] Fri   Time <morning> |
| What should the carer do?              |
| [x] Pick up and check medicines        |
| [x] Blood pressure reading             |
| [ ] Prepare a meal                     |
| [x] Companionship, 30 minutes          |
| [ ] Transport to an appointment        |
| Photos agreed with the family          |
| [x] Medicines laid out                 |
| [x] Blood pressure monitor reading     |
| [ ] Photo of your mother (ask her)     |
| Who may confirm a visit?               |
| [x] Comfort Mensah (by call or code)   |
| [x] Akua Mensah, sister, +233 24...    |
| Price per visit  GHS 120.00 (sample)   |
| Fidero's charge  included              |
| Paid to the carer only after the       |
| family confirms the visit.             |
| [ Set up care visits ]                 |
+----------------------------------------+
```

- **Content.** Address, frequency, plan items, agreed photos (consent is explicit), confirmers, price, the payment rule in words.
- **Actions.** Save; edit later; pause visits (holiday).
- **States.** No carer yet: "We are finding a vetted carer in Kumasi. Expected by 20 Aug. Nothing is charged until the first confirmed visit." Carer assigned: card with name, photo and Fidero ID, sent to the family too.
- **Rules.** RUL-23: payment only on confirmed visits. Photos of a person need their consent (FR-DPR-002 practice).
- **Satisfies.** FR-CARE-001, FR-CARE-002, RUL-23, J-10.

### W-30 Carer visit on the field app · SCR-MOB-14 to 16

```text
+--------------------------------+   +--------------------------------+
| Today · Tue 12 Aug             |   | <- Visit · Comfort Mensah      |
| Comfort Mensah, Ahodwo         |   | Checked in 09:02 · at address  |
| Planned 09:00 to 10:00         |   | Plan (2 of 4 done)             |
| You are 40 m from the address. |   | [v] Medicines checked          |
|                                |   |     (camera) photo 09:10       |
| [ Check in ]                   |   | [v] Blood pressure 128/82      |
|                                |   |     (camera) monitor 09:21     |
| If you cannot reach the house, |   | [ ] Companionship 30 min       |
| tap "Raise a concern".         |   | [ ] Ask about appointment      |
| [ Raise a concern ]            |   | [ Raise a concern ]            |
+--------------------------------+   | [ Check out ] (2 items left)   |
                                     +--------------------------------+
+--------------------------------+
| Check out · 10:15              |
| Visit lasted 1 h 13 min.       |
| Read this code to the family:  |
|          4 7 2 9               |
| They confirm by tapping the    |
| link we sent, or by phone.     |
| Paid after the family confirms.|
| [ Finish ]                     |
| (!) Offline: saved on phone.   |
+--------------------------------+
```

- **Content.** One visit at a time. Distance to the address before check-in. Plan items with in-app photos where agreed. Code at check-out. The payment rule in one line.
- **Actions.** Check in; tick items; capture (camera only); raise a concern (health, safety, welfare); check out; finish.
- **States.** Too far from the address: check-in allowed but marked "410 m from the address. Say why." with a required note; the visit is flagged for review. Items left at check-out: allowed with a reason ("Mother was asleep"); shown to the client. Offline: queue as W-17.
- **Rules.** Check-in and out with GPS (FR-MOB-012). Camera only (RUL-08 applied to visits through FR-MOB-010). The carer never sees the client's payment details.
- **Satisfies.** FR-MOB-010, FR-MOB-012, FR-CARE-003, FR-CARE-006, RUL-23, J-10.

### W-31 Family confirmation · SCR-PTL-45

```text
+----------------------------------------+
| FIDERO                                 |
| Did Grace visit Comfort today?         |
| Tuesday 12 August, about 09:00-10:15   |
|                                        |
| Code Grace read to you                 |
| [ _ _ _ _ ]                            |
|                                        |
| [       Yes, the visit happened   ]    |
|                                        |
| [ No, nobody came ]                    |
|                                        |
| This link works for 24 hours. Kwabena  |
| in New Jersey sees your answer. You    |
| can also call Fidero: 030 000 0000     |
| (sample).                              |
+----------------------------------------+
| AFTER "YES"                            |
| (v) Thank you. Visit confirmed 10:20.  |
+----------------------------------------+
| AFTER "NO"                             |
| We are sorry. Fidero will call you     |
| today. The carer is not paid for this  |
| visit.                                 |
+----------------------------------------+
```

- **Content.** One question, the carer's first name, the time, a 4-digit code field (CMP-28), two buttons, a plain line on who sees the answer.
- **Actions.** Confirm with code; say the visit did not happen; call Fidero.
- **States.** Wrong code: "That code does not match. Ask Grace to read it again, or tap 'No, nobody came'." Link expired: "This link has expired. Fidero will call you." Already answered: shows the answer and time.
- **Rules.** No account needed (DA-07). Large text (20 px body), 56 px buttons, works on a basic phone browser. No amounts shown.
- **Satisfies.** FR-CARE-004, RUL-23, J-10.

### W-32 Property dashboard with rent and repairs · SCR-PTL-47

```text
+----------------------------------------+
| <- Property                            |
| House, Community 4, Tema  PMG-2027-003 |
| Ghana · GHS                            |
| +------------------------------------+ |
| | NOW: Rent for August was paid by   | |
| | the tenant to your account at      | |
| | Partner Bank on 1 Aug. Repair      | |
| | quotes are waiting for you.        | |
| +------------------------------------+ |
| ! Approve a repair quote   [ Review ]  |
|                                        |
| Tenancy                                |
| Tenant ....... Verified, since 1 Mar   |
| Agreement .... Checked, 12 months >    |
| Rent ......... GHS 4,500.00 a month    |
| Paid to ...... your account at Partner |
|                Bank, ending 8820       |
| Fidero never receives your rent.       |
|                                        |
| Rent record                            |
| Aug  (v) Paid 1 Aug  GHS 4,500.00      |
| Jul  (v) Paid 3 Jul  GHS 4,500.00      |
| Jun  (!) Late, paid 9 Jun (8 days)     |
| May  (v) Paid 1 May                    |
|                                        |
| Repairs                                |
| (!) Leaking roof, bedroom 2            |
|     2 quotes ready. Approve one >      |
| (v) Water pump · paid to Sample        |
|     Plumbing Ltd, acct ending 1177,    |
|     14 Jun, after inspection           |
| Inspections   Next: 15 Sept            |
| Photo timeline  [img][img][img] >      |
+----------------------------------------+
```

- **Content.** Status sentence. Tenancy summary with where rent goes (RUL-24). Rent record by month with the state in words. Repairs with payee named. Inspections and photo timeline.
- **Actions.** Review quotes; see the agreement; report a repair; order an extra inspection; see photos.
- **States.** Rent late: "(!) Late since 6 Sept. Fidero contacted the tenant on 7 Sept." Not yet confirmed by the bank: "(o) Not yet confirmed by the bank" (never shown as missing). Vacant: "No tenant. Fidero is finding one."
- **Rules.** Rent to the owner's own account, never Fidero (RUL-24). Repair contractors paid only after inspection (FR-PMG-005, RUL-22).
- **Satisfies.** FR-PMG-002, FR-PMG-003, FR-PMG-005, FR-PMG-006, RUL-22, RUL-24, J-11.

### W-33 Repair quote approval · SCR-PTL-48

```text
+----------------------------------------+
| <- House, Tema                         |
| Leaking roof, bedroom 2                |
| Reported by the tenant 2 Aug · photos >|
| Inspector's note: flashing failed,     |
| about 4 m2 of sheets to replace.       |
|                                        |
| Quotes from vetted contractors         |
| +------------------------------------+ |
| |(*) Sample Roofing Ltd              | |
| |    GHS 6,200.00 · 3 days           | |
| |    Track record: 9 repairs, 0      | |
| |    disputes · Quote (pdf) >        | |
| +------------------------------------+ |
| |( ) Sample Builders Ltd             | |
| |    GHS 7,450.00 · 5 days           | |
| |    Track record: 14 repairs, 1     | |
| |    dispute (resolved) · Quote >    | |
| +------------------------------------+ |
| ( ) Neither. Ask for new quotes        |
|     Why? [_______________________]     |
|                                        |
| If you approve                         |
| GHS 6,200.00 is held at Partner Bank   |
| until an inspector passes the work.    |
| Then Partner Bank pays Sample Roofing  |
| Ltd, account ending 3301.              |
| Fidero's charge  GHS 150.00 (sample)   |
| Code sent to your phone [______]       |
| [ Approve Sample Roofing, GHS 6,200 ]  |
+----------------------------------------+
```

- **Content.** The problem with evidence, at least two quotes as radio cards with price, time and track record, a rejection option with reason, the payee line and the hold rule.
- **Actions.** Approve one quote with a code (DA-01); reject both with a reason; ask a question.
- **States.** Only one quote in: approve button disabled with "We need at least two quotes (FR-PMG-004). Second quote expected by 9 Aug." Rejected: "New quotes expected by [date]." Approved: "Held at Partner Bank. Work starts about 12 Aug. Inspection after."
- **Rules.** Two quotes minimum (FR-PMG-004). Money held until inspection (FR-PMG-005). Payee named (RUL-22). Client approval is not a release (RUL-11).
- **Satisfies.** FR-PMG-004, FR-PMG-005, FR-RAT-003, RUL-11, RUL-22, J-11.

### W-34 Errand progress · SCR-PTL-50

```text
+----------------------------------------+
| <- Projects and errands                |
| Ghana Card renewal      TSK-2027-0088  |
| Ghana · GHS · agent: Fidero-vetted     |
| +------------------------------------+ |
| | NOW: Lodged at the NIA office on   | |
| | 11 Aug. Receipt attached. Card     | |
| | expected by 9 Sept (target,        | |
| | assumption).                       | |
| +------------------------------------+ |
| Checklist (4 of 4 received)            |
| [v] Old Ghana Card photo  [v] Proof of |
|     address  [v] Passport photo        |
| [v] Signed form                        |
| Fees                                   |
| Official fee  GHS 125.00 (sample)      |
|   Paid to National Identification      |
|   Authority, acct ending 0450, 11 Aug  |
|   Receipt >                            |
| Fidero's charge  GHS 180.00 (sample)   |
|   Held at Partner Bank until the card  |
|   is in your representative's hands.   |
| Steps                                  |
| (v) Documents checked ....... 8 Aug    |
| (v) Fees paid into Partner Bank 9 Aug  |
| (v) Lodged, receipt uploaded . 11 Aug  |
| ( ) Card ready ....... expected 9 Sept |
| ( ) Fidero checks the card             |
| ( ) Handed to Kofi A. (your rep)       |
| Messages >   Receipts (2) >            |
+----------------------------------------+
```

- **Content.** Status sentence, checklist, fees with payees, steps with evidence. The agency is named as payee; the agent is never a payee.
- **Actions.** Upload a missing document; see receipts; message Fidero; change the representative.
- **States.** Rejected by the agency: "(x) Rejected by the NIA on 12 Aug: passport photo out of date. We need a new photo from you by 19 Aug." Late: "The agency is late. New expected date 23 Sept. We are chasing." Complete: "Handed to Kofi A. on 10 Sept, signed for. Photo of the card >". Document wrong at check: "The card shows the wrong date of birth. Our agent has returned it to the agency."
- **Rules.** Official fees to the agency's account only (RUL-22, FR-TSK-003). Completion only on the checked document (FR-TSK-004). Fidero's charge released on completion (RUL-23).
- **Satisfies.** FR-TSK-002 to FR-TSK-005, RUL-22, RUL-23, J-12.

### W-35 Insurer product page · SCR-PTL-51

```text
+----------------------------------------+
| <- Family                              |
| Health cover for a parent in Ghana     |
| +------------------------------------+ |
| |  SAMPLE INSURER GHANA LTD          | |
| |  Licensed insurer, NIC licence     | |
| |  no. [TO VERIFY]                   | |
| |  A policy from Sample Insurer.     | |
| |  Fidero does not hold the risk.    | |
| +------------------------------------+ |
| Family Health Plan (sample)            |
| Covers: in-patient care, consultations,|
| medicines up to GHS 20,000 a year      |
| (sample). Waiting period 30 days.      |
| Does not cover: ... Read the policy    |
| wording (Sample Insurer) >             |
| Premium   GHS 95.00 a month (sample)   |
|   Paid to Sample Insurer Ghana Ltd,    |
|   account ending 6610. Never to Fidero.|
| Claims     Decided and paid by Sample  |
|   Insurer. Fidero helps you start one  |
|   and tracks the insurer's answer.     |
| Fidero's role  We check the insurer is |
|   licensed, pass on your application   |
|   and keep your policy documents.      |
|   Fidero is not the insurer.           |
| [ Apply with Sample Insurer ]          |
| Insurance is regulated by the National |
| Insurance Commission [TO VERIFY].      |
+----------------------------------------+
```

- **Content.** The insurer's name and licence first and largest (CMP-31). The fixed line "A policy from [insurer]. Fidero does not hold the risk." What is covered, what is not, the premium with its payee, how claims work, Fidero's role in three sentences.
- **Actions.** Read the insurer's policy wording; apply (application is passed to the insurer); compare plans from other insurers if more than one partner.
- **States.** No partner insurer in this country: page not shown; dashboard shows no insurance section. Application sent: "Sent to Sample Insurer on 3 Sept. The insurer decides within 5 working days (sample)." Declined by the insurer: shown with the insurer's reason and contact.
- **Rules.** The insurer's name appears before Fidero's on the page (RUL-25). Premiums go to the insurer's account (FR-INS-002). No Fidero brand colour on the product name; the product is the insurer's.
- **Satisfies.** FR-INS-001, FR-INS-002, RUL-25.

### W-36 Admin: country configuration · SCR-BO-29

```text
+------------------------------------------------------------------------------------+
| Admin > Countries        [ Ghana · Live v ]   [ + Open a new country ]             |
+------------------------------------------------------------------------------------+
| Ghana (GH)    Configuration v1.4, live since 3 Mar 2027    [ Compare with v1.3 ]   |
| Section                 Status      Last change                Owner               |
| Currency and rates      GHS; USD guide; GBP, EUR, CAD guides   Admin, 1 Mar        |
| Holiday calendar        14 days 2027 [TO VERIFY]  Admin, 1 Feb                     |
| Working-day rules       Mon-Fri, excludes calendar             Admin               |
| Partner bank            Partner Bank (SAMPLE); account changes need 2 admins       |
| Insurer partners        Sample Insurer Ghana Ltd (health, funeral) · licence file  |
| Licence bodies          Ghana Bar Association; Licensed Surveyors Association      |
| Case templates          Land v1.3, Building v1.1 (see Templates)                   |
| Report scope statement  v1.0 (locked; lawyer and insurer approval on file)         |
| Overlay layers          Acquisitions v3, Road reserves v2, Wetlands v1, Flood v1   |
| Institution types       School, Hospital, Clinic, Pharmacy, Agency, Utility        |
| Errand catalogue        12 items (Ghana Card, passport, title, probate ...) v1.0   |
| Legal texts             Privacy notice v2, Terms v1.0, Escrow terms v1.0           |
| Data location           Region: [TO VERIFY] · backups: [TO VERIFY] (Q-11)          |
| Languages               English (Ghana). Twi, Ga, Ewe: not enabled                 |
+------------------------------------------------------------------------------------+
| Nigeria (NG)  Draft, copied from Ghana v1.4 on 1 Nov 2026  [ Edit ] [ Checklist ] |
| 9 of 14 sections still carry Ghana values. Cannot go live until all are reviewed   |
| and the data location is set (FR-CTY-002). Manual phase gate: not yet passed.      |
+------------------------------------------------------------------------------------+
```

- **Content.** One record per country with every configurable section from FR-CTY-001, each with status, version and owner. A draft country shows how many sections still hold copied values.
- **Actions.** Edit a section (versioned, logged); compare versions; open a new country by copying (FR-CTY-004, R2); run the go-live checklist.
- **States.** Live, Draft, Manual phase (no software yet; configuration being prepared), Suspended. A value that affects a release needs a second administrator (FR-ADM-005). `[TO VERIFY]` values show a warning chip.
- **Rules.** Nothing about Ghana is hard-coded (B2.9). Bank and insurer account changes need two administrators (FR-ADM-003). A country cannot go live until its data location is set and its manual phase gate is recorded as passed (C-13).
- **Satisfies.** FR-CTY-001, FR-CTY-002, FR-CTY-004, FR-ADM-003, FR-ADM-005.

---

## 5. Interaction and content design

### 5.1 Status messages

Every case, escrow, milestone, listing and dispute shows one status sentence at the top (FR-CASE-007, B2.3). Status messages are written from templates held in translation files (NFR-LOC-01, FR-NTF-002).

**Pattern.** `[What happened] [where] on [date]. [What happens next] by [date].`

| Situation | Template output (sample) |
|---|---|
| Step done, next known | "Searches lodged at the Lands Commission on 12 March. Results expected by 2 April." |
| Waiting on the client | "We need the seller's ID copy from you. Please upload it by 20 March so we stay on time." |
| Waiting on a third party | "The surveyor visits the plot on 18 March. You do not need to do anything." |
| Late | "Search results are late. We expected them by 2 April. We are chasing the Lands Commission and will update you by 9 April." |
| Paused | "Your case is paused. We are waiting for the family head to fix a date for the consent meeting." |
| Blocked money | "The release is waiting for one condition: the seller's tax clearance. The seller's lawyer expects it by 6 May." |
| Frozen | "A dispute was opened on 4 May. No money can move until it is decided. Decision due by 8 June." |
| Done | "Partner Bank paid the seller on 7 May at 11:05 GMT. Your purchase is complete." |
| Institution paid (J-09) | "Partner Bank paid Komfo Anokye Teaching Hospital, account ending 4471, on 15 August at 10:12 GMT. Receipt attached." |
| Invoice mismatch | "The invoice names a different patient. Nothing has been paid. Check with the hospital and upload a corrected invoice." |
| Recurring fee due | "Term 2 fees for Kofi and Yaw are due to Sample School by 5 January. Approve the payment by 29 December." |
| Visit confirmed (J-10) | "Grace visited your mother on Tuesday from 09:02 to 10:15. Comfort confirmed the visit at 10:20." |
| Visit unconfirmed | "Tuesday's visit is not yet confirmed. We have asked the family. The carer is not paid until it is." |
| Visit missed | "The carer did not check in for Friday's visit. We called the family at 10:30 and are arranging another visit." |
| Rent paid (J-11) | "August rent was paid by the tenant to your account at Partner Bank on 1 August." |
| Rent late | "September rent is late. It was due on 1 September. Fidero contacted the tenant on 7 September." |
| Quote rejected | "You rejected both quotes on 8 August. New quotes expected by 15 August." |
| Errand rejected (J-12) | "The agency rejected the application on 12 August: the passport photo is out of date. We need a new photo from you by 19 August." |
| Errand complete | "Your Ghana Card was handed to Kofi A. on 10 September and signed for. The errand is complete." |

Rules:

- One sentence for what happened, one for what next. Never more than 30 words in total.
- Always a date. Use "expected" for estimates and "by" for deadlines.
- Name the institution, not the person, for third parties (data minimisation, NFR-PRIV-02).
- Never blame the client. Never guess at reasons Fidero does not know.
- SMS and WhatsApp versions carry no report contents, no amounts above the threshold and no third-party personal data (FR-NTF-004). They say "There is an update on your case FID-2027-0142. Open the Fidero app or website to see it."

### 5.2 Empty, loading, error and offline states

| State | Pattern | Sample copy |
|---|---|---|
| Empty, first use | Plain explanation and one action (CMP-16) | "You have no checks yet. Order one to find out if a plot is safe to buy." [Order a check] |
| Empty, filtered | Say why and offer to clear filters | "No listings match. Try a wider price range." [Clear filters] |
| Loading, under 1 s | Nothing shown | |
| Loading, 1 s or more | Skeleton in the shape of the content (CMP-21). Keep any data already on screen. | |
| Loading, 10 s or more | Add a sentence | "This is taking longer than usual. Your connection may be slow." |
| Error, recoverable | Inline message near the cause, with a fix | "That file is too large (14 MB). The limit is 10 MB [TO VERIFY]. Try a photo instead of a scan." |
| Error, page | Keep the shell and last good data with its time | "We could not load the latest status. Showing what we had at 09:14 GMT." [Try again] |
| Error, server | Reference for support, no technical detail | "Something went wrong on our side. Reference T-7F3A. Try again in a minute." |
| Offline, web | Banner (CMP-13). Forms keep input. Submit queues only where safe; payments never queue. | "You are offline. You can keep reading. We will send your upload when you reconnect." |
| Offline, app | Banner with queue count, always visible | "Offline. 7 items saved on this phone." |
| Blocked | Say what blocks it, who must act, and by when | "Release blocked: 1 condition open." |

### 5.3 Confirmation of irreversible actions

Irreversible actions: pay a fee, accept escrow terms, approve an escrow release as the client, sign a report section, release a report, approve a release or refund, submit a milestone, submit an inspection result, approve an invoice payment, approve a repair quote, confirm or deny a care visit, apply for an insurer's policy, open a dispute, publish a template or a country configuration, approve a bulk export.

Pattern:

1. A summary panel that says, in one sentence, what will happen and to whom. Example: "Pay USD 18,000.00 from escrow at Partner Bank to Kofi Asante."
2. One or more statements the user must tick, written as facts they confirm: "I checked the evidence for each condition myself."
3. Second factor where money or signatures are involved (FR-ACC-003, FR-ESC-007, DA-01).
4. A button that names the action and amount: "Approve and send instruction", never "OK" or "Yes".
5. A receipt state that shows what happened, the time, and what comes next.

No "Are you sure?" dialogs for routine actions. Reversible actions (dismiss, archive, change a filter) act at once and offer "Undo" in a toast for 8 seconds.

### 5.4 The two-person approval pattern

Used for: escrow releases and refunds (RUL-05, FR-ESC-007, FR-ESC-013), report release (RUL-03), locked scope changes (FR-ADM-004), bulk personal data export (FR-DPR-005), and bank detail changes (design rule).

- The approval card (CMP-10) has two slots, "Approval 1 of 2" and "Approval 2 of 2".
- Each filled slot shows name, role, date and time in Ghana time, and "code verified".
- The gates list sits above the slots. If any gate fails, no slot is active and the reason is shown.
- The person in slot 1 sees slot 2 as "Waiting for a different person". The button is not rendered for them, so it cannot be clicked by mistake.
- People who closed a condition or authored the work can approve only where 01 allows it. A reviewer cannot be second approver of their own work (01 C2).
- Clients see the same two slots, read only, on their tracker. This shows "people stay in the loop" (B2.6).
- Approvals expire if a gate changes after slot 1 is filled, such as a new dispute or a fresh search going out of date. The card says "Approval 1 was reset because the fresh search expired on 16 May."

### 5.5 Communicating verdicts

Verdicts are never colour alone (WCAG 1.4.1). Each uses a distinct **shape**, a **word** and a **colour**, plus a one-line meaning from the report template.

| Verdict | Icon shape | Word | Meaning line (from template) |
|---|---|---|---|
| Green | Circle with a tick | GREEN | "No material issue found within scope. You may proceed, subject to the conditions listed." |
| Amber | Triangle with "!" | AMBER | "Issues found that can be fixed before purchase. Do not pay the seller until they are fixed." |
| Red | Octagon with a cross | RED | "A serious issue. Fidero advises you not to buy." |

- The verdict word is always written, including in tables and on small screens.
- Icon shapes differ, so the verdict reads in greyscale and for colour-blind users.
- Screen readers hear "Verdict: amber. Issues found that can be fixed before purchase."
- Never use red, amber or green for anything else in the UI: not for brand, not for buttons, not for charts. Errors use the red family but always with the word "Error" or a specific message and an error icon.
- An amber report with an escrow says plainly: "Paying into escrow is safe. The bank holds the money. The seller is paid only when every condition is closed."

### 5.6 Money display

- Always show the currency code before the amount: `USD 18,000.00`, `GHS 101,500.00` (DA-03). Two decimals for money. Thousands separated with commas.
- Say who holds it: "held by Partner Bank", "paid to the contractor by Partner Bank". Never "your Fidero balance".
- Guide conversions are marked "(guide only)" in smaller text and are never used in a button label.
- Cedi re-pricing (RUL-18, FR-BLD-007) shows the agreed amount, the new amount, the change as amount and percentage, the reason, the source of the guide and its date, then the amount to pay now. The client ticks "I have seen the new price" before approving.
- Amounts are not animated and do not count up.
- SMS and WhatsApp never include amounts above the threshold (FR-NTF-004).
- **Say who gets paid (RUL-22).** Every paid or planned payment on any line carries the payee line (CMP-30): `Paid to <institution, supplier, vendor or professional>, account ending <nnnn>`. Planned: `Will be paid to Komfo Anokye Teaching Hospital, account ending 4471`. Paid: `Paid to Komfo Anokye Teaching Hospital, account ending 4471, 15 Aug`. The payee is the verified organisation's registered name, never a person's name, never a relative, never "the carer" or "the agent". The only exception is a licensed professional paid in their own name (lawyer, surveyor, inspector), shown with their licence number.
- **In-person payment (FR-FEE-006, DA-10).** `Paid in person by a Fidero runner to Sample Pharmacy, receipt attached. Cash drawn from Partner Bank against a signed voucher.` Never shortened to "paid in cash".
- **Rent (RUL-24).** `Paid by tenant to your account at Partner Bank, ending 8820`. The word "Fidero" never appears next to a rent amount except in the fixed line "Fidero never receives your rent."
- **Held balance (FR-ESC-014, DA-08).** `Held at Partner Bank for you: GHS 1,150.00`. Never "balance", "wallet", "credit" or "your Fidero account".
- **Insurance (RUL-25).** Premiums: `Paid to Sample Insurer Ghana Ltd, account ending 6610. Never to Fidero.` Claims: `Decided and paid by Sample Insurer.`
- **Fidero's own charge.** Always a separate line labelled "Fidero's charge", with its own receipt, so a client can see what Fidero earned on any item (FR-PAY-003).

### 5.6a Fixed lines for partner products and other lines

These sentences are locked text, held in translation files and changed only with the lawyer's agreement. They appear exactly as written on the screens listed.

| Line | Fixed text | Where |
|---|---|---|
| Insurer products (RUL-25) | "A policy from [insurer]. Fidero does not hold the risk." | Insurer product page (SCR-PTL-51), policy wallet (SCR-PTL-52), dashboard insurance cards, every email about a policy |
| Insurer claims (RUL-25) | "[Insurer] decides and pays claims. Fidero helps you start a claim and tracks the insurer's answer." | SCR-PTL-52 |
| Rent (RUL-24) | "Rent is paid by your tenant to your own account at [bank]. Fidero never receives your rent." | SCR-PTL-46, SCR-PTL-47, tenant view (SCR-PTL-54) |
| Institution payments (RUL-22) | "Fidero pays the school, hospital or agency directly. Money never goes to a relative or a go-between." | SCR-PTL-39, SCR-PTL-40, Family section empty state |
| Care visits (RUL-23) | "The carer is paid only for visits the family confirms." | SCR-PTL-43, SCR-PTL-44, SCR-MOB-16 |
| Errands (RUL-23) | "Official fees go to the agency. Fidero's charge is released when the finished document is checked." | SCR-PTL-49, SCR-PTL-50 |
| Project funds and events (RUL-21, RUL-22) | "Suppliers and vendors are paid directly against invoices. Fidero confirms the money was spent as agreed. It does not judge whether the plan will succeed." | SCR-PTL-30, SCR-PTL-53 |
| Country (B2.9) | "Showing your things in [country]. Prices in [currency]." | Dashboard header when the client has more than one country |

### 5.7 Voice and tone

Fidero sounds like a calm, careful professional who is on the client's side.

| Do | Don't |
|---|---|
| "We found two missing pillars." | "Unfortunately, it appears that some discrepancies may have been identified." |
| "Do not pay the seller yet." | "We would recommend that you consider delaying payment." |
| "The bank holds your money." | "Your funds are safely secured in our escrow." (Fidero holds nothing) |
| "Fresh search" with a one-line explanation on first use | Legal shorthand without explanation |
| "Seller", "family head", "Lands Commission" | Internal names: "Task 5", "Overlay layer v3" |

Reading age 12 (NFR-USE-02): sentences under 20 words, everyday words, active voice. Check every template with a readability tool before release and test with real users. Legal text (scope statement, terms) is exempt from rewriting, but each is preceded by a plain summary marked "Summary, not the legal text".

---

## 6. Design system

### 6.1 Brand direction

Name: **Fidero**. Values: trust and evidence.

The verdict colours are red, amber and green. So are the colours of the Ghana flag and of kente cloth. The brand therefore avoids them entirely, which also avoids the obvious cliché. The palette draws on two materials tied to the work:

- **Indigo**, from the dyed cloth found across West Africa. Deep, calm and serious. Used for the brand and primary actions.
- **Laterite**, the red-brown earth of Ghana's plots and roads. Used sparingly for the brand mark and illustrations only, never on controls or status, so it is never confused with a red verdict.
- **Sand** neutrals. Warm off-white backgrounds instead of cold grey, easier on low-quality screens in bright light.

The wordmark is "Fidero" set in the system sans at semi-bold. A simple mark: a square plot outline with a tick through one corner, standing for "checked land". No shields with locks, no handshakes, no padlocks on houses.

### 6.2 Design tokens

Tokens are named by role, not by colour, so themes and countries can change values without code changes. Web: CSS custom properties. Android: Compose theme values. Contrast ratios below were calculated with the WCAG 2.x formula.

#### Colour, light theme

| Token | Hex | Use | Contrast |
|---|---|---|---|
| `--color-bg` | `#FAF7F2` | Page background (sand) | |
| `--color-surface` | `#FFFFFF` | Cards, inputs | |
| `--color-surface-2` | `#F2EDE4` | Sunken areas, table stripes | |
| `--color-text` | `#1C1B19` | Body text | 16.1:1 on bg; 17.2:1 on surface |
| `--color-text-muted` | `#5A544D` | Secondary text | 7.0:1 on bg; 6.4:1 on surface-2 |
| `--color-border` | `#DDD5C8` | Dividers only (decorative) | n/a |
| `--color-border-strong` | `#7C7368` | Input and control borders | 4.7:1 on surface (UI 3:1 met) |
| `--color-primary` | `#2B3F8C` | Primary buttons, links (indigo) | 9.0:1 on bg |
| `--color-primary-hover` | `#22337A` | Hover and pressed | white text 11.5:1 |
| `--color-on-primary` | `#FFFFFF` | Text on primary | 9.6:1 |
| `--color-primary-subtle` | `#E8ECF8` | Selected rows, chips | primary text 8.1:1 |
| `--color-accent` | `#A0461E` | Brand mark, illustration (laterite) | 6.2:1 on surface |
| `--color-focus` | `#1A56DB` | Focus ring, 3 px | 5.8:1 on bg |
| `--color-info` / `--color-info-bg` | `#1D5FA8` / `#E6F0FA` | Information notes | 5.6:1 |
| `--verdict-green-fg` / `-bg` | `#0A6B4F` / `#E2F3EC` | Green verdict text and fill | 5.7:1 |
| `--verdict-green-solid` | `#0B7A5C` | Large badge fill, white text | 5.3:1 |
| `--verdict-amber-fg` / `-bg` | `#7A4300` / `#FDF0D5` | Amber verdict text and fill | 7.1:1 |
| `--verdict-amber-solid` | `#F0B429` | Large badge fill, dark text | 9.2:1 with `#1C1B19` |
| `--verdict-red-fg` / `-bg` | `#A3191B` / `#FCE8E6` | Red verdict and error text | 6.6:1 |
| `--verdict-red-solid` | `#B42318` | Large badge fill, white text | 6.6:1 |

The amber solid fill has only 1.9:1 against white. It is therefore always drawn with a 2 px `--verdict-amber-fg` border and the triangle icon, which carry the 3:1 non-text contrast (WCAG 1.4.11).

#### Colour, dark theme

| Token | Hex | Contrast |
|---|---|---|
| `--color-bg` | `#121417` | |
| `--color-surface` | `#1B1E23` | |
| `--color-surface-2` | `#252A31` | |
| `--color-text` | `#ECEAE6` | 15.4:1 on bg |
| `--color-text-muted` | `#B5AFA7` | 8.5:1 on bg; 6.6:1 on surface-2 |
| `--color-border` | `#353B45` | decorative |
| `--color-border-strong` | `#808896` | 4.7:1 on surface |
| `--color-primary` | `#A9B8F5` | 9.5:1 on bg; text on it `#0F1733` 9.1:1 |
| `--color-primary-subtle` | `#1F2747` | primary text 7.6:1 |
| `--color-accent` | `#E08A62` | 6.4:1 on surface |
| `--color-focus` | `#7FA8FF` | 7.9:1 on bg |
| `--color-info` / `-bg` | `#8EC1F5` / `#13263A` | 8.1:1 |
| `--verdict-green-fg` / `-bg` / `-solid` | `#6FD9B0` / `#0F2E25` / `#3CBF8E` | 8.5:1; dark text on solid 8.3:1 |
| `--verdict-amber-fg` / `-bg` / `-solid` | `#F7C66B` / `#33260C` / `#F0B429` | 9.3:1; dark text on solid 10.3:1 |
| `--verdict-red-fg` / `-bg` / `-solid` | `#FF9F96` / `#3A1514` / `#F2685C` | 8.2:1; dark text on solid 6.3:1 |

Dark theme follows `prefers-color-scheme` and can be set by the user. In dark theme, solid verdict badges use dark text.

#### Colour-blind check

The three solid verdict fills were simulated for full deuteranopia, protanopia and tritanopia (Machado 2009 model). Colour difference (CIE ΔE 1976) between each pair stayed above 24 in every case: green to red was 41.8 (deuteranopia), 24.8 (protanopia) and 107.5 (tritanopia). Amber is far lighter than both (lightness about 75 against about 45). Protanopia is the weakest case, which is why shape and word carry the meaning and colour only supports it. Re-test with real users who have colour vision deficiency `[TO VERIFY]` during the usability study.

#### Typography

System fonts only. No web font download, which saves 40 to 100 KB per page on 3G (NFR-PERF-02). Android uses Roboto, which already covers the Akan letters ɛ and ɔ and the Hausa hooked letters for later languages.

| Token | Size / line height | Weight | Use |
|---|---|---|---|
| `--font-sans` | `system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans", Arial, sans-serif` | | All text |
| `--font-mono` | `ui-monospace, "SF Mono", Menlo, Consolas, "Roboto Mono", monospace` | | References, hashes |
| `--text-xs` | 13 / 18 px | 400 | Metadata only, never body |
| `--text-sm` | 14 / 20 px | 400, 600 | Labels, table cells |
| `--text-md` | 16 / 24 px | 400 | Body (minimum for body text) |
| `--text-lg` | 18 / 26 px | 600 | Status sentence |
| `--text-xl` | 20 / 28 px | 600 | Card titles |
| `--text-2xl` | 24 / 32 px | 700 | Page titles on phone |
| `--text-3xl` | 30 / 38 px | 700 | Page titles on laptop |
| `--text-4xl` | 36 / 44 px | 700 | Report verdict word |

Sizes are set in `rem` so user zoom and browser text size work. Text reflows at 320 px wide and 200% zoom (WCAG 1.4.4, 1.4.10).

#### Spacing, radii, elevation, breakpoints, motion

| Group | Tokens |
|---|---|
| Spacing (4 px base) | `--space-1` 4, `--space-2` 8, `--space-3` 12, `--space-4` 16, `--space-5` 24, `--space-6` 32, `--space-7` 48, `--space-8` 64 px. Page side gutter 16 px on phone, 24 on tablet, 32 on laptop. |
| Radii | `--radius-sm` 4 (inputs, chips), `--radius-md` 8 (buttons, cards), `--radius-lg` 12 (sheets, dialogs), `--radius-pill` 999 (badges) |
| Elevation | `--elev-0` none; `--elev-1` `0 1px 2px rgba(28,27,25,.08)` cards; `--elev-2` `0 4px 12px rgba(28,27,25,.10)` sticky bars; `--elev-3` `0 12px 32px rgba(28,27,25,.18)` dialogs. Dark theme uses lighter surfaces and borders instead of shadows. |
| Breakpoints | `sm` 360, `md` 600, `lg` 900, `xl` 1200 px. Design for 360 first; support 320. |
| Touch targets | 44 × 44 px minimum on web, 48 × 48 dp on Android. Above WCAG 2.5.8's 24 px minimum. |
| Motion | `--dur-fast` 100 ms, `--dur-base` 200 ms, `--dur-slow` 300 ms; easing `cubic-bezier(.2,0,0,1)`. All motion off under `prefers-reduced-motion`. No motion is needed to understand anything. |

### 6.3 Iconography

- One outline set, 24 px grid, 2 px stroke, rounded joins. Shipped as an inline SVG sprite of no more than 40 icons and 8 KB compressed. Android uses the same shapes as vector drawables.
- Icons never stand alone for meaning. Every icon has a visible label or an accessible name.
- Reserved shapes: circle-tick (green, done), triangle-exclamation (amber, warning), octagon-cross (red, stop), padlock (locked text, frozen money), bank building (money at the bank), camera with dot (captured in app), cloud with arrow (queued upload), clock (expected date).

### 6.4 Component library

Each component lists its states, usage rules, accessibility notes and Android Compose equivalent. All use the tokens above.

| ID | Component | States and variants | Usage rules | Accessibility | Compose equivalent |
|---|---|---|---|---|---|
| CMP-01 | Button | Primary, secondary, quiet, danger. Default, hover, focus, pressed, disabled, loading | One primary per screen. Label is a verb plus object ("Pay USD 450.00"). Disabled buttons show the reason next to them. | Native `<button>`. Focus ring 3 px `--color-focus` with 2 px offset. Loading keeps the label for screen readers ("Paying"). | `Button`, `OutlinedButton`, `TextButton` with `FideroTheme` colours |
| CMP-02 | Text input | Default, focus, filled, error, disabled, read only. With hint, prefix (country code) | Label above, always visible. Hint below label. Error below field. | `<label for>`; `aria-describedby` for hint and error; `autocomplete` set; errors announced via error summary. | `OutlinedTextField` with `supportingText`, `isError` |
| CMP-03 | Radio card and select | Default, selected, focus, disabled | Use radio cards for 2 to 5 options with prices or explanations. Select for long lists. | Native radio group with `<fieldset>` and `<legend>`. | `Row` with `RadioButton` and `Modifier.selectable` |
| CMP-04 | File upload | Empty, uploading with progress, scanned OK, rejected, retry | Show size limit and allowed types. Show a thumbnail and file name. Resumable on poor connections. | Native file input with visible label. Progress in `role="progressbar"` with value text. | Not used for evidence (RUL-08); `ActivityResultContracts` for portal-like uploads only |
| CMP-05 | Stepper | Step done, current, to do; with error | 3 to 5 steps. Labels short ("Plot"). Back never loses data. | `<ol>` with `aria-current="step"`; "Step 2 of 4" in text. | Custom `Row` of steps with `semantics { stateDescription }` |
| CMP-06 | Status timeline | Done (date), current (expected date), to do, late, paused, blocked | Status sentence on top, then the timeline. Done steps show actual dates. | `<ol>`; each item says its state in words ("Done", "Expected"). | `LazyColumn` items with icon and text |
| CMP-07 | Verdict badge | Green, amber, red. Sizes: small (tables), medium (cards), large (report cover) | Always icon plus word. Large size adds the meaning line. | Text is real text. Icon `aria-hidden`. | `FideroVerdictBadge(verdict, size)` |
| CMP-08 | Condition checklist | Open, closed with evidence, overdue, not applicable (with reason) | Each item shows owner, due date, closing evidence link and closed date. | `<ul>` with state words; not interactive checkboxes for clients. | `Column` of `ListItem` with leading icon |
| CMP-09 | Evidence thumbnail | Photo, video, document. Captured in app, uploaded, flagged, pending upload | Shows capture time, server time, position check, "Captured in app" or "Uploaded", hash (short). Tap opens full view with metadata. | Alt text built from metadata ("Photo, foundation trench, 14 Aug 10:02 GMT, on plot"). | `AsyncImage` with overlay `Text`; `contentDescription` from metadata |
| CMP-10 | Approval card | 0 of 2, 1 of 2, 2 of 2, blocked, reset, read only (client view) | See section 5.4. | Each slot is a list item with name and time; button only for eligible user. | `Card` with two `ListItem` slots |
| CMP-11 | Data table | Default, sortable, selectable rows, loading, empty | Back office only. Phone: becomes stacked cards. Sticky header. | `<table>` with `<th scope>`; sort state in `aria-sort`. | `LazyColumn` (no tables in app) |
| CMP-12 | Map panel | Static image, interactive, layer legend, error | Static map image first; interactive map on tap. Legend uses pattern and label, not colour alone. | Text summary always next to the map ("Plot is 120 m from the road reserve"). Zoom and pan buttons, no drag needed (WCAG 2.5.7). | Static image in app; no interactive map in R2 |
| CMP-13 | Offline banner | Offline, back online (auto-hides after 4 s), sending (n of m), failed item | Top of screen, does not cover content. Shows queue count in the app. | `role="status"`, polite. Not focus-stealing. | `Surface` banner driven by `ConnectivityManager` and the WorkManager queue |
| CMP-14 | Toast | Success, info, with undo | Only for results of the user's own action. Not for errors that need action. Lasts 8 s; pauses on hover or focus. | `role="status"`. Undo is a real button reachable by keyboard. | `SnackbarHost` |
| CMP-15 | Modal dialog | Confirm, form, blocking error | Only for irreversible confirmation (section 5.3). Never for marketing. | Focus moves in and is trapped; Escape closes when safe; returns focus. Not obscured by sticky bars (WCAG 2.4.11). | `AlertDialog` |
| CMP-16 | Empty state | First use, filtered, done | Short sentence, one action. No large images (page weight). | Heading plus text plus button. | `Column` with `Text` and `Button` |
| CMP-17 | Money | Amount, guide, held-by line, change (old to new) | Section 5.6. | Code read as words via `aria-label` ("18,000 US dollars"). | `FideroMoney(amount, currency, holder)` |
| CMP-18 | Date and time | Date, date and time, expected, deadline | "12 March 2027"; times "14:05 GMT" plus local time for users abroad. | `<time datetime>`. | `Text` with `java.time` formatter |
| CMP-19 | Hash display | Full, short, copied, match, no match | Monospace, groups of 4, copy button, check button. | Copy result announced. | `SelectionContainer` with mono `Text` |
| CMP-20 | Inline alert | Info, warning, error, success, locked | Inside content near its cause. | `role="alert"` only for new errors after submit. | `Surface` with icon and `Text` |
| CMP-21 | Skeleton | Text lines, card, table row | Only after 1 s. Matches final layout to avoid shift. | `aria-busy="true"` on the region. | Placeholder `Box` with shimmer off under reduced motion |
| CMP-22 | Tabs and segmented control | List or map; sections of a case | 2 to 5 options. | ARIA tabs pattern with arrow keys. | `TabRow` |
| CMP-23 | Fidero Verified badge | Valid, expiring in 14 days, expired, suspended | Always with check date; expiry on detail page; links to the report. Never shown on a listing that is not Live. | Text label, not an image. | `FideroVerifiedBadge(state, checkedOn, validUntil)` |
| CMP-24 | One-time code input | Empty, typing, error, expired, resend timer | One field, not 6 boxes; numeric keyboard; paste allowed. | `autocomplete="one-time-code"`; timer not announced every second. | `OutlinedTextField` with `KeyboardType.NumberPassword` |
| CMP-25 | Statement row | Payment out, payment in, Fidero's charge, pending, in-person exception, receipt missing | Date, payee line (CMP-30), reference, signed amount, receipt link. Newest first. Running balance line after each month. Used for family-member statements, held balances, project funds and events. | `<table>` on laptop, stacked list on phone; amount has `aria-label` with the full currency name; sign read as "paid" or "received". | `LazyColumn` of `ListItem` with trailing `FideroMoney` |
| CMP-26 | Institution card | Verified (with date), Checking (with expected date), Not verified (with reason), Re-verifying, Suspended | Name, type, town, what was checked, account ending, contact role. Verified status is word plus tick icon, never a colour alone. A card that is not Verified has no "pay" action. | Status is the first text in the card; `aria-describedby` links the reason. | `Card` with `FideroStatusChip` |
| CMP-27 | Visit card | Planned, Checked in, Checked out awaiting confirmation, Confirmed, Disputed, Missed, Late | Carer first name, planned window, check-in and check-out times with "at address" or distance, plan items done of total, photo thumbnails (CMP-09), confirmation line ("Confirmed by Comfort, 10:20"). | List item with a summary sentence for screen readers ("Visit Tuesday, confirmed, 09:02 to 10:15"). | `Card` with `Row` of times and `FlowRow` of thumbnails |
| CMP-28 | Confirmation code entry | Empty, typing, match, no match, expired, answered | Four large digit cells on the family's page (SCR-PTL-45) and a large read-out on the carer's phone (SCR-MOB-16). 20 px text, 56 px targets. Two buttons: confirm, deny. | Single input with `inputmode="numeric"`, `autocomplete="off"`; result in `role="status"`. | `OutlinedTextField` on the carer side only; the family side is web |
| CMP-29 | Country selector | Default from phone number country, chosen, single country (read only), adding a second country | List of open countries with flag-free text labels ("Ghana · GHS"), a short line on what changes (currency, calendar, partners). Shown at onboarding and in Account. Never a free-text field. | Native `<select>` or radio group; the consequence line is `aria-describedby`. | `ExposedDropdownMenuBox` in the app's account screen |
| CMP-30 | Payee line | Planned, paid, in person (exception), blocked | "Paid to [name], account ending [nnnn]" per section 5.6. Sits directly above any approve button and on every statement row. Blocked variant: "Cannot be paid: account not in the institution's name." | Plain text; the account digits are read as digits. | `Text` composed by `FideroPayee(name, last4, state)` |
| CMP-31 | Partner notice | Insurer, bank, agency | Fixed-text panel from section 5.6a with the partner's name first and larger than Fidero's. No Fidero brand colour on the partner's product name. | `<aside aria-label="About this partner">`. | `Surface` with partner `Text` at `--text-xl` |
| CMP-32 | Dashboard section | Property, Family, Projects and errands; collapsed, expanded, empty (hidden), with items needing action | Heading with count and "See" link; items needing the client first, each with "!" and a word; status sentence per item (CMP-06 pattern); at most 3 items shown, then "See all". | `<section>` with `<h2>`; counts in text. | `LazyColumn` section with sticky header |

---

## 7. Accessibility and performance

### 7.1 WCAG 2.2 AA checklist mapped to components

NFR-A11Y-01 (01 v0.3) requires WCAG 2.2 AA on the portal and back office from R1 and on the Android field app from R2, using Android's accessibility guidance. The family confirmation page (SCR-PTL-45) is held to the same bar with larger text and targets, because its users are often elderly. Each item is tested in document 05.

| SC | Requirement | How Fidero meets it | Components and screens |
|---|---|---|---|
| 1.1.1 Non-text content | Text alternatives | Evidence alt text built from metadata; decorative icons hidden | CMP-09, CMP-07, CMP-12 |
| 1.3.1 Info and relationships | Structure in code | Real headings, lists, tables, fieldsets | CMP-03, CMP-05, CMP-06, CMP-11 |
| 1.3.5 Identify input purpose | `autocomplete` | Name, email, tel, one-time-code | CMP-02, CMP-24, SCR-PTL-02 |
| 1.4.1 Use of colour | Not colour alone | Shape plus word plus colour for verdicts, states, map layers | CMP-07, CMP-08, CMP-12, CMP-23 |
| 1.4.3 Contrast (minimum) | 4.5:1 text | All text tokens 5.3:1 or more (section 6.2) | All |
| 1.4.4 Resize text | 200% | `rem` sizes, no fixed heights on text | All |
| 1.4.10 Reflow | 320 px, no 2-D scroll | Phone-first layouts; tables become cards | CMP-11, back office |
| 1.4.11 Non-text contrast | 3:1 UI | Input borders 4.7:1; focus ring 5.8:1; amber badge border | CMP-02, CMP-07, CMP-01 |
| 1.4.12 Text spacing | Overrides do not break | No clipped text containers | All |
| 1.4.13 Content on hover or focus | Dismissible, persistent | Tooltips replaced by visible hints | CMP-02 |
| 2.1.1 Keyboard | All functions | Map has buttons; uploads, dialogs, tabs keyboard operable | CMP-12, CMP-15, CMP-22 |
| 2.2.1 Timing adjustable | Warn and extend | Staff idle timeout warns at 25 minutes with "Stay signed in"; code resend timers are not deadlines | SCR-BO-01, CMP-24 |
| 2.4.3 Focus order | Logical | Order follows reading order; dialogs trap and return focus | CMP-15 |
| 2.4.7 Focus visible | Visible | 3 px ring, 2 px offset, both themes | All |
| 2.4.11 Focus not obscured (minimum) | Not hidden by sticky UI | `scroll-padding` equal to sticky bar heights | Bottom tab bar, CMP-13 |
| 2.5.7 Dragging movements | Single pointer alternative | Map zoom and pan buttons; no drag-to-reorder | CMP-12 |
| 2.5.8 Target size (minimum) | 24 px | 44 px web, 48 dp Android | CMP-01, CMP-03 |
| 3.1.1 Language of page | `lang` | `lang="en-GH"`; per-language when localised | All |
| 3.2.6 Consistent help | Same place | "Get help" in footer and account menu on every page | All |
| 3.3.1 Error identification | Text errors | Inline messages plus summary | CMP-02 |
| 3.3.3 Error suggestion | How to fix | Every error says what to do | Section 5.2 |
| 3.3.4 Error prevention (legal, financial) | Review and confirm | Order review step; confirmation pattern | SCR-PTL-09, section 5.3 |
| 3.3.7 Redundant entry | No retyping | Plot details carried from listing to order; seller saved for "extra plot" | SCR-PTL-07, SCR-PTL-28 |
| 3.3.8 Accessible authentication (minimum) | No cognitive test | Paste allowed; password managers; one-time code by email or SMS; no CAPTCHA puzzles | SCR-PTL-02, SCR-PTL-03, SCR-BO-01 |
| 4.1.2 Name, role, value | Correct semantics | Native elements first; ARIA only where needed | All |
| 4.1.3 Status messages | Announced | Status sentence, toasts, offline banner use `role="status"` | CMP-06, CMP-13, CMP-14 |

Android: content descriptions, `semantics` merging for list items, TalkBack order checked, font scale up to 200% without truncation, 48 dp targets, no information in haptics alone.

Testing: automated checks in the build pipeline, manual keyboard and screen reader passes (NVDA with Chrome, VoiceOver with Safari on iPhone, TalkBack on a 2 GB Android phone) before each release.

### 7.2 Performance budgets

NFR-PERF-01 (useful content in 3 s at the 75th percentile on 1.6 Mbps and 300 ms latency) and NFR-PERF-02 (under 500 KB initial transfer) set the ceiling. The design budget sits below it to leave room for growth.

| Item (compressed, per route, first load) | Budget | Hard limit |
|---|---|---|
| HTML | 30 KB | |
| CSS | 25 KB | |
| JavaScript | 150 KB | 200 KB |
| Fonts | 0 KB (system fonts) | |
| Icons | 8 KB (inline sprite) | |
| Above-the-fold images | 80 KB | 120 KB |
| **Total initial transfer** | **about 300 KB** | **500 KB (NFR-PERF-02)** |
| Largest contentful paint, 3G profile | 2.5 s | 3 s (NFR-PERF-01) |
| Layout shift | 0.05 | 0.1 |
| Listing pages | Server rendered, under 3 s on 3G (FR-LST-010) | |
| Android app | Start under 3 s, install under 30 MB (NFR-PERF-05) | |

Design choices that keep to budget:

- The live map loads only when the user taps the static map image.
- The card payment form is the provider's; load it only on the payment step.
- No carousels, no autoplay video, no decorative images.
- The case tracker works with JavaScript turned off for reading (server rendered).

### 7.3 Image and video handling

| Asset | Size served | Format | Notes |
|---|---|---|---|
| Thumbnail | 320 px long edge, about 20 to 30 KB | WebP, JPEG fallback | Lists, timelines (FR-EVD-004) |
| Preview | 1,024 px, about 120 to 150 KB | WebP, JPEG fallback | Opened on tap |
| Original | As captured | Original | Only on explicit "Download original", with size shown first |
| Video preview | 480p, capped length `[TO VERIFY]` | H.264 MP4 | Poster image first; never autoplay |
| App capture | Compressed on device (FR-MOB-008) | JPEG, MP4 | Original kept on device until server confirms |

All images have width and height set to stop layout shift, `loading="lazy"` below the fold, and are served through signed links that expire within 15 minutes (FR-EVD-003). The UI refreshes an expired link without a page reload.

---

## 8. Localisation readiness

NFR-LOC-01 requires every user-facing string in translation files. English (Ghana) is the only language in R1.

| Topic | Rule |
|---|---|
| Strings | Every string, including status templates, errors, emails and SMS, lives in translation files with stable keys (`case.status.searches_lodged`). No text in images. |
| Message format | ICU MessageFormat for plurals and variables. Never build sentences by joining fragments, because word order differs between languages. |
| Expansion | Layouts allow 40% longer text. Buttons wrap rather than truncate. |
| Fonts | System fonts cover Akan (ɛ, ɔ), Ewe and Ga letters and Hausa hooked letters. Test each before adding a language. |
| Direction | CSS logical properties (`margin-inline-start`) so a right-to-left language is possible later, though none is planned. |
| Candidate languages | Twi, Ga, Ewe, Hausa for Ghana; Nigeria pilot languages per FR-CTY-001. Demand `[TO VERIFY]` from R0 and R1 data. Legal texts stay in English until translated texts are approved by the lawyer. |
| Dates | `12 March 2027` (day, month name, year). Short form `12 Mar 2027`. Never `03/12/27`, which reads differently in the US. |
| Times | 24-hour clock with zone: `14:05 GMT`. Ghana uses GMT all year with no daylight saving. For users abroad, add their local time: `14:05 GMT (15:05 in London)`. Deadlines are always stated in Ghana time first (C3). |
| Working days | Deadlines in working days (FR-DSP-003) exclude weekends and the public holidays in the country's holiday calendar, which the administrator maintains (01 C3, FR-CTY-001; issue I-10 closed). |
| Currency | ISO code, then amount: `GHS 5,400.00`, `USD 450.00`. Comma for thousands, point for decimals. Screen readers get the full currency name. Each country's currency comes from its configuration; naira (`NGN`) is assumed first when country 2 goes live on the platform, from about month 12 `[TO VERIFY]`. |
| Numbers and sizes | Plot sizes in feet as sold locally ("100 x 70 ft") with square metres in brackets. Distances in metres. |
| Phone numbers | Stored in E.164. Shown with country code: `+233 24 123 4567`. Default country from locale, editable. |
| Names | One full-name field plus an optional "what should we call you" field. No assumption of first and last name order. |
| Addresses | Ghana Post GPS (`AA-NNN-NNNN`) plus free-text locality. No postcode field for Ghana. |
| Country configuration | Templates, scope statement, currency, holiday calendar, partners, licence bodies, institution types, errand catalogue and legal texts come from country configuration (FR-CTY-001, R1); the UI never hard-codes "Lands Commission", "Ghana Card" or "NIA" outside Ghana configuration. Status templates take the institution's name as a variable. A second country's manual phase starts from about month 6; its screens are the same screens with its configuration. |
| Institution names | Shown as registered, in the country's official language, with no translation. Abbreviations (KATH, NIA) are shown only after the full name on the same screen. |

---

## 9. Prototype and usability testing

### 9.1 What the prototype covers

File: `docs/specs/03-prototype/index.html`. One self-contained HTML file. No build step, no network calls, no external images. Open it in any current browser, on a phone or a laptop. A banner on every screen says it is a prototype with sample data and sample prices.

| Flow | Screens in the prototype | Spec screens |
|---|---|---|
| H. Home dashboard (F-35) | One screen with the country (Ghana), sections for Property, Family, and Projects and errands, sample items with status sentences, the held balance at the bank, and links into the other flows. First in the switcher and the screen the prototype opens on | SCR-PTL-36 |
| A. Order a report (J-01) | What to check → the plot → documents → check and agree → pay → payment confirmed → case tracker → released report with verdict and hash check | SCR-PTL-06 to 12, SCR-PTL-14 |
| B. Escrow (J-02) | Escrow tracker with conditions closing, fresh search, the client's own approval with a code, and Fidero approvals 1 of 2; bank instructions panel | SCR-PTL-17, SCR-PTL-18 |
| C. Back office release | Two-person release approval with gates (including "client approved"), second-factor field, and a switch to see the screen as approver 1 | SCR-BO-12 |
| D. Listings (J-04) | Search with list and map views → listing detail with Fidero Verified badge, check date, expiry and report link; one expired example | SCR-PTL-26, SCR-PTL-27 |
| E. Build dashboard (J-03) | Budget against actual, milestone list, photo timeline placeholders, re-pricing note | SCR-PTL-22, SCR-PTL-23 (summary) |
| F. Android field app | Phone frame with evidence checklist, offline banner and upload queue; a switch to go online and watch the queue send | SCR-MOB-04, SCR-MOB-07, SCR-MOB-08 |
| G. Family: pay a hospital bill (J-09) | Kwabena's view: verified institution card → invoice sent by the hospital, with the three checks and a mismatch state to try → approve with a code, payee named → paid to the institution → receipt and family-member statement | SCR-PTL-39, SCR-PTL-40, SCR-PTL-42 |

How to use it:

- The top bar has a **flow switcher** (H first, then A to G) and a **theme switch** (system, light, dark).
- Within flow A, buttons move forward and back as in the real product. The step indicator is clickable for completed steps.
- The hash check in flow A really computes SHA-256 in the browser for any file you choose, and compares it with the sample hash. "Download report (sample file)" saves a small text file that matches; "Use the sample report" shows the match state in one click. Any other file shows the no-match state.
- In flow B, after the last condition closes, the client approves the release with any 6 digits. Only then does the back office (flow C) show the gate "Client approved" as passed.
- The release approval in flow C is blocked until you tick the statement and type any 6 digits. The "View as Kofi Boateng" switch shows the "different person" rule.
- In flow F, "Go online" sends queued items one by one; "Go offline" stops the queue.
- In flow G, "Simulate a mismatched invoice" shows the blocked state where the patient on the invoice is not the family member. Nothing can be approved until a corrected invoice is chosen.
- The dashboard in flow H combines Ama's property items and Kwabena's family items so that every section has something in it. In the real product each client sees only their own things. The signed-in name at the top changes with the flow.

What it does not cover: sign-up, the country selector and identity check, the back-office queue, report builder and institution verification, care visits, property management, errands, insurer pages, disputes and admin screens. These are in the wireframes.

### 9.2 Usability test plan

**Goal.** Show that NFR-USE-01 is met: a first-time client orders a report on a phone in under 10 minutes without help. Also check that clients understand status, verdicts and where purchase money goes.

| Item | Plan |
|---|---|
| Participants | 5 diaspora adults who have bought or plan to buy land in Ghana, recruited through diaspora associations and R0 clients. Mix of UK, US, Canada and Germany or the Netherlands; at least 2 aged over 50; at least 1 using a low-end Android phone. Incentive `[TO VERIFY]`. |
| Method | Remote, moderated, 45 minutes, on the participant's own phone, sharing the screen. Think-aloud. Moderator does not help during timed tasks. |
| Build | R1 staging portal with a test payment provider, or this prototype for an early round. |
| Throttling | One session run with the phone on a slow connection to check the 3G experience. |
| Consent | Recorded consent for screen and audio recording under Act 843 (FR-DPR-002 practice). Recordings deleted after analysis `[TO VERIFY]` retention. |

Tasks:

| Task | Scenario | Success |
|---|---|---|
| T1 Order a report (timed) | "Your cousin found a plot in Kasoa. Order a check on it and pay with the test card." | Order paid with correct plot details, unaided, in under 10 minutes |
| T2 Read status | "Your case has moved on. What is happening and when will you hear next?" | States the step and the next date correctly |
| T3 Understand the verdict | "Your report is ready. Should you pay the seller now? Why?" | For amber: says not yet, names at least one condition |
| T4 Check the report file | "Check that the PDF you downloaded is the real one." | Finds and completes the hash check |
| T5 Where does the money go | "You are ready to pay for the plot. Who do you pay?" | Names the partner bank, not Fidero (critical, RUL-01) |
| T6 Listing trust (R2 round) | "Is this listing checked, and when?" | Reads badge, check date and opens the report |
| T7 Pay a hospital bill | "Your mother's hospital has sent a bill. Pay it, and tell me who receives the money." | Approves the invoice unaided; names the hospital, not a relative or Fidero (critical, RUL-22) |
| T8 Read the dashboard | "Open your home page. What needs you today?" | Names the two items marked as needing action, in any order |

Participants for T7 and T8 include at least 2 who send money home for fees or bills today (persona P-15).

Measures:

- Completion rate and time for T1. **NFR-USE-01 pass (01 v0.3): at least 4 of 5 participants complete T1 unaided, with a median time under 10 minutes.** (Issue I-13 closed.)
- Errors and recoveries per task.
- T5 and T7 must be 5 of 5. Any failure is a release blocker, because paying the wrong party is the highest-harm error.
- Single Ease Question (1 to 7) after each task; target median 6 or above (assumption).
- Comprehension: participants explain the status sentence and verdict in their own words.
- Findings are logged with severity and the screen ID, fixed, and retested in the next round.

---

## 10. Traceability

Screen to requirement to journey. Rules (`RUL-`) follow the FR IDs where a screen enforces them. "Wireframe" names the section 4 drawing, if any. Document 05 should test each FR on the screens listed here.

| Screen | FR IDs; rules | Journey | Wireframe |
|---|---|---|---|
| SCR-PTL-01 | FR-ORD-002, FR-ORD-005 | J-01 | - |
| SCR-PTL-02 | FR-ACC-001, FR-DPR-001 | J-01 | W-01 |
| SCR-PTL-03 | FR-ACC-002, FR-ACC-009 | J-01 | - |
| SCR-PTL-04 | FR-ACC-004 | J-01, J-02 | W-02 |
| SCR-PTL-05 | Retired; see SCR-PTL-36 | - | - |
| SCR-PTL-06 | FR-ORD-001, FR-ORD-002 | J-01, J-08 | W-03 |
| SCR-PTL-07 | FR-ORD-001, FR-GEO-008 | J-01, J-08 | W-04 |
| SCR-PTL-08 | FR-ORD-001, FR-EVD-001, FR-EVD-005 | J-01, J-08 | - |
| SCR-PTL-09 | FR-ORD-003, FR-ORD-005, FR-ORD-006; RUL-04 | J-01, J-08 | W-05 |
| SCR-PTL-10 | FR-PAY-001, FR-PAY-002, FR-PAY-005; RUL-01 | J-01, J-08 | W-06 |
| SCR-PTL-11 | FR-PAY-003, FR-ORD-004 | J-01, J-08 | - |
| SCR-PTL-12 | FR-CASE-007, FR-CASE-008, FR-NTF-001, FR-ACC-008 | J-01, J-08 | W-07 |
| SCR-PTL-13 | FR-CASE-008, FR-EVD-001 | J-01, J-08 | - |
| SCR-PTL-14 | FR-RPT-005, FR-RPT-007, FR-RPT-008, FR-RPT-010 | J-01, J-08 | W-08 |
| SCR-PTL-15 | FR-RPT-008 | J-01 | - |
| SCR-PTL-16 | FR-ESC-001, FR-ESC-002, FR-RPT-009 | J-02, J-08 | - |
| SCR-PTL-17 | FR-ESC-004 to FR-ESC-009; RUL-06, RUL-07, RUL-11 | J-02, J-04, J-08 | W-09 |
| SCR-PTL-18 | FR-ESC-003; RUL-01 | J-02, J-04 | W-10 |
| SCR-PTL-19 | FR-CASE-015 | J-01 | - |
| SCR-PTL-20 | FR-ACC-008, FR-ACC-010, FR-NTF-001 | J-01 | - |
| SCR-PTL-21 | FR-PTR-002, FR-RPT-011; RUL-16 | J-06 | W-24 |
| SCR-PTL-22 | FR-BLD-009 | J-03 | W-19 |
| SCR-PTL-23 | FR-BLD-005, FR-BLD-006, FR-BLD-007; RUL-09, RUL-11, RUL-18 | J-03 | W-20 |
| SCR-PTL-24 | FR-BLD-008; RUL-19 | J-03 | - |
| SCR-PTL-25 | FR-BLD-001, FR-BLD-002, FR-BLD-003, FR-RAT-003 | J-03 | - |
| SCR-PTL-26 | FR-LST-004, FR-LST-010 | J-04 | W-21 |
| SCR-PTL-27 | FR-LST-003, FR-LST-005, FR-RAT-003; RUL-12, RUL-13, RUL-14 | J-04 | W-22 |
| SCR-PTL-28 | FR-LST-005, FR-CASE-014 | J-04 | - |
| SCR-PTL-29 | FR-DSP-001 to FR-DSP-004; RUL-15 | J-07 | W-23 |
| SCR-PTL-30 | FR-PRJ-001 to FR-PRJ-005; RUL-21 | J-05 | - |
| SCR-PTL-31 | FR-LST-001, FR-ACC-011, FR-PAY-007 | J-04 | - |
| SCR-PTL-32 | FR-LST-006, FR-LST-007 | J-04 | - |
| SCR-PTL-33 | FR-RAT-002 | J-01, J-03 | - |
| SCR-PTL-34 | FR-DPR-003 | None (data rights) | - |
| SCR-PTL-35 | FR-REC-004 | None (records, R3) | - |
| SCR-PTL-36 | FR-ACC-012, FR-CASE-007, FR-ESC-014, FR-CTY-001; RUL-22, RUL-24 | J-01, J-02, J-03, J-05, J-09, J-10, J-11, J-12 | W-25 |
| SCR-PTL-37 | FR-CTY-001, FR-ACC-001 | J-01, J-09 | - |
| SCR-PTL-38 | FR-ACC-012, FR-CARE-001 | J-09, J-10 | - |
| SCR-PTL-39 | FR-FEE-001; RUL-22 | J-09 | W-26 |
| SCR-PTL-40 | FR-FEE-002, FR-FEE-003, FR-ESC-014, FR-ESC-015; RUL-11, RUL-22 | J-09 | W-27 |
| SCR-PTL-41 | FR-FEE-004, FR-FEE-005; RUL-11 | J-09 | - |
| SCR-PTL-42 | FR-FEE-004, FR-FEE-006, FR-FEE-007, FR-ESC-014; RUL-22 | J-09 | W-28 |
| SCR-PTL-43 | FR-CARE-001, FR-CARE-002; RUL-23 | J-10 | W-29 |
| SCR-PTL-44 | FR-CARE-003, FR-CARE-005, FR-CARE-006; RUL-23 | J-10 | - |
| SCR-PTL-45 | FR-CARE-004; RUL-23 | J-10 | W-31 |
| SCR-PTL-46 | FR-PMG-001; RUL-24 | J-11 | - |
| SCR-PTL-47 | FR-PMG-002, FR-PMG-003, FR-PMG-005, FR-PMG-006; RUL-22, RUL-24 | J-11 | W-32 |
| SCR-PTL-48 | FR-PMG-004, FR-PMG-005, FR-RAT-003; RUL-11, RUL-22 | J-11 | W-33 |
| SCR-PTL-49 | FR-TSK-001, FR-CTY-001 | J-12 | - |
| SCR-PTL-50 | FR-TSK-002 to FR-TSK-005; RUL-22, RUL-23 | J-12 | W-34 |
| SCR-PTL-51 | FR-INS-001, FR-INS-002; RUL-25 | None (insurer line) | W-35 |
| SCR-PTL-52 | FR-INS-003, FR-INS-004; RUL-25 | None (insurer line) | - |
| SCR-PTL-53 | FR-EVT-001 to FR-EVT-003; RUL-22 | None (events, R3) | - |
| SCR-PTL-54 | FR-PMG-002, FR-PMG-004 | J-11 | - |
| SCR-BO-01 | FR-ACC-003, FR-ACC-009, NFR-SEC-02 | All | - |
| SCR-BO-02 | FR-CASE-005, FR-NTF-003 | J-01, J-08 | W-11 |
| SCR-BO-03 | FR-CASE-001 to FR-CASE-004, FR-CASE-007, FR-CASE-008, FR-CASE-011, FR-CASE-012, FR-CASE-013 | J-01, J-08 | W-12 |
| SCR-BO-04 | FR-CASE-004, FR-CASE-006, FR-CASE-010, FR-EVD-001 | J-01, J-08 | - |
| SCR-BO-05 | FR-CASE-009; RUL-17 | J-01, J-08 | W-13 |
| SCR-BO-06 | FR-CASE-010 | J-01 | - |
| SCR-BO-07 | FR-GEO-001 to FR-GEO-006 | J-01, J-04 | - |
| SCR-BO-08 | FR-RPT-001 to FR-RPT-005, FR-RPT-009; RUL-02, RUL-04, RUL-20 | J-01, J-08 | W-14 |
| SCR-BO-09 | FR-RPT-006, FR-RPT-007, FR-RPT-010; RUL-03 | J-01, J-08 | - |
| SCR-BO-10 | FR-ESC-001, FR-ESC-006 | J-02 | - |
| SCR-BO-11 | FR-ESC-001, FR-ESC-002, FR-ESC-004, FR-ESC-005, FR-ESC-006; RUL-06, RUL-07, RUL-15 | J-02, J-04, J-08 | - |
| SCR-BO-12 | FR-ESC-006 to FR-ESC-009, FR-ESC-013, FR-ESC-015; RUL-05, RUL-06, RUL-07, RUL-11, RUL-22 | J-02, J-03, J-05, J-09, J-11, J-12 | W-15 |
| SCR-BO-13 | FR-PAY-004, FR-PAY-006, FR-ESC-011 | J-01, J-02 | - |
| SCR-BO-14 | FR-BLD-005, FR-BLD-010, FR-MOB-011, FR-EVD-006 | J-03 | - |
| SCR-BO-15 | FR-BLD-003, FR-BLD-004, FR-RAT-001; RUL-10 | J-03 | - |
| SCR-BO-16 | FR-LST-002, FR-LST-006, FR-LST-008, FR-GEO-007, FR-RAT-004 | J-04 | - |
| SCR-BO-17 | FR-DSP-002 to FR-DSP-005 | J-07 | - |
| SCR-BO-18 | FR-ADM-001, FR-ADM-004, FR-ADM-005, FR-CTY-001 | All | W-16 |
| SCR-BO-19 | FR-ADM-002 | J-01 | - |
| SCR-BO-20 | FR-ACC-005, FR-ACC-006, FR-ACC-007 | All | - |
| SCR-BO-21 | FR-ADM-003, FR-PTR-004 | J-06 | - |
| SCR-BO-22 | FR-AUD-001 to FR-AUD-004 | All | - |
| SCR-BO-23 | FR-ANL-001 to FR-ANL-003 | None (operations) | - |
| SCR-BO-24 | FR-DPR-003 to FR-DPR-005 | None (data rights) | - |
| SCR-BO-25 | FR-NTF-002, FR-NTF-004, FR-NTF-005 | All | - |
| SCR-BO-26 | FR-REC-001 to FR-REC-003 | None (records, R3) | - |
| SCR-BO-27 | FR-FEE-001, FR-ESC-015, FR-ADM-003; RUL-22 | J-09 | - |
| SCR-BO-28 | FR-CARE-002, FR-CARE-005, FR-CARE-006, FR-TSK-003; RUL-23 | J-10, J-12 | - |
| SCR-BO-29 | FR-CTY-001, FR-CTY-002, FR-CTY-004, FR-ADM-003, FR-ADM-005 | All | W-36 |
| SCR-BO-30 | FR-FEE-002, FR-FEE-003, FR-FEE-006, FR-ESC-014, FR-ESC-015; RUL-22 | J-09 | - |
| SCR-BO-31 | FR-PMG-003, FR-PMG-004, FR-PMG-006; RUL-24 | J-11 | - |
| SCR-BO-32 | FR-TSK-003, FR-TSK-004, FR-TSK-005 | J-12 | - |
| SCR-MOB-01 | FR-MOB-001, FR-MOB-004 | J-03, J-10, J-12 | - |
| SCR-MOB-02 | FR-MOB-001 | J-03 | - |
| SCR-MOB-03 | FR-BLD-005 | J-03 | - |
| SCR-MOB-04 | FR-MOB-006 | J-03 | - |
| SCR-MOB-05 | FR-MOB-002, FR-MOB-003, FR-MOB-004; RUL-08 | J-03 | - |
| SCR-MOB-06 | FR-MOB-003, FR-MOB-004, FR-MOB-008 | J-03 | - |
| SCR-MOB-07 | FR-MOB-005, FR-MOB-006 | J-03 | W-17 |
| SCR-MOB-08 | FR-MOB-005, FR-MOB-008, FR-MOB-009 | J-03 | - |
| SCR-MOB-09 | FR-MOB-007; RUL-09, RUL-10 | J-03 | W-18 |
| SCR-MOB-10 | FR-MOB-007, FR-BLD-006 | J-03 | - |
| SCR-MOB-11 | FR-MOB-007; RUL-09 | J-03 | W-18 |
| SCR-MOB-12 | FR-MOB-010, FR-CASE-010 | J-01, J-02 | - |
| SCR-MOB-13 | FR-MOB-008, FR-MOB-009 | J-03 | - |
| SCR-MOB-14 | FR-MOB-012, FR-CARE-003; RUL-23 | J-10 | W-30 |
| SCR-MOB-15 | FR-CARE-003, FR-MOB-002, FR-MOB-010 | J-10 | W-30 |
| SCR-MOB-16 | FR-MOB-012, FR-CARE-004, FR-CARE-006 | J-10 | W-30 |
| SCR-MOB-17 | FR-TSK-003, FR-TSK-005, FR-MOB-010 | J-12 | - |
| SCR-MOB-18 | FR-PMG-001, FR-PMG-005, FR-MOB-012 | J-11 | - |

Modules with no screen of their own: FR-ANL (F-35 draws on it for the dashboard counts; the operating dashboard is SCR-BO-23), FR-AUD, FR-NTF and FR-DPR are cross-cutting and listed on the screens above.

---

## 11. Open questions and issues

### 11.1 Open design questions

| ID | Question | Owner | Needed by |
|---|---|---|---|
| DQ-01 | Is a brand typeface worth its page weight for headings only, or do system fonts stay for good? | Founder, designer | Before R1 visual design sign-off |
| DQ-02 | Which local languages first, if any, and for which screens (status messages only, or all)? Needs R0 and R1 data. | Founder | R2 planning |
| DQ-03 | Should clients receive WhatsApp messages with a deep link to the case, or a neutral "open the app" message only? Links in messages can be copied by fraudsters. | Product lead, security | R1 |
| DQ-04 | How do we show the seller's side of an escrow in R1, before sellers have full accounts? A one-time link to accept terms, or a lawyer-mediated paper step? | Product lead, lawyer | R1 |
| DQ-05 | Does the client representative in Ghana (FR-ACC-008) see the report verdict, or only progress? | Founder, lawyer | R1 |
| DQ-06 | How long is the mobile money wait before we show "not confirmed"? Depends on the provider. `[TO VERIFY]` | Product lead | R1 |
| DQ-07 | Should the portal offer a lightweight installable web app (offline reading of the tracker and report), or is the server-rendered page enough? | Product lead | R1 |
| DQ-08 | Do inspectors need a laptop view of their results, or is the app enough? | Operations | R2 |
| DQ-09 | What is the file size limit for client uploads on slow connections? Sample 10 MB `[TO VERIFY]`. | Engineering | R1 |
| DQ-10 | Should the public hash check (SCR-PTL-15) show the report's verdict, or only "match" and the release date? This design shows only match, reference, version and release date. | Founder, lawyer | R1 |
| DQ-11 | How is a listing's badge shown on social media shares, where it can be screenshotted after expiry? A live verification link with the expiry date is proposed. | Product lead | R2 |
| DQ-12 | Do we recruit colour-blind participants specifically for the verdict test? Recommended. | Designer | R1 usability round |
| DQ-13 | Does the dashboard show one country at a time with a switcher, or all countries in one list with a chip per item? This document assumes one list with chips until a client has more than about 10 items `[TO VERIFY]`. | Designer, founder | R1 |
| DQ-14 | Should institution-sent invoices (IF-10) appear on the dashboard before Fidero's checks run, marked "Not yet checked", or only after? This document shows them after the checks, to avoid a client approving an unchecked bill. | Product lead, operations | R1 |
| DQ-15 | What does the family member's confirmation page show when the client has asked for photos of the parent: the photos, or only that photos were taken? Privacy of the parent against reassurance of the family. | Lawyer, designer | R2 |
| DQ-16 | Is the insurer's own application form embedded, or does Fidero collect the fields and pass them on (FR-INS-002)? Each insurer may differ `[TO VERIFY]`. | Founder, insurer partner | R2 |
| DQ-17 | What is the late-rent grace period before an alert (FR-PMG-003), and the missed-visit window before an alert (FR-CARE-005)? This document uses 5 days and 60 minutes as samples `[TO VERIFY]`. | Operations | R2 |

### 11.2 Issues found in document 01

Document 01 has not been edited. Items marked **Closed** were fixed in 01 v0.2 or v0.3 and are kept here for one version so document 05 can retire its tests against them. The rest need a decision by the owner of 01.

| ID | Where in 01 | Issue | Status | Design assumption used here |
|---|---|---|---|---|
| I-01 | RUL-02, FR-RPT-003 | 01 says green is blocked if any section from 4 to 10 is red; the report template said 4 to 9. | **Closed.** The template now reads "sections 4 to 10". | Sections 4 to 10. |
| I-02 | RUL-11 against J-02 and the Escrow state model | No client approval step for a purchase release. | **Closed** in v0.2: the Escrow model has Ready to release → Client approved. J-02 step 6 still omits the client's step in its prose; a one-line edit would align it. | W-09, flow 3.2 and prototype flow B show the client approval. |
| I-03 | Milestone state model against FR-BLD-005, FR-BLD-006, FR-BLD-012 | Missing states for inspection scheduled, returned to submitted, defect hold-back, retention. | **Mostly closed** in v0.2. Retention held and released (FR-BLD-012) still has no state. | UI shows retention as a final milestone line ("Handover and retention"). |
| I-04 | Escrow state model | No Frozen from Release approved; no Frozen to Cancelled; no partial releases; no manual mode. | **Closed** in v0.2 (Frozen from Release approved with Q-12; Frozen → Cancelled; Partly released). Manual mode is covered by FR-ESC-004's manual entry. | As 01. |
| I-05 | FR-ACC-003 against RUL-11 | MFA is required for "any user who approves a release". Clients approve but do not release. It is unclear whether client approvals need MFA. | Open. | DA-01: one-time code for client approvals, now also for invoices (FR-FEE-003), repair quotes (FR-PMG-004) and the escrow release. |
| I-06 | NFR-A11Y-01 | The Android app had no accessibility requirement. | **Closed** in v0.3: the field app meets WCAG 2.2 AA from R2. | DA-06 retired. |
| I-07 | C2 user roles | Missing roles for quantity surveyor, client representative, authority representative, project runner, supplier; seller in R1. | **Closed** in v0.2 and v0.3. | As 01. |
| I-08 | FR-NTF-004 | No threshold for amounts in SMS and WhatsApp. | **Closed** in v0.2: FR-ADM-005 lists it as a configurable value. | As 01. |
| I-09 | FR-ORD-002 against C3 | Unclear which currency is charged. | **Closed** in v0.2: USD for cards, GHS for mobile money. | DA-02 kept as the display rule. |
| I-10 | FR-DSP-003, FR-ADM-005 | No holiday calendar per country. | **Closed** in v0.3: C3 and FR-CTY-001 name the holiday calendar. | As 01. |
| I-11 | FR-CASE-006, RUL-08, FR-EVD-006 | In R1, field staff upload verification evidence through a phone browser, which allows gallery uploads. RUL-08 covers only milestones. R1 site photos have weaker proof of time and place. | Open. Now also applies to R1 institution receipts uploaded by runners (FR-FEE-006). | UI marks R1 uploads as "Uploaded" with metadata shown. |
| I-12 | Listing state model, RUL-13 | No transition for a Reserved listing whose badge expires or that gets an alert. | **Closed** in v0.2: Live or Reserved → Suspended or Expired; Reserved → Live. | As 01. |
| I-13 | NFR-USE-01 | Pass mark unclear. | **Closed** in v0.2: at least 4 of 5, median under 10 minutes. | Section 9.2 updated. |
| I-14 | Milestone "approval window lapses" against RUL-18 | Automatic approval would skip the client seeing a re-pricing. | **Closed** in v0.2: silence is never approval (Q-13 remains open on what happens next). | W-20 updated. |
| I-15 | Dispute state model, FR-DSP-004 | No "Withdrawn" state. The model does not say what happens to frozen releases for each outcome. | Open. | UI offers withdraw and shows the money outcome in the decision. |
| I-16 | FR-RPT-008 | What the public hash check may reveal is not stated. | Open. | DA-04 and DQ-10. |
| I-17 | C8 state models against FEE, CARE, PMG, TSK, INS, EVT | 01 v0.3 adds six modules but no state models for an institution payment, a care visit, a repair, an errand, a policy or an event. Document 05 cannot test transitions that are not written down. | Open. | This document uses these states in words: institution payment (Received, Checked, Blocked, Approved by client, Release approved, Paid, Receipt returned); visit (Planned, Checked in, Checked out, Confirmed, Disputed, Missed); repair (Reported, Quotes in, Approved, Held, Inspected, Paid); errand (Documents, Paid in, Lodged, Rejected, Ready, Checked, Handed over, Complete). |
| I-18 | Priorities in FEE, CARE, PMG, TSK, INS | Must requirements sit under Should or Could parents: FR-INS-002 (Must) under F-33 (Could) and FR-INS-001 (Could); FR-TSK-002 to 004 (Must) under FR-TSK-001 (Should); FR-CARE-003 and 004 (Must) under FR-CARE-001 (Should); FR-PMG-002, 003 and 005 (Must) under FR-PMG-001 (Should). A Must that depends on a Should cannot ship on its own. | Open. | Screens follow the parent feature's release and priority. |
| I-19 | FR-CARE-004, C2 "Family member" | The family member confirms a visit "by a one-tap code, a call or the app", but 01 gives family members no sign-up or authentication path, and FR-ACC-012 only lets the client add them. | Open. | DA-07: one-time link, no account; call as fallback. |
| I-20 | FR-FEE-006 against RUL-22 and RUL-01 | A runner draws cash from the bank against a voucher and pays an institution in person. This is the only place cash moves, and no rule names it as an exception the way RUL-09 names mobilisation. | Open. | DA-10: shown plainly as an exception with voucher and receipt. |
| I-21 | FR-PMG-003 against RUL-24 | Rent goes to the owner's own account at the partner bank and Fidero "tracks rent received from the bank's statement". 01 does not say how Fidero may read the owner's account (consent, a mandate, or a view-only product `[TO VERIFY]`). | Open. | UI shows "Not yet confirmed by the bank" rather than "missing" when the statement is not available, and asks the owner for consent to view at SCR-PTL-46. |
| I-22 | FR-ACC-012 (Should) against FR-FEE-002 (Must) | Checking an invoice "against the named family member" is Must in R1, but adding a family member is Should. | Open. | SCR-PTL-38 is treated as Must for R1. |
| I-23 | FR-CARE-004, FR-CARE-005, RUL-23 | If the family never confirms and never denies a visit, the carer is unpaid for ever. 01 sets a 24-hour alert but no end state. | Open. Linked to Q-19. | After the alert, Fidero calls the family; a reviewer may record "confirmed by call" or "not confirmed", which decides payment. |
| I-24 | C2 "Tenant" and "Institution contact", FR-ACC-011 | Tenants and institution contacts have roles but no sign-up path in R1 (organisation accounts are R2). | Open. | Tenant view (SCR-PTL-54) is R2; institution contacts work by email and the back office in R1 (IF-10). |
