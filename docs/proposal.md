# Fidero business proposal

Status: working draft. Every figure in this document is an assumption unless marked otherwise. Unknown numbers are marked `[TO VERIFY]`.

## 1. Executive summary

Fidero is a land verification, escrow and construction management platform for Ghana. It serves Ghanaians abroad first, then local buyers, banks and developers.

The product is one pipeline with three steps. Verify a plot before money changes hands. Hold purchase money in escrow until conditions are met. Build with vetted contractors, paying only at inspected milestones.

Verification starts as a manual service run by a lawyer, a licensed surveyor and a field runner. That means revenue from month one and no software risk at launch. Escrow and construction management follow once the service has a client base.

The pre-seed ask is $400k (assumption) for 18 months. Illustrative year 3 revenue is about $1.9M a year (assumption), mostly in hard currency.

## 2. Problem

### Land in Ghana

Most land is held under customary ownership by stools, skins and families. Records are scattered across traditional authorities, the Lands Commission and private hands. The common failures:

- The same plot is sold to several buyers.
- The seller has no authority to sell. A family member sells without the family head's consent, or a chief sells land that belongs to another stool.
- The site plan does not match the ground. Boundaries overlap neighbours.
- The plot sits inside a government acquisition, a road reserve, a wetland or a flood zone.
- Land guards intimidate buyers who try to develop the plot.
- Title registration takes a long time and many buyers never complete it.

### Diaspora money

Ghanaians abroad send roughly $4-5B a year home (assumption, source `[TO VERIFY]`). Much of it goes to land and building. A buyer abroad cannot visit the site, check the records or watch the builder. Money sent to relatives or contractors is often diverted. Projects stall for years. Houses are built on plots the buyer never owned.

### Why it is not solved

Lawyers and surveyors exist, but a buyer abroad has no way to find trustworthy ones, no single report that pulls every check together, and no way to tie payment to proof. Banks run collateral checks slowly and by hand. No one holds the construction money in a neutral place.

## 3. Solution

Fidero sells trust at three points where money is at risk.

### Verify

A land due-diligence report delivered in 2-4 weeks. It covers:

- Lands Commission searches on the plot and the seller.
- An independent licensed surveyor who checks the site plan against the ground and against neighbouring plots.
- Ghana Post GPS address and satellite imagery of the plot.
- Overlay checks against government acquisitions, wetlands, road reserves, flood zones and known dispute areas.
- Confirmation of the seller's authority with the stool, skin or family. Consent is signed and video-recorded.

The output is a red, amber or green report. The report structure is in `docs/operations/verification-report-template.md`.

### Buy

Purchase money is held in escrow with a partner bank or a licensed escrow agent. It is released only when the conditions in the escrow agreement are met, such as a green report, a signed indenture and stool or family consent on file. Fidero can also manage conveyancing and track title registration.

### Build

Fidero vets contractors. A quantity surveyor produces a bill of quantities. Payments are released only at milestones: foundation, blocks, lintel, roof, finishing. Each milestone is confirmed by geotagged, time-stamped photos and video plus an independent inspector. Bulk materials are bought by Fidero and delivered to site. The owner sees budget against actual and a photo timeline on a dashboard. The schedule is in `docs/operations/milestone-schedule.md`.

### Later: records

Over time Fidero digitises allocation records with traditional authorities under a revenue share. This makes future verifications faster and gives the authorities a clean register.

### Product lines beyond land

Fidero is not limited to land. Every line uses the same engine: verify, hold, release. Each line reuses the same field team, escrow partner and evidence app.

| Line | What Fidero verifies | What releases the money | Phase |
|---|---|---|---|
| Land | Searches, survey, overlays, seller authority and consent | Report conditions met and indenture signed | 1 |
| Existing buildings: houses, apartments, commercial property | The land checks, plus building permit, structural inspection, occupants and tenancies, unpaid property rates and utility bills | Report conditions met, transfer documents signed, keys and vacant possession handed over | 2 |
| Construction on the buyer's own plot | Contractor vetting and the bill of quantities | Inspected milestones | 3 |
| Off-plan homes from developers | The developer's title to the estate land, permits, company registration and track record | Construction stages confirmed by app evidence and an inspector | 3 |
| Project funds: businesses, renovations, farms, family and community projects | The budget, the person running the project, and the suppliers | Suppliers paid directly against invoices, each stage confirmed by receipts, photos and visits | 3 |
| Later candidates: vehicles, equipment, buying a business | Demand `[TO VERIFY]` | To be designed | 4 |

Project funds are the widest new line. Money sent to a relative for a business, farm or renovation is often diverted, just like construction money. Fidero pays suppliers directly against invoices and confirms each stage. It does not advise on whether a project or property is a good investment and does not guarantee returns.

Each line opens only after the previous phase passes its gate. Pricing for the new lines is `[TO VERIFY]`.

Regulation to check for the wider lines:

- Verified listings of plots and buildings, or brokering their sale, may bring Fidero under the Real Estate Agency Act 2020 (Act 1047). Whether a licence is needed is `[TO VERIFY]`.
- Project funds stay with the licensed partner bank. Anti-money laundering checks are stricter, because the money is not tied to one asset.
- Professional indemnity cover must be extended to building inspections and project funds `[TO VERIFY]`.

### Verified listings

From month 9, sellers can pay to have a plot or property verified once and listed on Fidero with a "Fidero Verified" badge. Buyers browse the listings and buy through escrow. One verification then serves many buyers, which is how Fidero grows beyond one report per buyer. The model borrows four parts of how Alibaba makes trade between strangers safe.

| Alibaba | Fidero |
|---|---|
| Verified sellers | Verified listings. Licensed third parties check the plot or property once. The badge shows the date of the checks and links to the full report. |
| Trade Assurance: payment held until delivery | Escrow. The buyer pays into the partner bank's escrow account. Money is released when every condition is recorded as met, with two Fidero staff approving each release. Fidero never holds the money. |
| Seller ratings | Public track records for sellers, developers, contractors and surveyors. Bad actors are removed. |
| Dispute process | Fixed steps and timelines when a buyer or seller contests a release. |

Rules that protect the badge:

- **Fresh search before payment.** Land is not a product. A listed plot can be resold or encroached on after it is verified. A fresh search and site check run just before any money moves. The check is cheap and is never skipped.
- **The badge cannot be bought.** The seller pays, but licensed independent surveyors and lawyers do the checks. A failed check means no listing. Buyers see the full report. Buyer-ordered reports stay available for plots that are not listed.
- **Badges expire.** A badge lapses after a set period `[TO VERIFY]`. Satellite monitoring alerts Fidero if new structures appear on a listed plot.

What can be automated. The ground truth cannot be fully automated. Someone still stands on the plot, and the family still consents in person. The target is an automated platform with a small field team behind it.

| Step | Automated | How |
|---|---|---|
| Overlay checks | Fully | Acquisition, road reserve, wetland and flood zone layers are checked as soon as coordinates are entered |
| Satellite monitoring | Fully | Alerts fire if new structures appear on a listed plot |
| Payments and receipts | Fully | Card and mobile money |
| Escrow release | Fully, once the bank offers an API `[TO VERIFY]` | Conditions met prepares the release instruction; two Fidero staff approve it |
| Construction milestones | Mostly | Evidence comes through the app with automatic fraud checks. An inspector still visits. |
| Lands Commission searches | Partly | Online where the Commission allows it `[TO VERIFY]`, otherwise a runner does them |
| Surveyor check | Partly | Drones or GPS speed it up, but a licensed surveyor still signs |
| Seller authority and consent | No | An in-person meeting the app records with video, signatures and location |

Rollout:

1. **Months 0-9.** No listings. Manual reports, the escrow partner and the portal run as planned. Overlay checks, satellite imagery and status updates are automated from the start, because they are cheap.
2. **Months 9-18.** Developers list first. They hold many plots and want diaspora buyers.
3. **Months 18-36.** Families and stools list through the records programme. Where records are digitised, the search step becomes largely automatic.

Listings add a second source of revenue. Sellers pay a listing fee and a success fee on each sale, on top of what buyers pay. Both prices are `[TO VERIFY]`. A marketplace needs buyers and sellers at the same time. The plan builds buyer demand first, so sellers can see access to diaspora buyers before they pay to list.

## 4. Market and customers

### Segments

1. **Diaspora buyers and home builders.** UK, US, Canada, Germany, Netherlands. They have hard currency, high stakes and no way to check the ground. First target.
2. **Local professionals.** Salaried buyers in Accra, Kumasi and other cities who want a plot checked before paying.
3. **Banks and mortgage lenders.** They need collateral checks on land offered as security. Sold as an API or a batch service.
4. **Developers.** They need clean title on the land they build on and a trusted channel to diaspora buyers.

### Size

Diaspora remittances to Ghana: roughly $4-5B a year (assumption). Share going to land and building: `[TO VERIFY]`. Number of land transactions a year: `[TO VERIFY]`. Number of diaspora construction projects a year: `[TO VERIFY]`. These numbers are needed before the market size can be stated with confidence.

### Why they buy

A verification report costs a small fraction of a plot. Losing the plot costs everything. Construction management costs a fraction of the build. A stalled build costs the whole budget.

### Expansion beyond Ghana

Fidero starts in Ghana and extends to other countries where the same three problems exist: customary or poorly recorded land ownership, a large diaspora sending money home for land and building, and no neutral party tying payment to proof. The first expansion market is Nigeria, as a pilot in months 18-36. Further markets are `[TO VERIFY]`.

A country qualifies for entry when it meets all of these criteria:

1. A large diaspora in the countries Fidero already serves, so existing channels reach the new market.
2. A legal framework that allows escrow through a licensed bank or agent.
3. Licensed surveyors and land lawyers available to contract.
4. A partner bank willing to run escrow and a professional indemnity insurer willing to cover reports.
5. Field safety conditions that allow site visits under Fidero's safety rules.

Each new country repeats phase 1: a manual verification service with local professionals, a country-specific report template and scope statement, and a 90-day validation before any software is localised. Ghana must have passed its construction gate before the first expansion market opens.

## 5. Business model and pricing

All prices are assumptions to be tested in the first 90 days. See `docs/validation-plan.md`.

| Service | Price | Notes |
|---|---|---|
| Verification, diaspora tier | $250-600 per plot | Tiered by plot size and location |
| Verification, local tier | GHS 2,000-4,000 per plot | Same report, local price |
| Escrow | 1-2% of purchase price, minimum $200 | Shared with partner bank, split `[TO VERIFY]` |
| Conveyancing | $300-800 | Through partner law firm |
| Title registration tracking | Included or `[TO VERIFY]` | |
| Construction management | 5-8% of build value | Covers QS, inspections, dashboard |
| Materials margin | 3-7% | On bulk materials bought for the build |
| Bank and developer API checks | `[TO VERIFY]` per check | Volume pricing |
| Extra inspections | $50-100 each | Beyond the standard milestone inspections |
| Verified listing, paid by the seller | `[TO VERIFY]` per plot, unit or estate | From month 9, developers first |
| Success fee on a listed sale, paid by the seller | `[TO VERIFY]` | Charged when escrow releases |
| Traditional authority records | Revenue share `[TO VERIFY]` | Later phase |

### Unit economics of a verification report (assumptions)

| Item | Cost |
|---|---|
| Lawyer, searches and review | `[TO VERIFY]` |
| Licensed surveyor site visit | `[TO VERIFY]` |
| Runner, travel and fees | `[TO VERIFY]` |
| Lands Commission search fees | `[TO VERIFY]` |
| Professional indemnity insurance, per report share | `[TO VERIFY]` |
| Target total cost per report | Under 40% of price (assumption) |

### Illustrative year 3 (assumption)

About $1.9M a year, mostly in hard currency. The mix assumed is verification plus escrow on a share of verified plots, plus construction management on a smaller share. The underlying volumes are `[TO VERIFY]` and should be rebuilt from the 90-day validation numbers.

## 6. Go-to-market and roadmap

### Channels

- Diaspora associations, churches and hometown associations abroad. Talks, webinars and a named contact.
- Webinars on how land fraud happens and how to avoid it.
- Referral rewards for clients who bring another client.
- Partnerships with remittance companies, who already serve the same customers.
- Anonymised case studies of real reports, with the client's consent.

### Roadmap

| Phase | Months | Goal | Target |
|---|---|---|---|
| Manual service | 0-3 | Launch verification with a lawyer, a surveyor and a runner | 50 paid reports |
| Escrow and portal | 3-9 | Sign an escrow partner bank, launch the client portal | 300 reports, 50 escrows |
| Construction | 9-18 | Launch construction management, the milestone photo app and verified listings for developers | 40 active builds, one bank contract |
| Scale | 18-36 | Traditional authority records, family and stool listings, bulk materials, Nigeria pilot | `[TO VERIFY]` |

All targets are assumptions.

## 7. Competition

| Alternative | What it does | Gap Fidero fills |
|---|---|---|
| Individual lawyers and surveyors | Searches and site checks on request | No single report, no standard, hard to find from abroad, no liability framework |
| Relatives on the ground | Visit the site, talk to the seller | No records access, conflict of interest, no proof |
| Lands Commission search alone | Confirms registered interests | Misses customary ownership, ground truth and seller authority |
| Real estate agents and developers | Sell plots and houses | They are the counterparty, not an independent check |
| Remittance companies | Move money | Do not hold it against conditions |
| Other land verification or proptech startups in Ghana | `[TO VERIFY]` | Map them in the first 90 days |

Fidero's edge is the full pipeline. The report feeds the escrow, and the escrow feeds the build. Each step makes the next one safer and cheaper to sell.

## 8. Financials and use of funds

All figures are assumptions.

### Pre-seed ask

$400k for 18 months.

### Use of funds

| Use | Share | Notes |
|---|---|---|
| Operations team: lawyer, surveyor, runners, inspectors | `[TO VERIFY]` | Part contract, part staff |
| Product and engineering: portal, workflow, photo app | `[TO VERIFY]` | |
| Sales and diaspora marketing | `[TO VERIFY]` | Travel to associations, webinars |
| Professional indemnity insurance and legal | `[TO VERIFY]` | |
| Escrow partner integration | `[TO VERIFY]` | |
| Reserve | `[TO VERIFY]` | Cedi swings, slow searches |

### Revenue timing

Verification revenue starts in month one because the service is manual. Escrow revenue starts after the partner bank signs. Construction revenue starts after month 9.

### Currency

Most revenue is in hard currency from diaspora clients. Most costs are in cedis. This is a natural hedge for the business, but construction budgets quoted in dollars must be re-priced as the cedi moves.

## 9. Team and partners

### Team

| Role | Status |
|---|---|
| Founder, operations and sales | In place |
| Lawyer, land and conveyancing | To contract `[TO VERIFY]` |
| Licensed surveyor | To contract `[TO VERIFY]` |
| Field runner | To contract `[TO VERIFY]` |
| Product and engineering lead | To hire in phase 2 |
| Quantity surveyor and inspectors | To contract in phase 3 |

### Partners

Escrow partner bank or licensed escrow agent, law firms, licensed surveyors, contractors, diaspora associations, remittance companies and a professional indemnity insurer. The first ask to each is in `docs/partners.md`.

## 10. Regulation

- **Land Act 2020 (Act 1036)** sets the framework for land ownership and allows electronic conveyancing.
- **Bank of Ghana guidance** means escrow must run through a licensed bank or a licensed escrow agent. Fidero does not hold client money itself.
- **Data Protection Act 2012 (Act 843)** governs client data, seller data and recordings. Fidero registers with the Data Protection Commission `[TO VERIFY]`.
- Licensing for surveyors and lawyers is handled by their professional bodies. Fidero contracts only licensed professionals.

## 11. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| A wrong verification damages the brand | High | Professional indemnity insurance, precise report scope, two-person review, clear limits on what the report certifies |
| Lands Commission searches are slow | Medium | Runner relationships, parallel checks, honest turnaround promises, status updates to the client |
| Staff safety on disputed land | High | No solo visits, risk screening before each visit, withdraw if threatened, never confront land guards |
| Contractor fraud | High | Vetting, milestone payments only, independent inspector, materials bought by Fidero |
| Cedi swings on construction budgets | Medium | Quote in cedis with a dollar guide, re-price at each milestone, hold a reserve |
| Escrow partner delays or withdraws | Medium | Talk to two banks and one licensed agent in parallel |
| Seller or family disputes consent after the sale | Medium | Signed and video-recorded consent, witnesses, lawyer present |
| Data breach of client or seller records | High | Data protection measures in `docs/product/architecture.md` |
| Branding confused with land guards | Low | Never use "guard" in any name or product |
