# Proposed architecture

This is a proposal for the Fidero product. Nothing here is built. The manual service runs first with documents, spreadsheets and messaging. Software is added in the order the roadmap needs it: client portal and report workflow in months 3-9, escrow status in months 3-9, milestone photo app in months 9-18.

Principles:

- Build the smallest thing the next phase needs.
- Fidero never holds client money. The escrow partner does.
- Every piece of evidence is tamper-evident: signed, time-stamped, hashed.
- Personal data is minimised and kept in Ghana or in a jurisdiction with adequate protection `[TO VERIFY]`.

## 1. Components

| Component | Purpose | Phase |
|---|---|---|
| Client portal (web) | Clients order reports, see status, read reports, approve escrow conditions, watch the build | 2 |
| Report workflow (internal web) | Lawyer, surveyor, runner and reviewer move each report through its steps and attach evidence | 2 |
| Escrow status tracker | Mirrors the state of each escrow at the partner bank and the conditions still open | 2 |
| Milestone photo app (mobile) | Contractors and inspectors capture geotagged, time-stamped photos and video, offline, and submit milestones | 3 |
| Evidence store | Stores every file with a hash, a timestamp and who uploaded it | 2 |
| Core API | One backend serving all of the above | 2 |
| Partner API | Bank and developer collateral checks | 3 |

## 2. Client portal

Users: clients abroad and local, on phone and laptop.

Features by phase:

- Phase 2: sign up, identity check, order a report, pay, see report status with dates, download the finished report, message Fidero, see escrow status and the open conditions, approve release conditions.
- Phase 3: see the build dashboard, budget against actual, photo timeline by milestone, inspector results, request an extra inspection, approve variations.

Design notes:

- Works on a slow phone connection. Pages are small. Photos are served resized.
- Status language is plain: "Searches lodged at Lands Commission on 12 March. Results expected by 2 April."
- Payment through a card and mobile money provider `[TO VERIFY]`. Fidero stores no card numbers.

## 3. Report workflow

Each report is a case that moves through fixed steps. Each step has an owner, required evidence and a due date.

| Step | Owner | Required evidence | Target days (assumption) |
|---|---|---|---|
| Intake | Fidero | Client documents, site plan, seller contact | 1 |
| Searches lodged | Runner | Receipts | 2 |
| Site visit | Surveyor and runner | Coordinates, photos, video | 5 |
| Overlay checks | Fidero | Maps | 3 |
| Consent meeting | Lawyer and runner | Signed forms, video | 7 |
| Search results | Runner | Official results | 10 |
| Legal review | Lawyer | Signed legal section | 3 |
| Second review | Fidero reviewer | Checklist | 1 |
| Release | Fidero | Final PDF, hash | 1 |

The workflow tool generates the report from the template in `docs/operations/verification-report-template.md`. Section verdicts are chosen from red, amber and green. The overall verdict cannot be green if any section is red. The scope statement is inserted from a locked text block.

Every change to a case is logged with who, when and what. The final PDF is hashed and the hash stored. A client can check that their PDF matches the hash.

## 4. Escrow status tracking

Fidero does not move money. The partner bank or licensed escrow agent holds it under an escrow agreement between client, seller and the bank.

The tracker holds, for each escrow:

- Parties, plot, agreed price, reference at the bank.
- The release conditions, copied from the report's section 11, each with a status and the evidence that closes it.
- Deposit confirmed, yes or no, with date, from the bank's statement or API.
- Release instruction sent, with the signatory and date.
- Release confirmed by the bank.

Integration options, in order of preference:

1. Bank API for deposit and release status `[TO VERIFY]` whether the partner offers one.
2. Daily statement file from the bank, reconciled by Fidero.
3. Manual entry by Fidero from the bank's confirmation, with the confirmation attached.

Release is a two-person action at Fidero and is recorded with both names. The client sees every condition and its status.

## 5. Milestone photo app

Users: contractors, inspectors and Fidero field staff. Android first `[TO VERIFY]` the share of iPhone users among contractors.

Requirements:

- **Capture in app only.** Photos and video are taken with the app's camera. Gallery uploads are blocked for evidence.
- **Geotag.** GPS position at capture, with accuracy. The app warns if the position is more than a set distance from the plot coordinates in the verification report.
- **Timestamp.** Device time plus server time on upload. A large gap is flagged.
- **Offline.** Capture works with no signal. Evidence is queued and uploaded when a connection returns. The queue survives the app being closed.
- **Tamper evidence.** Each file is hashed on the device at capture. The hash, position and time are signed with a device key and sent with the file. The server verifies the signature and stores the hash.
- **Milestone submission.** The contractor picks the milestone, sees the required evidence list from `docs/operations/milestone-schedule.md`, attaches each item, and submits.
- **Inspector mode.** The inspector sees the checklist for the milestone, ticks each item, adds photos and notes, and submits pass, pass with defects, or fail. Defects are listed with a value.
- **Low bandwidth.** Photos are compressed on device. Video is capped in length and resolution. Full-size originals can be requested later.
- **Low-end devices.** Small app, works on older Android versions `[TO VERIFY]`.

Fraud checks on the server:

- Position outside the plot buffer.
- Timestamp before the previous milestone was passed.
- Duplicate hash seen on another project.
- Image metadata inconsistent with the device.

Flagged evidence goes to a Fidero reviewer before the inspector visit.

## 6. Evidence store

- Object storage with versioning, so nothing is overwritten.
- Each object has a record: hash, uploader, device, time, position, case or project, milestone.
- Access is by signed, short-lived links. Nothing is public.
- Retention follows the data policy below. Deletion is logged.

## 7. Core API and data model

Main entities: client, seller, plot, report case, report section, evidence, escrow, condition, project, milestone, submission, inspection, defect, contractor, inspector, professional, audit event.

- One backend, one database. Keep it boring: a relational database and a web framework the team knows.
- All actions go through the API and are written to an audit log that cannot be edited by application users.
- Roles: client, Fidero staff, Fidero reviewer, lawyer, surveyor, runner, contractor, inspector, partner. Each sees only the cases or projects assigned to them.

## 8. Partner API

Phase 3. Banks and developers submit a plot reference and receive a status: no report, report in progress, or the verdict and date of an existing report, with the client's consent on file. A full report is never shared without the client's consent. Pricing `[TO VERIFY]`.

## 9. Data protection

Fidero handles data about clients, sellers, family heads, chiefs, witnesses, contractors and neighbours. The Data Protection Act 2012 (Act 843) applies.

Measures:

- **Register** with the Data Protection Commission `[TO VERIFY]` the requirement for Fidero's size and activity.
- **Minimise.** Collect only what the report needs. Do not record neighbours' personal details beyond what a dispute check requires.
- **Consent and notice.** Everyone recorded on video is told why and signs. Clients agree to a plain-language privacy notice.
- **Purpose.** Report data is used for the report, the escrow and the build, and for anonymised case studies only with written consent.
- **Access control.** Role-based. Professionals see only their cases. Two-person rule for escrow release and for export of any full dataset.
- **Encryption.** In transit everywhere. At rest in the database and the evidence store. Device storage in the app is encrypted and cleared after upload.
- **Location.** Data hosted in Ghana or in a jurisdiction the Commission accepts `[TO VERIFY]`. Record where each service stores data.
- **Retention.** Report cases kept for the period the insurer and lawyer advise `[TO VERIFY]`, then deleted or anonymised. Consent videos kept for the same period. Client accounts deleted on request subject to legal holds.
- **Rights.** Clients and sellers can ask what Fidero holds about them and have it corrected. One contact handles requests within a set time `[TO VERIFY]`.
- **Breach plan.** A written plan: contain, assess, notify the Commission and affected people within the required time `[TO VERIFY]`, record.
- **Staff.** Every professional and staff member signs a data agreement and does a short training before access.
- **Safety data.** Threat and incident logs about disputed plots are held separately with tighter access, because they identify people who may be dangerous or at risk.

## 10. Hosting and operations

- Cloud hosting with daily backups kept in a second region `[TO VERIFY]` data location constraints.
- Monitoring on uptime, error rate and upload queue length.
- Staging environment for every release. No direct changes in production.
- Secrets in a secrets manager, never in code.
- Dependencies pinned and reviewed. Security review before each phase launch.

## 11. Build order

1. Phase 2 (months 3-9): core API, report workflow, evidence store, client portal with report status and download, escrow tracker with manual entry.
2. Phase 3 (months 9-18): milestone photo app, inspector mode, build dashboard, bank statement or API integration, partner API.
3. Phase 4 (months 18-36): traditional authority records module, materials ordering, multi-country support for the Nigeria pilot.

Team for phase 2: one product and engineering lead plus one or two developers `[TO VERIFY]` against the budget in `docs/proposal.md`.
