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
| Construction | 9-18 | Launch construction management and the milestone photo app | 40 active builds, one bank contract |
| Scale | 18-36 | Traditional authority records, bulk materials, Nigeria pilot | `[TO VERIFY]` |

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
