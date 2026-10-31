# Fidero

Fidero (from *fides*, trust) is a land verification, escrow and diaspora construction platform. It lets someone abroad buy a plot at home and build a house without being cheated or losing track of the money. Ghana is the launch market. Fidero then extends to other countries with customary land tenure and large diasporas, starting with a Nigeria pilot.

All figures in this repository are working assumptions, not verified data. Unknown numbers are marked `[TO VERIFY]`.

## The problem

Most land in Ghana is held under customary ownership by stools, skins and families. Records are scattered. The same plot is sold several times. Sellers lack authority. Site plans do not match the ground. Plots sit inside government acquisitions or road reserves. Land guards intimidate buyers. Title registration is slow.

Ghanaians abroad send roughly $4-5B a year home. Much of it goes to land and building. Money sent to relatives or contractors for construction is often diverted, and projects stall.

## The solution: one pipeline

1. **Verify.** A land due-diligence report in 2-4 weeks. Lands Commission searches, an independent licensed surveyor check against the site plan, Ghana Post GPS and satellite images, overlay checks (acquisitions, wetlands, road reserves, flood zones, dispute areas), and confirmation of the seller's authority with the stool or family, with signed and video-recorded consent. Output is a red, amber or green report.
2. **Buy.** Purchase money is held in escrow with a partner bank or licensed escrow agent and released only when conditions are met. Optional conveyancing and title registration tracking.
3. **Build.** Vetted contractors, a quantity surveyor's bill of quantities, and payments released only at milestones (foundation, blocks, lintel, roof, finishing). Each milestone is confirmed by geotagged, time-stamped photos and video plus an independent inspector. Bulk materials are delivered to site. The owner sees budget against actual and a photo timeline on a dashboard.

Over time, Fidero digitises allocation records with traditional authorities under a revenue share.

## Beyond land

Fidero is not limited to land. Every product line uses the same engine: verify the asset or the people involved, hold the money with a partner bank, and release it only against evidence. Land is the launch product.

| Line | What Fidero verifies | What releases the money | Phase |
|---|---|---|---|
| Land | Searches, survey, overlays, seller authority and consent | Report conditions met and indenture signed | 1 |
| Existing buildings: houses, apartments, commercial property | The land checks, plus building permit, structural inspection, occupants and tenancies, unpaid property rates and utility bills | Report conditions met, transfer documents signed, keys and vacant possession handed over | 2 |
| Construction on the buyer's own plot | Contractor vetting and the bill of quantities | Inspected milestones | 3 |
| Off-plan homes from developers | The developer's title to the estate land, permits, company registration and track record | Construction stages confirmed by app evidence and an inspector | 3 |
| Project funds: businesses, renovations, farms, family and community projects | The budget, the person running the project, and the suppliers | Suppliers paid directly against invoices, each stage confirmed by receipts, photos and visits | 3 |
| Later candidates: vehicles, equipment, buying a business | Demand `[TO VERIFY]` | To be designed | 4 |

Project funds cover money sent home for a shop, a farm, a renovation or a family project. Fidero pays suppliers and workers directly instead of handing cash to someone on the ground. It confirms the money was spent as agreed. It does not judge whether the project will succeed.

## Verified listings

From month 9, sellers can pay to have a plot or property verified once and listed with a "Fidero Verified" badge. Buyers browse the listings and buy through escrow, so one verification serves many buyers. The model borrows from Alibaba: verified sellers, payment held until delivery, public track records and a dispute process. A fresh search still runs before any money moves, licensed third parties do the checks, and buyers see the full report. Developers list first, then families and stools through the records programme. Details are in `docs/proposal.md`.

## Customers

- Diaspora buyers and home builders in the UK, US, Canada, Germany and the Netherlands. First target.
- Local professionals buying land.
- Banks and mortgage lenders needing collateral checks.
- Developers.

## Revenue model (assumptions)

| Service | Price |
|---|---|
| Verification, diaspora tier | $250-600 per plot |
| Verification, local tier | GHS 2,000-4,000 per plot |
| Escrow | 1-2% of price, minimum $200 |
| Conveyancing | $300-800 |
| Construction management | 5-8% of build value |
| Materials margin | 3-7% |
| Bank and developer API checks | Per check, price [TO VERIFY] |
| Building verification, off-plan escrow, project funds management | [TO VERIFY] |
| Extra inspections | $50-100 each |
| Verified listing and success fee, paid by the seller | [TO VERIFY] |

Illustrative year 3 revenue: about $1.9M a year, mostly in hard currency. Verification starts as a manual service, so revenue begins in month one.

## The ask

Pre-seed: $400k for 18 months. It funds the manual verification service, the escrow partnership and client portal, and the construction management product with the milestone photo app.

## Repository map

| Path | What it holds |
|---|---|
| `README.md` | This summary |
| `CLAUDE.md` | Context and writing rules for Claude sessions working on Fidero |
| `docs/proposal.md` | Full business proposal |
| `docs/validation-plan.md` | 90-day plan to launch the manual verification service |
| `docs/partners.md` | Partner types and the first ask to each |
| `docs/operations/verification-report-template.md` | Structure of the red/amber/green land verification report |
| `docs/operations/milestone-schedule.md` | Construction milestone schedule, release evidence and inspector checklists |
| `docs/product/architecture.md` | Proposed architecture for the portal, report workflow, escrow tracking and milestone photo app |

## Naming note

Never use "guard" in Fidero branding or product names. Land guards are the threat the service protects against.
