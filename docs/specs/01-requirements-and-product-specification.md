# 01 — Requirements and Product Specification

Business requirements (BRD), product requirements (PRD) and software requirements (SRS) for the Fidero platform.

| Item | Value |
|---|---|
| Document | 01 of 6 in `docs/specs/` |
| Version | 0.1, working draft |
| Date | 31 October 2026 |
| Owner | Founder, acting as product owner |
| Status | For review. Not yet baselined |
| Sources | `README.md`, `docs/proposal.md`, `docs/validation-plan.md`, `docs/partners.md`, `docs/operations/verification-report-template.md`, `docs/operations/milestone-schedule.md`, `docs/product/architecture.md`, the business plan Claude doc |

Every figure in this document is a working assumption, not verified data. Unknown numbers are marked `[TO VERIFY]`.

## How to read this document

- **Part A, the BRD**, says why Fidero builds software and what the business needs from it.
- **Part B, the PRD**, says what the product does, for whom, and in which release.
- **Part C, the SRS**, says exactly what the system shall do. Developers build from it and testers test against it.

### Identifiers

Every requirement has a stable ID. IDs are never reused. Documents 02 to 06 trace back to these IDs.

| Prefix | Meaning | Example |
|---|---|---|
| `BO-` | Business objective | BO-01 |
| `BR-` | Business requirement | BR-04 |
| `C-` | Constraint | C-02 |
| `AS-` | Assumption | AS-03 |
| `P-` | Persona | P-01 |
| `F-` | Product feature | F-07 |
| `J-` | User journey | J-02 |
| `RUL-` | Business rule the system must enforce | RUL-05 |
| `FR-<MODULE>-nnn` | Functional requirement | FR-ESC-004 |
| `NFR-<AREA>-nn` | Non-functional requirement | NFR-SEC-03 |
| `IF-` | External interface | IF-02 |

### Priority

MoSCoW within each release.

| Priority | Meaning |
|---|---|
| Must | The release cannot ship without it |
| Should | Important. Ship without it only with the product owner's written agreement |
| Could | Include if time allows |
| Won't (this release) | Agreed out of the release. May return later |

### Releases

Releases follow the roadmap phases in `docs/proposal.md`. Each release opens only after the previous phase passes its gate.

| Release | Roadmap phase | Months | What ships |
|---|---|---|---|
| R0 | Manual service | 0-3 | No platform. Spreadsheets, templates, a landing page and a payment link |
| R1 | Escrow and portal | 3-9 | Core platform: client portal, verification case workflow, report generation, evidence store, overlay checks, escrow tracking, building verification |
| R2 | Construction | 9-18 | Milestone photo app, inspections, construction management, off-plan escrow, project funds, verified listings for developers, partner API, bank integration, track records, disputes |
| R3 | Scale | 18-36 | Traditional authority records, family and stool listings, materials ordering, multi-country support for the Nigeria pilot |

---

# Part A — Business Requirements (BRD)

## A1. Purpose

Fidero lets people abroad buy land and property, build, and fund projects at home without being cheated or losing track of the money. Ghana is the launch market. Land verification is the launch product.

The 90-day manual service (R0) proves demand and the report process with no software. This BRD covers the software that lets the service grow past what a small team can run with spreadsheets, and that turns one-off reports into an escrow, construction and listings business.

## A2. Business problem

- Land in Ghana is mostly held under customary tenure. Records are scattered. Plots are sold twice, sellers lack authority, site plans do not match the ground, and plots sit inside acquisitions or road reserves.
- People abroad cannot visit, check records or watch a builder. Money sent home for land, building and projects is often diverted.
- No neutral party ties payment to proof.

The full problem statement is in `docs/proposal.md` section 2.

## A3. Business objectives

| ID | Objective | Measure | Target (assumption) |
|---|---|---|---|
| BO-01 | Sell verification at volume without losing quality | Paid reports per month; reports proven wrong within scope | 300 reports by month 9; zero proven wrong |
| BO-02 | Cut the cost and time of each report | Cost per report as share of price; median turnaround | Under 40% of price; median under 15 working days by month 9 |
| BO-03 | Convert verified buyers into escrow clients | Share of green or amber reports that lead to an escrow | 30% `[TO VERIFY]`; 50 escrows by month 9 |
| BO-04 | Launch construction management with zero diverted money | Active builds; payments released without an inspector's pass | 40 active builds by month 18; zero |
| BO-05 | Earn revenue from sellers as well as buyers | Verified listings live; seller fees as share of revenue | `[TO VERIFY]` |
| BO-06 | Sell checks to banks and developers | Signed partner contracts | One bank contract by month 18 |
| BO-07 | Keep client data and money safe | Data breaches; money held by Fidero | Zero reportable breaches; zero client money held by Fidero |
| BO-08 | Be ready to enter a second country | Nigeria pilot running on the same platform | By month 36 `[TO VERIFY]` |

## A4. Business requirements

| ID | Business requirement | Objectives | Release |
|---|---|---|---|
| BR-01 | Clients abroad and in Ghana must be able to order and pay for a verification report online, without visiting an office. | BO-01 | R1 |
| BR-02 | Every report must follow the standard template, pass two-person review and carry the locked scope statement. | BO-01, BO-07 | R1 |
| BR-03 | Fidero staff and contracted professionals must run each case through a tracked workflow with owners, due dates and required evidence. | BO-02 | R1 |
| BR-04 | Overlay checks against acquisitions, road reserves, wetlands and flood zones must run automatically from plot coordinates. | BO-02 | R1 |
| BR-05 | Fidero must show clients the state of each escrow and its release conditions, while the money stays with a licensed bank or escrow agent. | BO-03, BO-07 | R1 |
| BR-06 | Every piece of evidence must be tamper-evident and kept in a store where nothing is overwritten. | BO-01, BO-04 | R1 |
| BR-07 | Existing buildings must be verifiable with the land checks plus building-specific checks. | BO-01 | R1 |
| BR-08 | Construction payments must be released only against app-captured evidence and an independent inspector's pass. | BO-04 | R2 |
| BR-09 | Off-plan purchases and project funds must use the same verify, hold, release engine. | BO-04, BO-05 | R2 |
| BR-10 | Sellers must be able to list verified plots and properties, and buyers must be able to buy them through escrow. | BO-05 | R2 |
| BR-11 | Banks and developers must be able to check a plot's verification status through an API, with the client's consent. | BO-06 | R2 |
| BR-12 | Sellers, contractors, developers and professionals must build public track records, and disputes must follow fixed steps and timelines. | BO-04, BO-05 | R2 |
| BR-13 | Allocation records from traditional authorities must be digitised and used to speed up searches. | BO-02 | R3 |
| BR-14 | The platform must support a second country with its own report template, rules, currency and partners. | BO-08 | R3 |
| BR-15 | The platform must meet the Data Protection Act 2012 (Act 843) and keep a full audit trail of every action. | BO-07 | R1 |
| BR-16 | Management must see the operating metrics from the validation plan without building spreadsheets by hand. | BO-01, BO-02 | R1 |

## A5. Stakeholders

| Stakeholder | Interest | Involvement |
|---|---|---|
| Founder and product owner | Product direction, priorities, gates | Approves this document and every release |
| Diaspora buyers | Safe purchase and build from abroad | Primary users; usability tests |
| Local buyers | Affordable checks before paying | Users |
| Fidero operations staff | Running cases on time | Daily users of the back office |
| Fidero reviewers | Report quality | Approve reports and releases |
| Contracted lawyers | Clear scope, fair fees, low admin | Sign the legal section |
| Licensed surveyors | Clear scope, safe visits | Sign the surveyor's section |
| Field runners | Simple task lists on a phone | Lodge searches, attend visits |
| Escrow partner bank or licensed escrow agent | Compliance, fee share, clean process | Holds money; integration partner |
| Contractors | Prompt payment for work done | Submit milestone evidence |
| Independent inspectors | Clear checklists, safety | Pass or fail milestones |
| Developers | Diaspora sales channel | List estates and units; off-plan escrow |
| Traditional authorities: stools, skins, families | Clean records, revenue share | Consent; records programme; later listings |
| Banks and mortgage lenders | Faster collateral checks | Partner API customers |
| Professional indemnity insurer | Controlled scope and process | Approves scope wording and review rules |
| Data Protection Commission | Compliance with Act 843 | Registration and breach notices |
| Investors | Growth against the plan | Read the metrics |

## A6. Scope

**In scope.**

- Client portal (web, phone first) for ordering, paying, tracking and reading reports, escrows, builds and projects.
- Back office for case management, reviews, escrow conditions, inspections, listings, disputes and configuration.
- Milestone photo app (Android first) for contractors, inspectors and field staff.
- Evidence store, audit log, notifications, payments for Fidero's own fees.
- Integrations with the escrow bank, a payment provider, an identity check provider, map and satellite data, and messaging channels.
- Verified listings marketplace and partner API.
- Records module and multi-country support (R3).

**Out of scope.**

- Holding, pooling or moving client purchase money. A licensed bank or escrow agent does this. See C-01.
- Giving investment advice or guaranteeing returns.
- Replacing the Lands Commission register or issuing title.
- Mortgage lending.
- Vehicles, equipment and buying a business (phase 4 candidates, not specified here).
- An iPhone app for contractors before R2 data shows the need `[TO VERIFY]`.

## A7. Constraints

| ID | Constraint |
|---|---|
| C-01 | Fidero never holds client money. A licensed bank or escrow agent holds it under Bank of Ghana guidance. Fidero only records conditions and sends release instructions. |
| C-02 | The Data Protection Act 2012 (Act 843) applies to all personal data, including video of sellers, family heads and witnesses. |
| C-03 | The Land Act 2020 (Act 1036) sets the land framework and allows electronic conveyancing. |
| C-04 | Listing or brokering property may need a licence under the Real Estate Agency Act 2020 (Act 1047) `[TO VERIFY]`. Listings do not go live until this is resolved. |
| C-05 | Only licensed lawyers and surveyors may sign their report sections. |
| C-06 | The scope and limitation statement is fixed text. It changes only with the lawyer's and insurer's approval. |
| C-07 | Budget: $400,000 pre-seed for 18 months, shared with operations and marketing. Phase 2 team is one product and engineering lead plus one or two developers `[TO VERIFY]`. |
| C-08 | Many users in Ghana are on slow mobile connections and low-end Android phones. |
| C-09 | Data hosting must be in Ghana or in a jurisdiction the Data Protection Commission accepts `[TO VERIFY]`. |
| C-10 | The word "guard" must not appear in any product, feature or brand name. Land guards are the threat Fidero protects against. |

## A8. Assumptions and dependencies

| ID | Assumption or dependency | If wrong |
|---|---|---|
| AS-01 | The R0 manual service passes its day-90 gate before R1 build starts in earnest. | Delay R1; rework pitch and channels first. |
| AS-02 | At least one bank or licensed escrow agent signs an escrow agreement by month 6. | Escrow features ship but stay off; tracker runs on manual entry. |
| AS-03 | The partner bank can provide a status API or a daily statement file `[TO VERIFY]`. | Manual entry with the bank's confirmation attached. |
| AS-04 | A payment provider supports international cards and Ghana mobile money `[TO VERIFY]`. | Bank transfer with manual reconciliation. |
| AS-05 | An identity check provider supports the Ghana Card and foreign passports `[TO VERIFY]`. | Manual document check by staff. |
| AS-06 | Map layers for acquisitions, road reserves, wetlands and flood zones can be obtained in digital form `[TO VERIFY]`. | Staff digitise from paper maps; overlay checks are partly manual. |
| AS-07 | Lands Commission searches stay manual, done by a runner, unless online search becomes available `[TO VERIFY]`. | No change; the workflow already assumes manual searches. |
| AS-08 | Most contractors use Android phones `[TO VERIFY]`. | Build an iPhone app earlier. |
| AS-09 | Professional indemnity cover extends to building inspections and project funds `[TO VERIFY]`. | Those lines do not open. |

## A9. Success metrics

The platform must report these metrics from its own data (see FR-ANL).

| Metric | Source |
|---|---|
| Paid reports per month, by tier and country | Orders |
| Turnaround, median and 90th percentile, payment to delivery | Case events |
| Time per workflow step against target | Case events |
| Cost per report | Case costs entered by operations |
| Verdict mix: red, amber, green | Reports |
| Conversion: report to escrow, report to build | Cases, escrows, projects |
| Lead source and conversion | Leads |
| Escrows opened, value held at the bank, value released | Escrow tracker |
| Milestones submitted, passed first time, failed, flagged for fraud | Milestone app |
| Listings live, views, enquiries, sales through escrow | Listings |
| Disputes opened, resolved within the timeline | Disputes |
| Client satisfaction (would recommend, yes or no) | Survey after delivery |
| Safety incidents | Incident log |

---

# Part B — Product Requirements (PRD)

## B1. Product vision

Anyone abroad can buy, build or fund something at home and know, with evidence, that the money went where it should.

**Positioning.** For people abroad who send money home for land, property and projects, Fidero is the independent party that checks the asset, has the money held by a licensed bank, and releases it only against evidence. Unlike relatives, agents or a lawyer alone, Fidero gives one standard report, a neutral escrow and proof at every step.

## B2. Product principles

1. **Evidence before money.** No release without recorded evidence that closes every condition.
2. **Fidero never holds the money.** The product shows and instructs. The bank holds and pays.
3. **Plain status, always.** Every screen says what happened, when, and what comes next, in one sentence.
4. **Built for a slow phone.** Small pages, resized images, offline capture.
5. **One engine.** A new product line is a new template, condition set and milestone schedule, not new software.
6. **People stay in the loop.** Software automates checks and paperwork. Licensed people sign, and two people approve every release.
7. **Safety first.** No product feature may push field staff into a disputed site without a risk screen.

## B3. Personas

| ID | Persona | Context | Goals | Frustrations |
|---|---|---|---|---|
| P-01 | Ama, diaspora buyer | Nurse in London, 38. Buying a plot near Kasoa to build a family house. Uses her phone for everything. | Know the plot is real and the seller can sell. Pay safely. Watch the build. | A cousin took her last building money. Cannot leave work to fly home. |
| P-02 | Kwame, local buyer | Accountant in Accra, 31. Buying his first plot. Pays in cedis by mobile money. | An affordable check before he pays the family. | Does not know which lawyer or surveyor to trust. |
| P-03 | Esi, Fidero case manager | Runs 30 cases at once from the Accra office. | See what is late and who owns it. Chase without spreadsheets. | Status is spread across WhatsApp, email and paper. |
| P-04 | Fidero reviewer | Senior staff member who signs off reports and releases. | Catch errors before a report or a payment goes out. | Missing evidence found at the last minute. |
| P-05 | Lawyer | Partner lawyer handling searches, consent meetings and the legal section. | Clear scope, documents in one place, quick sign-off. | Chasing clients for documents. |
| P-06 | Surveyor | Licensed surveyor doing site visits. | A clear job sheet, safe visits, simple upload of coordinates and photos. | Unsafe sites; unpaid travel. |
| P-07 | Runner | Field runner lodging searches and attending visits. | A task list on a basic phone. | Lost receipts; unclear priorities. |
| P-08 | Contractor | Small building contractor, Android phone, patchy signal. | Get paid fast for work done. | Slow payments; disputes about what was done. |
| P-09 | Inspector | Independent building inspector. | A checklist per milestone, a fair fee, not chosen by the contractor. | Pressure from contractors. |
| P-10 | Developer | Estate developer selling plots and off-plan homes. | Reach diaspora buyers who trust the listing. | Buyers who do not trust developers. |
| P-11 | Family head or stool secretary | Represents the land-owning family or stool. | Sell legitimately, keep records straight, earn from the records programme. | Rogue family members selling family land. |
| P-12 | Bank credit officer | Checks land offered as loan collateral. | A fast status check on a plot. | Slow manual collateral checks. |
| P-13 | Project fund owner | Teacher in Toronto funding her brother's poultry farm. | Pay suppliers directly and see each stage done. | Money sent for projects disappears. |
| P-14 | Fidero administrator | Configures templates, prices, users and partners. | Change settings without a developer. | Hard-coded rules. |

## B4. Release plan and gates

| Release | Gate to start | Gate to finish |
|---|---|---|
| R0 | Founder decision | Day-90 review in `docs/validation-plan.md` section 6 passes |
| R1 | R0 passes; escrow partner in talks | 300 reports and 50 escrows `[TO VERIFY]`; security review passed; insurer approves the platform report process |
| R2 | R1 targets met; bank agreement signed; Act 1047 position known for listings | 40 active builds and one bank contract |
| R3 | R2 targets met; Ghana construction gate passed for the Nigeria pilot | `[TO VERIFY]` |

## B5. Feature catalogue

| ID | Feature | Personas | Release | Priority | SRS modules |
|---|---|---|---|---|---|
| F-01 | Accounts, sign-in and identity check | All | R1 | Must | ACC |
| F-02 | Order and pay for a verification report | P-01, P-02 | R1 | Must | ORD, PAY |
| F-03 | Verification case workflow with tasks, owners and due dates | P-03 to P-07 | R1 | Must | CASE |
| F-04 | Report builder, two-person review and hashed PDF | P-03, P-04, P-05, P-06 | R1 | Must | RPT |
| F-05 | Automatic overlay checks from plot coordinates | P-03 | R1 | Must | GEO |
| F-06 | Client case tracker with plain-language status | P-01, P-02 | R1 | Must | CASE, NTF |
| F-07 | Evidence store with hashing and versioning | All internal | R1 | Must | EVD |
| F-08 | Escrow tracker with release conditions and two-person release instruction | P-01, P-03, P-04 | R1 | Must | ESC |
| F-09 | Building verification (existing houses, apartments, commercial property) | P-01, P-02 | R1 | Should | CASE, RPT |
| F-10 | Notifications by email, SMS and WhatsApp | All | R1 | Must | NTF |
| F-11 | Back office administration: users, roles, templates, prices, partners | P-14 | R1 | Must | ADM |
| F-12 | Audit log | P-04, P-14 | R1 | Must | AUD |
| F-13 | Operating dashboard and exports | P-03, P-14 | R1 | Should | ANL |
| F-14 | Data subject requests and retention | P-14 | R1 | Must | DPR |
| F-15 | Milestone photo app with offline, tamper-evident capture | P-08, P-09 | R2 | Must | MOB |
| F-16 | Construction projects: bill of quantities, milestones, inspections, build dashboard | P-01, P-08, P-09 | R2 | Must | BLD |
| F-17 | Off-plan purchase escrow with stage releases | P-01, P-10 | R2 | Should | BLD, ESC |
| F-18 | Project funds: budgets, suppliers, direct payment against invoices | P-13 | R2 | Should | PRJ |
| F-19 | Verified listings marketplace (developers first) | P-01, P-10 | R2 | Should | LST |
| F-20 | Track records and ratings | P-01, P-10 | R2 | Should | RAT |
| F-21 | Dispute process | All | R2 | Must (with F-16) | DSP |
| F-22 | Partner API for banks and developers | P-12 | R2 | Should | PTR |
| F-23 | Bank integration: statement file or API | P-03 | R2 | Should | ESC |
| F-24 | Satellite monitoring of listed and active plots | P-03 | R2 | Could | GEO |
| F-25 | Traditional authority records module | P-11 | R3 | Should | REC |
| F-26 | Family and stool listings | P-11 | R3 | Could | LST |
| F-27 | Materials ordering for builds | P-01, P-08 | R3 | Could | BLD |
| F-28 | Multi-country support | P-14 | R3 | Must (for Nigeria) | CTY |

## B6. Key user journeys

### J-01 Order a land verification report (R1)

1. Ama finds Fidero through a diaspora association webinar and opens the portal on her phone.
2. She signs up with email and phone, and passes an identity check.
3. She enters the plot details, uploads the site plan and the seller's contact, and picks a tier.
4. She pays by card. She gets a receipt and a case reference.
5. Operations accepts the case. Tasks are created for the runner, surveyor and lawyer with due dates.
6. Ama sees each step as it happens, such as "Searches lodged at the Lands Commission on 12 March. Results expected by 2 April."
7. The report is built, reviewed by two people and released. Ama downloads the PDF and can check its hash.
8. If the verdict is green or amber, she is offered escrow.

### J-02 Buy through escrow (R1)

1. Ama chooses escrow on a green or amber report.
2. The release conditions are copied from the report's section 11. Ama, the seller and Fidero accept the escrow terms. The bank opens the escrow.
3. Ama pays the purchase price to the bank, not to Fidero. The tracker shows the deposit when the bank confirms it.
4. A fresh search and site check run before release.
5. Each condition is closed with evidence, such as the signed indenture and recorded family consent.
6. Two Fidero staff approve. Fidero sends the release instruction. The bank pays the seller and confirms. Ama sees each step.

### J-03 Build with milestone payments (R2)

1. Ama starts a construction project on her verified plot.
2. A quantity surveyor uploads the bill of quantities. The milestone split is set. Ama picks a vetted contractor and approves the budget.
3. Construction money is held at the bank against the milestone schedule.
4. The contractor captures evidence in the app on site and submits each milestone.
5. Fidero checks the evidence. Fraud flags go to a reviewer.
6. An independent inspector visits and records pass, pass with defects, or fail.
7. On a pass, two Fidero staff approve and the bank pays the contractor. Ama sees photos, the inspector's result and budget against actual.

### J-04 Buy a verified listing (R2)

1. A developer lists an estate. Fidero verifies each plot. Only plots that pass are published with a "Fidero Verified" badge and the date of the checks.
2. Ama browses listings, opens the full report, and reserves a plot.
3. A fresh search and site check run. The purchase follows J-02. The developer pays a success fee when the escrow releases.

### J-05 Fund a project at home (R2)

1. A project fund owner sets up a project with a budget, the person running it and the suppliers.
2. Fidero checks the person and the suppliers.
3. Money is held at the bank. Suppliers are paid directly against invoices once each stage is confirmed by receipts, photos and visits.

### J-06 Bank collateral check (R2)

1. A bank's system calls the partner API with a plot reference.
2. If the client has consented, the API returns the verdict and date of the latest report. Otherwise it returns only whether a report exists.

### J-07 Raise and resolve a dispute (R2)

1. A buyer, seller, contractor or Fidero opens a dispute against a pending release.
2. The release is frozen. Each party submits a statement and evidence by a set deadline.
3. A Fidero reviewer decides, or refers to mediation. The outcome and reasons are recorded.

### J-08 Verify an existing building (R1)

As J-01, with extra checks: building permit, structural inspection, occupants and tenancies, unpaid property rates and utility bills. Release in escrow also needs keys and vacant possession.

## B7. Business rules

The system must enforce these rules. Each is tested in document 05.

| ID | Rule |
|---|---|
| RUL-01 | Fidero never receives or holds purchase, construction or project money. The system has no function to receive such money into a Fidero account. |
| RUL-02 | A report's overall verdict cannot be green if any section from 4 to 10 is red. |
| RUL-03 | A report is released only after review by two different people: the lawyer who signed the legal section and one Fidero reviewer. |
| RUL-04 | The scope and limitation statement is inserted from a locked text block. Users cannot edit it in a report. |
| RUL-05 | Every release instruction needs approval by two different Fidero staff with release rights. Their names are recorded. |
| RUL-06 | A release instruction cannot be sent while any release condition is open. |
| RUL-07 | Before any purchase release, a fresh search and site check must be recorded within `[TO VERIFY]` days of the release. |
| RUL-08 | Milestone evidence must be captured in the Fidero app. Gallery and file uploads are not accepted as evidence. |
| RUL-09 | A milestone payment cannot be released without an inspector's pass or pass with defects. A pass with defects holds back the defect value. |
| RUL-10 | The inspector on a project cannot be chosen, paid or employed by the contractor on that project. |
| RUL-11 | A client cannot release a payment alone. A client approves; Fidero staff approve; the bank pays. |
| RUL-12 | A listing is published only if its verification report is green and less than `[TO VERIFY]` days old. A failed check means no listing. |
| RUL-13 | A listing badge expires after `[TO VERIFY]` days or when monitoring raises an unresolved alert. |
| RUL-14 | Buyers always see the full report behind a listing. |
| RUL-15 | An open dispute freezes every release linked to it. |
| RUL-16 | A full report is shared with a partner only with the client's recorded consent. |
| RUL-17 | Field visits to a plot flagged as disputed need a risk screen and at least two people. |
| RUL-18 | Each milestone's cost is re-priced in cedis against the dollar guide before release, and any change is shown to the client before approval. |
| RUL-19 | Every scope variation on a build is agreed in writing in the app before work starts. |
| RUL-20 | Only licensed professionals with a verified licence on file can sign their report section. |
| RUL-21 | Project fund money goes only to named, checked suppliers against invoices, never as cash to a person running the project. |

## B8. Out of scope for this specification

- Native iPhone app for contractors (decide after R2 data).
- In-app chat between buyers and sellers in listings. Enquiries go through Fidero.
- Automated legal advice or valuation.
- Lending or credit scoring.
- Phase 4 lines: vehicles, equipment, buying a business.

## B9. Open product questions

| ID | Question | Owner | Needed by |
|---|---|---|---|
| Q-01 | Which bank or escrow agent, and can it offer an API or a daily statement? | Founder | R1 start |
| Q-02 | Which payment provider for cards and mobile money? | Founder | R1 start |
| Q-03 | Which identity check provider? | Product lead | R1 start |
| Q-04 | How many days may pass between the fresh search and a release (RUL-07)? | Lawyer | R1 |
| Q-05 | How long does a listing badge stay valid (RUL-13)? | Lawyer, insurer | R2 |
| Q-06 | Does Act 1047 require a licence for listings? | Lawyer | Before R2 listings |
| Q-07 | Where must data be hosted under Act 843? | Lawyer | R1 start |
| Q-08 | Retention period for cases and consent videos | Lawyer, insurer | R1 |
| Q-09 | Share of contractors on iPhone | Operations | R2 start |
| Q-10 | Listing fee and success fee levels | Founder | R2 |

---

# Part C — Software Requirements (SRS)

## C1. System overview

Fidero is one platform with four front ends over one core API:

1. **Client portal** (web, phone first) for buyers, sellers, developers and project fund owners.
2. **Back office** (web) for operations, reviewers, professionals and administrators.
3. **Milestone app** (Android) for contractors, inspectors, runners and surveyors in the field.
4. **Partner API** for banks and developers.

It integrates with an escrow bank, a payment provider, an identity check provider, map and satellite data sources, and messaging channels. Architecture is in document 02.

## C2. User roles

| Role | Can do | Cannot do |
|---|---|---|
| Client | Order, pay Fidero fees, track own cases, escrows, projects; approve conditions and milestones; open disputes | See other clients' data; release money |
| Seller | Accept escrow terms; supply documents; list verified assets (R2); respond to disputes | See the buyer's personal data beyond what the deal needs |
| Developer | As seller, for many units; manage estates and off-plan stages | Choose the inspector |
| Case manager (Fidero operations) | Run cases, assign tasks, chase, enter bank confirmations | Release alone; edit locked text |
| Reviewer (Fidero) | Review and approve reports, releases, fraud flags, disputes | Approve their own work as second approver |
| Lawyer | Work assigned cases; sign the legal section | See unassigned cases |
| Surveyor | Work assigned site visits; sign the surveyor's section | See unassigned cases |
| Runner | Work assigned tasks; capture evidence | Sign sections |
| Contractor | Submit milestone evidence for assigned projects | Choose the inspector; release |
| Inspector | Complete checklists for assigned inspections | Work on a project where they have a conflict |
| Partner (API) | Query plot status for consented reports | See full reports without consent |
| Administrator | Configure users, roles, templates, prices, partners, countries | Release money; edit the audit log |

## C3. Operating environment

- Web front ends work on the last two major versions of Chrome, Safari, Firefox and Edge, and on Android Chrome on devices with 2 GB of RAM.
- The milestone app runs on Android 8.0 or later `[TO VERIFY]` on devices with 2 GB of RAM.
- Users may be on 3G connections with frequent drops.
- Primary language is English. Times are shown in the user's time zone and in Ghana time (GMT).
- Currencies: Ghana cedi (GHS) and US dollar (USD) in R1; GBP, EUR and CAD shown as guides; Nigerian naira (NGN) in R3.

## C4. Functional requirements

Each requirement uses "shall". Priority and release follow the conventions above. "Source" points to the business requirement or rule it serves.

### C4.1 Accounts and identity (ACC)

| ID | Requirement | Priority | Release | Source |
|---|---|---|---|---|
| FR-ACC-001 | The system shall let a person sign up with an email address and a mobile number, both verified by one-time code. | Must | R1 | BR-01 |
| FR-ACC-002 | The system shall let users sign in with email or phone and a password, or with a one-time code. | Must | R1 | BR-01 |
| FR-ACC-003 | The system shall require multi-factor authentication for all Fidero staff, professionals, administrators and any user who approves a release. | Must | R1 | BR-15 |
| FR-ACC-004 | The system shall run an identity check on a client before a report is released or an escrow is opened, using the identity check provider or a manual document check. | Must | R1 | BR-05 |
| FR-ACC-005 | The system shall store each professional's licence number, licence body and expiry date, and block signing when the licence is expired or unverified. | Must | R1 | RUL-20 |
| FR-ACC-006 | The system shall let an administrator invite staff, professionals, contractors and inspectors and assign roles. | Must | R1 | BR-03 |
| FR-ACC-007 | The system shall enforce role-based access so each user sees only the cases, projects and listings assigned to them or owned by them. | Must | R1 | BR-15 |
| FR-ACC-008 | The system shall let a client name a representative in Ghana with limited, read-only access to a case or project. | Should | R1 | BR-01 |
| FR-ACC-009 | The system shall lock an account after 5 failed sign-in attempts for 15 minutes and notify the user. | Must | R1 | BR-15 |
| FR-ACC-010 | The system shall let users manage notification preferences and their preferred channel. | Should | R1 | BR-01 |
| FR-ACC-011 | The system shall let a developer or seller create an organisation account with several users. | Should | R2 | BR-10 |

### C4.2 Orders and leads (ORD)

| ID | Requirement | Priority | Release | Source |
|---|---|---|---|---|
| FR-ORD-001 | The system shall let a client order a verification for a plot or building by entering locality, plot number, site plan reference, Ghana Post GPS address if known, seller name and contact, and uploading the site plan and any documents. | Must | R1 | BR-01 |
| FR-ORD-002 | The system shall offer the tiers configured by an administrator (diaspora standard, local standard, rush, extra plot same seller) and show the price in the client's currency before payment. | Must | R1 | BR-01 |
| FR-ORD-003 | The system shall show the scope statement and terms before payment and record the client's acceptance with time and version. | Must | R1 | RUL-04 |
| FR-ORD-004 | The system shall create a case only after payment is confirmed, or after a case manager records an offline payment with proof. | Must | R1 | BR-01 |
| FR-ORD-005 | The system shall record the lead source of every order (association, webinar, referral, remittance partner, other). | Should | R1 | BR-16 |
| FR-ORD-006 | The system shall apply referral codes and record the referral reward owed. | Could | R1 | BR-16 |
| FR-ORD-007 | The system shall let a client order an extra inspection on a project at the configured price. | Should | R2 | BR-08 |

### C4.3 Payments for Fidero fees (PAY)

| ID | Requirement | Priority | Release | Source |
|---|---|---|---|---|
| FR-PAY-001 | The system shall take payment of Fidero's own fees by international card and Ghana mobile money through the payment provider. | Must | R1 | BR-01 |
| FR-PAY-002 | The system shall never store full card numbers. | Must | R1 | BR-15 |
| FR-PAY-003 | The system shall issue a receipt for every fee payment, by email and in the portal. | Must | R1 | BR-01 |
| FR-PAY-004 | The system shall record refunds with a reason and an approver. | Should | R1 | BR-01 |
| FR-PAY-005 | The system shall keep fee payments completely separate from escrowed money, and shall offer no function to accept purchase, construction or project money. | Must | R1 | RUL-01 |
| FR-PAY-006 | The system shall reconcile provider settlements against orders daily and list mismatches for a case manager. | Should | R1 | BR-16 |
| FR-PAY-007 | The system shall invoice sellers for listing fees and success fees. | Should | R2 | BR-10 |

### C4.4 Verification case workflow (CASE)

| ID | Requirement | Priority | Release | Source |
|---|---|---|---|---|
| FR-CASE-001 | The system shall create each case from a case template for the product line (land, building) and country. | Must | R1 | BR-03 |
| FR-CASE-002 | The system shall create the template's steps as tasks, each with an owner role, required evidence and a target duration. Land steps: intake, searches lodged, site visit, overlay checks, consent meeting, search results, legal review, second review, release. | Must | R1 | BR-03 |
| FR-CASE-003 | The system shall let a case manager assign each task to a named person and set or change its due date with a reason. | Must | R1 | BR-03 |
| FR-CASE-004 | The system shall not let a task be marked done until its required evidence is attached. | Must | R1 | BR-06 |
| FR-CASE-005 | The system shall show case managers a queue of cases and tasks sorted by due date, with overdue items highlighted. | Must | R1 | BR-03 |
| FR-CASE-006 | The system shall let assigned professionals and runners see and complete their tasks on a phone browser. | Must | R1 | BR-03 |
| FR-CASE-007 | The system shall record a client-facing status message at each step, written in plain language from a template, with the date and the next expected date. | Must | R1 | BR-01 |
| FR-CASE-008 | The system shall let a case manager request documents from the client and show the request in the client's tracker. | Must | R1 | BR-03 |
| FR-CASE-009 | The system shall require a risk screen before any site visit and block assignment of fewer than two people to a plot flagged as disputed. | Must | R1 | RUL-17 |
| FR-CASE-010 | The system shall let field staff log a safety incident from the case, held in a restricted incident log. | Must | R1 | RUL-17 |
| FR-CASE-011 | The system shall record the cost of each case by item (lawyer, surveyor, runner, fees, travel). | Should | R1 | BR-16 |
| FR-CASE-012 | The system shall support case pause, cancellation and refund with reasons. | Should | R1 | BR-03 |
| FR-CASE-013 | The system shall support a building case template with extra steps: building permit check, structural inspection, occupancy and tenancy check, property rates and utility bills check. | Should | R1 | BR-07 |
| FR-CASE-014 | The system shall support a fresh-search case type that repeats the Lands Commission search and a site check on a previously verified asset. | Must | R1 | RUL-07 |
| FR-CASE-015 | The system shall let a client message Fidero inside a case and keep the thread with the case. | Should | R1 | BR-01 |

### C4.5 Report builder (RPT)

| ID | Requirement | Priority | Release | Source |
|---|---|---|---|---|
| FR-RPT-001 | The system shall build each report from the versioned template in `docs/operations/verification-report-template.md`, with sections 1 to 14 in order. | Must | R1 | BR-02 |
| FR-RPT-002 | The system shall let the owner of each section enter findings, attach evidence and choose a section verdict of red, amber or green. | Must | R1 | BR-02 |
| FR-RPT-003 | The system shall compute the allowed overall verdict and block green if any section from 4 to 10 is red. | Must | R1 | RUL-02 |
| FR-RPT-004 | The system shall insert the scope and limitation statement from a locked, versioned text block. | Must | R1 | RUL-04 |
| FR-RPT-005 | The system shall let the lawyer sign the legal section and the surveyor sign the surveyor's section, each with name, licence number and time. | Must | R1 | RUL-20 |
| FR-RPT-006 | The system shall require approval by the signing lawyer and by a second Fidero reviewer who is a different person before release. | Must | R1 | RUL-03 |
| FR-RPT-007 | The system shall generate a PDF of the released report, compute its SHA-256 hash and store both. | Must | R1 | BR-06 |
| FR-RPT-008 | The system shall let anyone with a report reference and PDF check that the PDF matches the stored hash. | Should | R1 | BR-06 |
| FR-RPT-009 | The system shall record release conditions in section 11 as structured items that can be copied into an escrow. | Must | R1 | BR-05 |
| FR-RPT-010 | The system shall never change a released report. A correction creates a new version with a reason, and the client is notified. | Must | R1 | BR-02 |
| FR-RPT-011 | The system shall produce an anonymised version of a report for case studies only when the client's written consent is on file. | Could | R1 | BR-15 |

### C4.6 Geospatial checks and monitoring (GEO)

| ID | Requirement | Priority | Release | Source |
|---|---|---|---|---|
| FR-GEO-001 | The system shall store plot boundaries as polygons from surveyor coordinates or a digitised site plan. | Must | R1 | BR-04 |
| FR-GEO-002 | The system shall check a plot polygon against overlay layers (government acquisitions, road reserves, wetlands, flood zones, known dispute areas, planning zones) when the polygon is saved, and record each result with the layer version. | Must | R1 | BR-04 |
| FR-GEO-003 | The system shall flag a plot as inside, near (within a configurable buffer) or clear of each layer, and propose the section 7 verdict. | Must | R1 | BR-04 |
| FR-GEO-004 | The system shall let an administrator upload and version overlay layers. | Must | R1 | BR-04 |
| FR-GEO-005 | The system shall check a new plot against all previously verified plots and flag overlaps. | Should | R1 | BR-04 |
| FR-GEO-006 | The system shall attach a satellite image of the plot with the boundary drawn to each report. | Should | R1 | BR-02 |
| FR-GEO-007 | The system shall compare new satellite imagery of listed and active plots on a schedule and alert when new structures or clearing appear. | Could | R2 | RUL-13 |
| FR-GEO-008 | The system shall convert between Ghana Post GPS addresses and coordinates where the service allows `[TO VERIFY]`. | Could | R1 | BR-04 |

### C4.7 Escrow tracking (ESC)

| ID | Requirement | Priority | Release | Source |
|---|---|---|---|---|
| FR-ESC-001 | The system shall create an escrow record with parties, asset, agreed price, currency, bank reference and the release conditions copied from the report. | Must | R1 | BR-05 |
| FR-ESC-002 | The system shall record each party's acceptance of the escrow terms with time and terms version. | Must | R1 | BR-05 |
| FR-ESC-003 | The system shall show the client the bank's payment instructions and never Fidero's own account details. | Must | R1 | RUL-01 |
| FR-ESC-004 | The system shall record deposit confirmation from the bank's API, statement file or a manual entry with the bank's confirmation attached. | Must | R1 | BR-05 |
| FR-ESC-005 | The system shall let a case manager close each condition by attaching the evidence that satisfies it. | Must | R1 | BR-05 |
| FR-ESC-006 | The system shall block a release instruction while any condition is open, a dispute is open, or the fresh search is missing or out of date. | Must | R1 | RUL-06, RUL-07, RUL-15 |
| FR-ESC-007 | The system shall require approval of a release instruction by two different staff with release rights, using multi-factor authentication. | Must | R1 | RUL-05 |
| FR-ESC-008 | The system shall generate the release instruction in the format agreed with the bank, signed by the approvers, and send it by the agreed channel. | Must | R1 | BR-05 |
| FR-ESC-009 | The system shall record the bank's release confirmation and show it to all parties. | Must | R1 | BR-05 |
| FR-ESC-010 | The system shall support partial releases against milestones or stages for construction, off-plan and project fund escrows. | Must | R2 | BR-08, BR-09 |
| FR-ESC-011 | The system shall import the bank's daily statement file and match lines to escrows, listing unmatched lines. | Should | R2 | BR-05 |
| FR-ESC-012 | The system shall integrate with the bank's API for deposit and release status where available. | Could | R2 | BR-05 |
| FR-ESC-013 | The system shall support cancellation and refund instructions with the same two-person approval. | Must | R1 | RUL-05 |

### C4.8 Evidence store (EVD)

| ID | Requirement | Priority | Release | Source |
|---|---|---|---|---|
| FR-EVD-001 | The system shall store every uploaded file with its SHA-256 hash, uploader, device if any, capture time, server time, position if any, and the case, project or listing it belongs to. | Must | R1 | BR-06 |
| FR-EVD-002 | The system shall never overwrite or silently delete evidence. Deletions follow retention rules and are logged. | Must | R1 | BR-06 |
| FR-EVD-003 | The system shall serve evidence only through signed links that expire within 15 minutes. | Must | R1 | BR-15 |
| FR-EVD-004 | The system shall create resized previews of images and compressed previews of video for slow connections. | Must | R1 | C-08 |
| FR-EVD-005 | The system shall scan uploads for malware and reject unsafe files. | Must | R1 | BR-15 |
| FR-EVD-006 | The system shall mark each item as app-captured (with a verified device signature) or uploaded. | Must | R2 | RUL-08 |

### C4.9 Milestone app (MOB)

| ID | Requirement | Priority | Release | Source |
|---|---|---|---|---|
| FR-MOB-001 | The app shall let contractors, inspectors, runners and surveyors sign in and see only their assigned projects, cases and tasks. | Must | R2 | BR-08 |
| FR-MOB-002 | The app shall capture photos and video with its own camera only, and block gallery and file uploads for evidence. | Must | R2 | RUL-08 |
| FR-MOB-003 | The app shall record GPS position and accuracy at capture and warn when the position is more than a configured distance from the plot boundary. | Must | R2 | BR-08 |
| FR-MOB-004 | The app shall hash each file at capture and sign the hash, position and device time with a key held in the device keystore. | Must | R2 | BR-06 |
| FR-MOB-005 | The app shall work offline: capture, fill checklists and queue submissions, and upload when a connection returns. The queue shall survive the app being closed or the phone restarting. | Must | R2 | C-08 |
| FR-MOB-006 | The app shall show the required evidence list for the chosen milestone and block submission until each item is attached. | Must | R2 | BR-08 |
| FR-MOB-007 | The app shall give inspectors the checklist for the milestone and let them record pass, pass with defects (each defect with photos and a value) or fail. | Must | R2 | RUL-09 |
| FR-MOB-008 | The app shall compress photos and cap video length and resolution, keeping originals on the device until the server confirms receipt. | Must | R2 | C-08 |
| FR-MOB-009 | The app shall encrypt stored evidence on the device and remove it after the server confirms receipt. | Must | R2 | BR-15 |
| FR-MOB-010 | The app shall let runners and surveyors capture evidence for verification case tasks the same way. | Should | R2 | BR-06 |
| FR-MOB-011 | The server shall verify each signature, record the server time and flag: position outside the plot buffer, a large gap between device and server time, capture before the previous milestone passed, a hash already seen on another project, and inconsistent image metadata. | Must | R2 | BR-08 |

### C4.10 Construction, off-plan and buildings (BLD)

| ID | Requirement | Priority | Release | Source |
|---|---|---|---|---|
| FR-BLD-001 | The system shall let a client create a construction project on a verified plot. | Must | R2 | BR-08 |
| FR-BLD-002 | The system shall let a quantity surveyor upload a bill of quantities and set the milestone split from the standard schedule (mobilisation, foundation, blocks, lintel, roof, finishing, handover and retention). | Must | R2 | BR-08 |
| FR-BLD-003 | The system shall keep a panel of vetted contractors and inspectors with their documents, status and track record. | Must | R2 | BR-08 |
| FR-BLD-004 | The system shall assign an inspector who has no recorded link to the contractor, and block a conflicted assignment. | Must | R2 | RUL-10 |
| FR-BLD-005 | The system shall route each milestone through: submitted, evidence checked, inspection scheduled, inspected, client approved, release approved, released. | Must | R2 | BR-08 |
| FR-BLD-006 | The system shall hold back the defect value on a pass with defects and release it when the defect is closed with evidence. | Must | R2 | RUL-09 |
| FR-BLD-007 | The system shall re-price each milestone in cedis against the dollar guide before release and show any change to the client for approval. | Must | R2 | RUL-18 |
| FR-BLD-008 | The system shall record scope variations agreed in writing by client and contractor before the work. | Must | R2 | RUL-19 |
| FR-BLD-009 | The system shall show the client a build dashboard: budget against actual, milestone status, photo timeline, inspector results and payments. | Must | R2 | BR-08 |
| FR-BLD-010 | The system shall remove a contractor from the panel and freeze their releases when they submit evidence for work not done, after a reviewer confirms. | Must | R2 | BR-12 |
| FR-BLD-011 | The system shall support off-plan purchases: verify the developer's title, permits and company; hold stage payments; release each stage against app evidence and an inspector. | Should | R2 | BR-09 |
| FR-BLD-012 | The system shall hold the retention for the defects period and release it when the inspector confirms all defects closed. | Must | R2 | BR-08 |
| FR-BLD-013 | The system shall let Fidero order bulk materials for a build, pay suppliers from the held funds through the bank, and show deliveries on the dashboard. | Could | R3 | BR-08 |

### C4.11 Project funds (PRJ)

| ID | Requirement | Priority | Release | Source |
|---|---|---|---|---|
| FR-PRJ-001 | The system shall let a client create a project with a budget, stages, the person running it and named suppliers. | Should | R2 | BR-09 |
| FR-PRJ-002 | The system shall run identity and background checks on the person running the project and on each supplier before money is accepted at the bank. | Should | R2 | BR-09 |
| FR-PRJ-003 | The system shall release money only to checked suppliers against an invoice, with the stage confirmed by receipts, photos and, where configured, a visit. | Should | R2 | RUL-21 |
| FR-PRJ-004 | The system shall apply enhanced anti-money-laundering checks to project funds above a configurable amount. | Should | R2 | BR-09 |
| FR-PRJ-005 | The system shall show in every project agreement that Fidero gives no investment advice and guarantees no returns. | Must | R2 | BR-09 |

### C4.12 Verified listings (LST)

| ID | Requirement | Priority | Release | Source |
|---|---|---|---|---|
| FR-LST-001 | The system shall let a seller or developer submit a plot, building, estate or off-plan unit for listing and pay the listing fee. | Should | R2 | BR-10 |
| FR-LST-002 | The system shall publish a listing only when its verification report is green and within the validity period. | Must | R2 | RUL-12 |
| FR-LST-003 | The system shall show on each listing the "Fidero Verified" badge, the date of the checks and a link to the full report. | Must | R2 | RUL-14 |
| FR-LST-004 | The system shall let buyers search and filter listings by region, locality, price, size, type and verification date, and view them on a map. | Should | R2 | BR-10 |
| FR-LST-005 | The system shall let a buyer enquire about or reserve a listing, which starts a fresh search and an escrow. | Should | R2 | BR-10 |
| FR-LST-006 | The system shall expire the badge after the validity period and suspend the listing on an unresolved monitoring alert. | Must | R2 | RUL-13 |
| FR-LST-007 | The system shall mark a listing as sold when its escrow releases and invoice the success fee. | Should | R2 | BR-10 |
| FR-LST-008 | The system shall let a reviewer remove a listing and its seller for misconduct, with a reason. | Must | R2 | BR-12 |
| FR-LST-009 | The system shall let families and stools list plots through the records module. | Could | R3 | BR-13 |
| FR-LST-010 | Listing pages shall be indexable by search engines and load in under 3 seconds on 3G. | Should | R2 | BR-10 |

### C4.13 Track records and ratings (RAT)

| ID | Requirement | Priority | Release | Source |
|---|---|---|---|---|
| FR-RAT-001 | The system shall compute a track record for each seller, developer, contractor, surveyor and inspector from completed deals, milestone outcomes, disputes and timeliness. | Should | R2 | BR-12 |
| FR-RAT-002 | The system shall let a client rate a completed case, deal or milestone from 1 to 5 with an optional comment. | Should | R2 | BR-12 |
| FR-RAT-003 | The system shall show track records on listings and when a client chooses a contractor. | Should | R2 | BR-12 |
| FR-RAT-004 | The system shall let a reviewer hide an abusive comment with a reason, without changing the rating. | Should | R2 | BR-12 |

### C4.14 Disputes (DSP)

| ID | Requirement | Priority | Release | Source |
|---|---|---|---|---|
| FR-DSP-001 | The system shall let a party to an escrow, milestone or listing open a dispute with a reason and evidence. | Must | R2 | BR-12 |
| FR-DSP-002 | The system shall freeze every release linked to an open dispute. | Must | R2 | RUL-15 |
| FR-DSP-003 | The system shall set deadlines for each step: response 5 working days, evidence 10 working days, decision 10 working days (assumptions). | Must | R2 | BR-12 |
| FR-DSP-004 | The system shall record the decision, reasons and decider, and notify all parties. | Must | R2 | BR-12 |
| FR-DSP-005 | The system shall let a reviewer refer a dispute to external mediation and record the outcome. | Should | R2 | BR-12 |

### C4.15 Partner API (PTR)

| ID | Requirement | Priority | Release | Source |
|---|---|---|---|---|
| FR-PTR-001 | The API shall let an authenticated partner submit a plot reference or coordinates and receive: no report, report in progress, or the verdict and date of the latest report. | Should | R2 | BR-11 |
| FR-PTR-002 | The API shall return the verdict and date only if the client has consented to sharing with that partner, and the full report only with specific consent. | Must | R2 | RUL-16 |
| FR-PTR-003 | The API shall let a partner order a new verification on behalf of a consenting client. | Could | R2 | BR-11 |
| FR-PTR-004 | The system shall meter API calls per partner for billing and apply rate limits. | Should | R2 | BR-11 |

### C4.16 Notifications and messaging (NTF)

| ID | Requirement | Priority | Release | Source |
|---|---|---|---|---|
| FR-NTF-001 | The system shall notify users of status changes, tasks, requests and approvals by email, SMS and WhatsApp, according to their preferences. | Must | R1 | BR-01 |
| FR-NTF-002 | The system shall send notifications from editable templates per language and channel. | Must | R1 | BR-01 |
| FR-NTF-003 | The system shall remind task owners 2 working days before a due date and alert the case manager when a task is overdue. | Must | R1 | BR-03 |
| FR-NTF-004 | The system shall never include report contents, money amounts above a threshold or personal data of third parties in SMS or WhatsApp messages. | Must | R1 | BR-15 |
| FR-NTF-005 | The system shall log every notification sent, its channel and delivery status. | Should | R1 | BR-15 |

### C4.17 Administration (ADM)

| ID | Requirement | Priority | Release | Source |
|---|---|---|---|---|
| FR-ADM-001 | The system shall let an administrator manage case templates, report templates, condition sets and milestone schedules as versioned configuration. | Must | R1 | BR-03 |
| FR-ADM-002 | The system shall let an administrator manage prices, tiers, currencies and exchange-rate guides. | Must | R1 | BR-01 |
| FR-ADM-003 | The system shall let an administrator manage partners: banks, professionals, contractors, inspectors, suppliers, API partners. | Must | R1 | BR-03 |
| FR-ADM-004 | The system shall keep the locked scope statement versioned and changeable only by two administrators with the lawyer's and insurer's approval recorded. | Must | R1 | RUL-04 |
| FR-ADM-005 | The system shall let an administrator set configurable values: fresh-search window, badge validity, plot buffer distances, dispute deadlines. | Must | R1 | RUL-07, RUL-13 |

### C4.18 Audit (AUD)

| ID | Requirement | Priority | Release | Source |
|---|---|---|---|---|
| FR-AUD-001 | The system shall write every create, change, approval, release, export and sign-in to an append-only audit log with who, when, what and from where. | Must | R1 | BR-15 |
| FR-AUD-002 | No application user, including administrators, shall be able to edit or delete audit entries. | Must | R1 | BR-15 |
| FR-AUD-003 | The system shall let reviewers and administrators search the audit log by case, user, date and action. | Should | R1 | BR-15 |
| FR-AUD-004 | The system shall chain audit entries by hash so any tampering is detectable. | Should | R1 | BR-15 |

### C4.19 Analytics and reporting (ANL)

| ID | Requirement | Priority | Release | Source |
|---|---|---|---|---|
| FR-ANL-001 | The system shall show an operating dashboard with the metrics in A9, filterable by date, country, product line and tier. | Should | R1 | BR-16 |
| FR-ANL-002 | The system shall export metric tables as CSV for reviewers and administrators, with the export logged. | Should | R1 | BR-16 |
| FR-ANL-003 | Dashboards shall show no personal data beyond what the viewer's role allows. | Must | R1 | BR-15 |

### C4.20 Data protection and retention (DPR)

| ID | Requirement | Priority | Release | Source |
|---|---|---|---|---|
| FR-DPR-001 | The system shall show a plain-language privacy notice at sign-up and record acceptance with its version. | Must | R1 | C-02 |
| FR-DPR-002 | The system shall record the consent of every person recorded on video, linked to the recording. | Must | R1 | C-02 |
| FR-DPR-003 | The system shall let an administrator respond to access and correction requests by exporting or correcting a person's data, with the request logged. | Must | R1 | C-02 |
| FR-DPR-004 | The system shall apply retention rules per data class and delete or anonymise data at the end of the period, unless a legal hold applies. | Must | R1 | C-02 |
| FR-DPR-005 | The system shall require two-person approval for any bulk export of personal data. | Must | R1 | C-02 |

### C4.21 Records programme (REC)

| ID | Requirement | Priority | Release | Source |
|---|---|---|---|---|
| FR-REC-001 | The system shall let a traditional authority's allocation records be captured as plots with boundaries, allottees, dates and supporting documents. | Should | R3 | BR-13 |
| FR-REC-002 | The system shall check new verification cases against digitised records and pre-fill the chain of ownership where a match is found. | Should | R3 | BR-13 |
| FR-REC-003 | The system shall compute the revenue share owed to each authority from cases that used their records. | Should | R3 | BR-13 |
| FR-REC-004 | The system shall let an authorised representative of the authority view and confirm their records. | Should | R3 | BR-13 |

### C4.22 Multi-country (CTY)

| ID | Requirement | Priority | Release | Source |
|---|---|---|---|---|
| FR-CTY-001 | The system shall hold country as configuration: templates, scope statement, overlay layers, currency, partners, professional licence bodies and legal texts. | Must | R3 | BR-14 |
| FR-CTY-002 | The system shall keep each country's data in the location its law requires. | Must | R3 | BR-14 |
| FR-CTY-003 | The system shall report all metrics by country. | Must | R3 | BR-14 |

## C5. Data requirements

### C5.1 Main entities

| Entity | Key attributes |
|---|---|
| Person | Name, email, phone, country, identity check status, roles |
| Organisation | Name, type (developer, bank, contractor, supplier, law firm, authority), registration number, users |
| Professional licence | Person, body, number, expiry, verified by, verified on |
| Asset | Type (plot, building, off-plan unit), locality, plot number, Ghana Post GPS, boundary polygon, country |
| Order | Client, asset, tier, price, currency, lead source, payment status |
| Case | Template and version, asset, client, status, steps, costs, risk flag |
| Task | Case, step, owner, due date, required evidence, status |
| Report | Case, version, sections, verdicts, conditions, signatures, PDF hash, released at |
| Overlay layer | Name, type, version, source, polygons |
| Overlay result | Asset, layer version, inside, near or clear, distance |
| Escrow | Parties, asset, price, currency, bank reference, terms version, status |
| Condition | Escrow, text, evidence, status, closed by |
| Release instruction | Escrow, amount, approvers, sent at, bank confirmation |
| Project | Type (construction, off-plan, funds), asset, budget, stages or milestones, contractor or person running it |
| Milestone | Project, share, amount, status, submissions, inspection |
| Submission | Milestone, items, device, signatures, flags |
| Inspection | Milestone, inspector, checklist results, outcome, defects |
| Evidence | File, hash, uploader, device, times, position, links |
| Listing | Asset, seller, price, report, badge expiry, status |
| Dispute | Subject, parties, statements, deadlines, decision |
| Rating | Subject, rater, score, comment |
| Audit event | Actor, action, object, time, origin, previous hash |
| Consent | Person, purpose, text version, time, linked recording |

### C5.2 Data classes and retention

| Class | Examples | Retention (assumption) |
|---|---|---|
| Case and report | Reports, evidence, signatures | `[TO VERIFY]` by lawyer and insurer; at least the limitation period |
| Consent recordings | Videos of sellers, family heads, witnesses | Same as case |
| Escrow and payment | Escrow records, instructions, receipts | As tax and banking law requires `[TO VERIFY]` |
| Account | Profile, preferences | Life of account plus `[TO VERIFY]` |
| Safety | Incident and threat logs | `[TO VERIFY]`; restricted access |
| Audit | Audit log | At least as long as the longest class it covers |
| Marketing | Leads | 24 months from last contact (assumption) |

## C6. External interfaces

| ID | Interface | Purpose | Release | Notes |
|---|---|---|---|---|
| IF-01 | Escrow bank or agent | Deposit confirmation, release instructions and confirmation | R1 manual; R2 file or API | Format agreed with the bank `[TO VERIFY]` |
| IF-02 | Payment provider | Card and mobile money for Fidero fees | R1 | Provider `[TO VERIFY]` |
| IF-03 | Identity check provider | Ghana Card and passport checks | R1 | Provider `[TO VERIFY]` |
| IF-04 | Map layers | Acquisitions, road reserves, wetlands, flood zones, zoning | R1 | Sources `[TO VERIFY]` |
| IF-05 | Satellite imagery | Images for reports; change detection | R1 images; R2 monitoring | Provider `[TO VERIFY]` |
| IF-06 | Ghana Post GPS | Address to coordinates | R1 | Availability `[TO VERIFY]` |
| IF-07 | Email, SMS, WhatsApp | Notifications | R1 | Providers `[TO VERIFY]` |
| IF-08 | Partner API consumers | Banks and developers | R2 | Defined in document 02 |
| IF-09 | Lands Commission | Searches | Manual in all releases unless online access is offered `[TO VERIFY]` | |

## C7. Non-functional requirements

| ID | Requirement | Release |
|---|---|---|
| NFR-PERF-01 | Portal pages shall show useful content within 3 seconds at the 75th percentile on a simulated 3G connection (1.6 Mbps, 300 ms latency). | R1 |
| NFR-PERF-02 | A portal page's initial transfer shall be under 500 KB, excluding images the user opens. | R1 |
| NFR-PERF-03 | API reads shall respond within 500 ms and writes within 1 second at the 95th percentile, at 10 times the expected R1 load. | R1 |
| NFR-PERF-04 | Overlay checks shall complete within 30 seconds of saving a plot polygon. | R1 |
| NFR-PERF-05 | The milestone app shall start in under 3 seconds and its install size shall be under 30 MB on a 2 GB RAM device. | R2 |
| NFR-AVL-01 | The portal and API shall be available 99.5% of each month, excluding announced maintenance. | R1 |
| NFR-AVL-02 | Recovery point objective: no more than 1 hour of data loss. Recovery time objective: 4 hours. | R1 |
| NFR-AVL-03 | Evidence shall be stored with at least two copies in separate locations. | R1 |
| NFR-SEC-01 | All traffic shall use TLS 1.2 or later. Data at rest shall be encrypted. | R1 |
| NFR-SEC-02 | Passwords shall be hashed with a modern adaptive algorithm. Staff sessions shall time out after 30 minutes idle. | R1 |
| NFR-SEC-03 | The system shall pass an independent penetration test with no open high or critical findings before each release goes live. | R1 |
| NFR-SEC-04 | Secrets shall live in a secrets manager, never in code or configuration files. | R1 |
| NFR-SEC-05 | The system shall follow the OWASP Application Security Verification Standard level 2 for the portal, back office and API. | R1 |
| NFR-PRIV-01 | Personal data shall be hosted where the Data Protection Commission accepts `[TO VERIFY]`, and every data location recorded. | R1 |
| NFR-PRIV-02 | Personal data shall be minimised: each field must have a stated purpose in the data catalogue. | R1 |
| NFR-USE-01 | A first-time client shall be able to order a report on a phone in under 10 minutes without help, in usability tests with 5 diaspora users. | R1 |
| NFR-USE-02 | Status messages shall be in plain English, readable at a reading age of 12. | R1 |
| NFR-ACC-01 | The portal and back office shall meet WCAG 2.2 level AA. | R1 |
| NFR-OBS-01 | Every request shall carry a trace ID. Errors, latency, upload queue length and job failures shall be monitored with alerts. | R1 |
| NFR-MNT-01 | Automated tests shall cover at least 80% of lines in the core API and every business rule in B7. | R1 |
| NFR-MNT-02 | A new product line or country shall be added through configuration, with code changes only for new integrations. | R2 |
| NFR-SCL-01 | The platform shall handle 2,000 open cases, 500 active projects and 20,000 listings without redesign. | R2 |
| NFR-LOC-01 | All user-facing text shall be held in translation files, ready for other languages. | R1 |
| NFR-AUD-01 | Audit entries shall be retained and readable for the full retention period of the data they describe. | R1 |

## C8. State models

### Case

| From | To | Trigger |
|---|---|---|
| Draft | Paid | Payment confirmed |
| Paid | In progress | Case manager accepts |
| In progress | On hold | Waiting on client or third party, with reason |
| On hold | In progress | Blocker cleared |
| In progress | In review | All tasks done, report drafted |
| In review | In progress | Reviewer returns with comments |
| In review | Released | Two-person approval (RUL-03) |
| Any before Released | Cancelled | Cancellation with reason and refund decision |

### Escrow

| From | To | Trigger |
|---|---|---|
| Proposed | Agreed | All parties accept terms |
| Agreed | Funded | Bank confirms deposit |
| Funded | Ready to release | All conditions closed and fresh search in date |
| Ready to release | Release approved | Two-person approval (RUL-05) |
| Release approved | Released | Bank confirms payment |
| Funded or Ready to release | Frozen | Dispute opened |
| Frozen | Funded | Dispute resolved |
| Agreed or Funded | Cancelled | Two-person approved cancellation; bank confirms refund |

### Milestone

| From | To | Trigger |
|---|---|---|
| Not started | Submitted | Contractor submits evidence |
| Submitted | Evidence checked | Fidero accepts evidence (flags cleared by a reviewer) |
| Submitted | Returned | Evidence incomplete or flagged and rejected |
| Evidence checked | Inspected | Inspector records outcome |
| Inspected (fail) | Returned | Contractor must fix and resubmit |
| Inspected (pass or pass with defects) | Client approved | Client approves, or approval window lapses `[TO VERIFY]` |
| Client approved | Release approved | Two-person approval |
| Release approved | Paid | Bank confirms |

### Listing

| From | To | Trigger |
|---|---|---|
| Draft | In verification | Listing fee paid |
| In verification | Rejected | Report not green |
| In verification | Live | Report green and in date |
| Live | Suspended | Monitoring alert, dispute or misconduct |
| Suspended | Live | Issue resolved |
| Live | Expired | Badge validity ends |
| Expired | In verification | Seller orders re-verification |
| Live | Reserved | Buyer reserves; fresh search starts |
| Reserved | Sold | Escrow released |
| Reserved | Live | Reservation lapses or fails |

### Dispute

| From | To | Trigger |
|---|---|---|
| Open | Awaiting response | Notified to other party |
| Awaiting response | Evidence | Response received or deadline passed |
| Evidence | Decision | Evidence deadline passed |
| Decision | Closed | Decision recorded and notified |
| Any | Referred | Referred to mediation |
| Referred | Closed | Mediation outcome recorded |

## C9. Acceptance

Each functional requirement and business rule has acceptance criteria and test cases in document 05, with a traceability matrix from BR to F, FR, user story and test. A release is accepted when all its Must requirements pass, no critical or high defects are open, and the product owner signs off.

## Glossary

| Term | Meaning |
|---|---|
| Stool, skin | The seat of a chief, standing for the traditional authority that holds customary land |
| Indenture | The deed transferring an interest in land |
| Site plan | The seller's drawing of the plot, usually from a surveyor |
| Pillars | Concrete markers at the corners of a plot |
| Ghana Post GPS | Ghana's digital address system |
| Overlay check | Checking a plot boundary against map layers such as acquisitions and road reserves |
| Fresh search | A repeat search and site check just before money is released |
| Bill of quantities | The quantity surveyor's list of materials, labour and costs for a build |
| Retention | Part of the build value held back until the defects period ends |
| Release instruction | Fidero's signed instruction to the bank to pay out escrowed money |
| Badge | The "Fidero Verified" mark on a listing, valid for a set period |
