# 90-day validation plan: manual services

Goal: launch two front doors as manual services and learn, before building software, which brings users, repeat use and margin (`docs/decisions/2026-11-12-two-front-doors.md`):

- **Family payments against proof:** school fees, hospital bills and household bills, verified and confirmed with the receipt returned. Frequent: this door builds the habit and brings users.
- **Property checks on land and houses:** the largest sums and the strongest trust story.

Alongside them, test building a house in stages with a few clients, and the checked plots and survey tests below.

All numbers are assumptions unless marked otherwise. Unknown numbers are `[TO VERIFY]`.

## 1. What a property report must cover

Every report follows the template in `docs/operations/verification-report-template.md`. The checklist:

1. **Identity of the plot.** Site plan, plot number, locality, Ghana Post GPS address, coordinates from the surveyor.
2. **Lands Commission searches.** Official search on the plot and on the seller's name. Any registered interests, caveats or pending applications.
3. **Surveyor check.** Licensed surveyor visits the site, picks up the pillars, compares the ground to the site plan and to the Lands Commission cadastral records. Notes overlaps with neighbours.
4. **Imagery.** Satellite image of the plot with the boundary drawn. Photos from the site visit.
5. **Overlay checks.** Government acquisitions, road reserves, wetlands, flood zones, known dispute areas, planning scheme zoning.
6. **Seller authority.** Who is selling, what interest they hold, and who must consent. Confirmation with the stool, skin or family head. Signed consent, video-recorded, with witnesses.
7. **Chain of ownership.** Previous transfers, indentures, receipts, any allocation note from the traditional authority.
8. **Occupation and threats.** Who is on the land now, any structures, any sign of land guards or active dispute.
9. **Verdict.** Red, amber or green, with the reasons and the conditions to move from amber to green.
10. **Scope statement.** The exact liability wording from the template, unchanged.

**For a house or other building**, add: the building permit and approved plans from the local assembly, a structural inspection by a qualified inspector or engineer `[TO VERIFY which]`, who lives in it now and on what tenancy, and utility accounts and arrears. The platform's building case template covers the same steps (FR-CASE-013).

## 1a. How family payments work by hand

Tenmina never holds client money. Until a licensed partner can pay on a client's behalf, family payments use **verify and confirm**:

1. **Verify the payee once.** School, hospital, pharmacy, utility or landlord: registration, a bank or mobile money account in its own name, and a named contact. Record it in the tracker.
2. **Confirm each invoice** with the institution: amount, reference, the pupil or patient.
3. **The client pays** the verified account directly, from their own bank or money transfer service, using the reference.
4. **The institution confirms receipt**, and Tenmina sends the client the official receipt. Record it in the tracker's Institution payments tab.
5. **Repeat on a calendar.** School terms, monthly bills and repeat prescriptions are reminded before they are due.

Fee: a charge per payment or a monthly plan `[TO VERIFY]`, paid through the payment provider. Never cash to a relative, and never Tenmina's account.

## 1b. Test: building a house in stages

With 3 to 5 clients who are already building at home (assumption):

1. Verify the builder: identity, a bank or mobile money account in the builder's own name, references.
2. Agree the stages with the client, using `docs/operations/milestone-schedule.md`.
3. At each stage, an inspector visits, photographs the work against the stage checklist, and confirms the builder's invoice. Photos are fingerprinted like all evidence.
4. The client pays the builder's verified account for that stage, holding back any defect value. Record each stage in the tracker's Build stages tab.

Learn: how often stages come, what clients pay for the inspection, and how often a stage is not ready when the builder says it is.

## 2. Professionals to contract

| Role | What they do | Terms to test |
|---|---|---|
| Lawyer (land and conveyancing) | Runs Lands Commission searches, reviews documents, attends consent meetings, signs off the legal section | Per-report fee `[TO VERIFY]`, retainer later |
| Licensed surveyor | Site visit, pillar pick-up, comparison to site plan and cadastral records, surveyor's section of the report | Per-visit fee `[TO VERIFY]`, travel extra |
| Field runner | Follows up searches that Tenmina's office submits from its own Lands Commission account, arranges site visits and consent meetings, takes photos and video | Monthly fee `[TO VERIFY]` plus expenses |
| Building inspector or engineer `[TO VERIFY which]` | Structural inspection for house checks; inspects each stage in the building test | Per-visit fee `[TO VERIFY]` |

Rules:

- Contract two of each role so one slow professional does not stall the service.
- Each professional signs a short agreement covering scope, confidentiality, data handling and turnaround: `docs/operations/case-kit/professional-agreement.docx`. Clients accept `docs/operations/case-kit/client-terms.docx` before paying.
- Check licences with the Ghana Institution of Surveyors and the Ghana Bar Association `[TO VERIFY]` before the first job.
- Get a professional indemnity insurance quote in the first 30 days. Do not deliver a report to a paying client without cover in place or a clear written scope limit agreed with a lawyer.

## 3. Pricing to test

| Tier | Price | Who |
|---|---|---|
| Diaspora standard | $250-600 per plot, test at three points: $300, $450, $600 | Clients abroad |
| Local standard | GHS 2,000-4,000 per plot | Local professionals |
| Rush | Standard plus `[TO VERIFY]` | Turnaround under 10 working days |
| Extra plot, same seller | Discount `[TO VERIFY]` | Buyers checking several plots |
| House check | Land check plus building inspection `[TO VERIFY]` | Buyers of a house |
| Family payment | Per payment `[TO VERIFY]`, or a monthly plan `[TO VERIFY]` covering a set number of payments | Clients paying schools, hospitals and bills |
| Building stage | Per stage inspected `[TO VERIFY]` | Clients building a house |

Test method: offer each of the first 20 diaspora clients one price point in rotation. Record acceptance, objections and what they compared it to. For family payments, test a per-payment fee against a monthly plan with the first 20 clients who use them.

## 4. Reaching the first 20 diaspora clients

Target: 50 paid reports in 90 days (assumption), of which the first 20 come from diaspora clients.

1. **Weeks 1-2.** List 10 Ghanaian associations, churches and hometown associations in the UK, US, Canada, Germany and the Netherlands. Get a named contact at each. Offer a free 30-minute talk on land fraud.
2. **Weeks 2-6.** Run four webinars. Each ends with an offer of a report at the test price. Collect email and WhatsApp contacts.
3. **Weeks 3-12.** Referral reward: a client who brings another client gets `[TO VERIFY]` off the next report or a free extra inspection.
4. **Weeks 4-12.** Approach two remittance companies with a co-marketing offer. See `docs/partners.md`.
5. **From the first delivered report.** Publish an anonymised case study with the client's written consent. One per month.
6. **Throughout.** Personal network of the founder and the professionals. Ask every contact for one introduction.

Materials: the webinar deck is a Slides artifact at https://claude.ai/artifact/Q6e9sMd1RNRTTqVSXMyEyX (13 slides with speaker notes, ending with the offer and the survey poll); the messages to leaders, the members' announcement, the after-webinar message and the referral note are in the outreach pack at https://claude.ai/artifact/6RnTrFE85b6gyuvG4mtEc6.

Every lead goes into a simple spreadsheet: source, date, price offered, outcome, reason.

## 4a. Test: checked plots from established sellers

Decided 12 November 2026 (`docs/decisions/2026-11-12-checked-plots-and-established-sellers.md`). Buyer-found verification stays the main product. Alongside it, test whether buyers will buy plots Tenmina has already checked.

1. **Weeks 3-6.** Screen 2 or 3 established sellers: registered company, Real Estate Agency Council licence where it applies `[TO VERIFY]`, the estate's title or lease checked at the Lands Commission, a clear court search, clear overlays, at least 3 references from past buyers, and a signed seller agreement. Record each in the tracker's Sellers tab.
2. **Weeks 5-8.** Check 10 to 20 of their plots in full. Each seller pays a fixed fee per plot `[TO VERIFY]`, the same whatever the verdict, and no success fee. Record each in the Checked plots tab.
3. **Weeks 6-12.** Offer plots that can be offered (green, in date, screened seller, not sold) to every buyer whose own plot came back red, and to every lead looking for land. Tell them the seller pays Tenmina to check plots. A buyer who chooses one gets a fresh search and a report in their own name, at a reduced fee `[TO VERIFY]`.

Rules: the buyer is always the client; no shortcuts for established sellers; sellers never see a buyer's report first and never pay Tenmina's professionals. Seller-paid checks do not count toward the day-90 demand criteria.

**Decision at day 90 (working assumptions):**

- At least 20% of leads offered a checked plot buy one, and at least 2 sellers accept the fixed fee: propose moving the verified listings marketplace (F-19) from R2 into R1.
- Under 10% buy: keep F-19 in R2 and keep checked plots as a manual offer only.
- Between the two: run 30 more days and decide again.

Also record how many established sellers' plots were not green. A high share is a finding in itself: being established is not proof of a clean title.

## 4b. Survey: what else people pay for at home

Ask every lead and every webinar attendee one question: **"What else do you pay for at home?"** The answers decide which candidate line (business plan, candidate lines) to test after land. The script and options are in `docs/operations/home-payments-survey.md`.

- The landing page order form asks it as optional tick boxes, and the answers arrive in the request message.
- Webinars end with it as a poll; WhatsApp leads get it as one follow-up message.
- Record each answer in the tracker's Leads tab (the "Also pays" columns). The Review tab counts each need and its share.
- Read the results after the first 50 answers (assumption). Bring the top one or two needs to the day-90 review as the next line to test by hand.

The survey only asks. It promises no service and takes no money for any line that has not passed its gate.

## 5. What to measure

| Metric | Target (assumption) | How |
|---|---|---|
| Paid property reports delivered | 50 in 90 days | Count |
| Diaspora clients | 20 | Count |
| Turnaround time | Median under 20 working days, none over 30 | Date of payment to date of delivery |
| Cost per report | Under 40% of price | Sum of lawyer, surveyor, runner, fees, travel |
| Gross margin per report | Over 60% | Price minus cost |
| Report outcomes | Share red, amber, green | Count. A high red share is a selling point |
| Conversion to escrow | Share of green reports where the client asks for escrow | Count, even before escrow exists. Record the ask |
| Conversion to build | Share of clients who ask about construction management | Count |
| Lead to paid conversion | `[TO VERIFY]` | Leads spreadsheet |
| Client satisfaction | Would recommend, yes or no | One question after delivery |
| Safety incidents | Zero | Log every threat or confrontation |
| Family payments confirmed with a receipt | 100 in 90 days (assumption) | Tracker Institution payments |
| Active clients (at least one paid service) | 60 (assumption) | Tracker Clients tab |
| Repeat clients (two or more transactions) | 30% of active clients (assumption) | Tracker Clients tab |
| Building stages inspected | 6 across 3 or more clients (assumption) | Tracker Build stages |
| Lands Commission search time | Days per search | Log per search |
| Checked plots bought | At least 20% of leads offered one (assumption) | Tracker Review: share of offered leads who bought |
| Established sellers' plots not green | Record, no target | Tracker Checked plots tab |
| What else leads pay for at home | 50 answers by day 90 (assumption) | Tracker Review: survey summary |

Review the numbers every two weeks.

## 6. Go/no-go criteria at day 90

Go to phase 2 (escrow partner and client portal) if all of these hold:

- At least 20 paid property reports delivered (assumption), paid by buyers. Seller-paid checks of checked plots are not counted.
- At least 60 family payments confirmed with a receipt (assumption).
- At least 40 active clients, and at least 30% of them repeat clients (assumptions).
- At least 12 diaspora clients.
- Median turnaround under 25 working days.
- Cost per report under 50% of price.
- At least 30% of green-report clients ask for escrow or a safe way to pay.
- No safety incident that could not be managed by the withdraw rule.
- Professional indemnity cover in place.

Pause and rework if:

- Fewer than 10 property reports and fewer than 30 family payments. The channels do not work. Rework the pitch and the channels before spending on software.
- Fewer than 15% of active clients come back. The service is not a habit yet; find out why before building the portal.
- Cost per report over 70% of price. Renegotiate professional fees or raise the price.
- Median turnaround over 35 working days. Fix the search process before taking more clients.

Stop if:

- A report is proven wrong on a point within scope and the cause cannot be fixed by process.
- No escrow partner is willing to talk after approaching two banks and one licensed agent.

## 7. Week-by-week outline

| Weeks | Work |
|---|---|
| 1-2 | Contract lawyer, surveyor, runner. Finalise report template and scope wording. Get insurance quote. Register data protection `[TO VERIFY]`. Build leads spreadsheet. |
| 2-4 | First webinar. First 5 reports at test prices. Time every step. |
| 5-8 | Three more webinars. Approach remittance companies. Reports 6-25. First case study. |
| 1-12 | Family payments from week 1: verify each institution once, confirm each invoice, return each receipt (section 1a). Offer them to every lead and every property client. |
| 3-12 | Building test with 3 to 5 clients (section 1b). |
| 3-12 | Checked plots test (section 4a): screen sellers in weeks 3-6, check their plots in weeks 5-8, offer them from week 6. |
| 9-12 | Referral push. Approach escrow banks with the report numbers. Reports 26-50. Day 90 review against the criteria above. Draft the country 2 plan from the Ghana numbers. |
