# Fidero

Fidero (from *fides*, trust) is a land verification, escrow and diaspora construction platform for Ghana. It lets a Ghanaian abroad buy a plot and build a house without being cheated or losing track of the money.

All figures in this repository are working assumptions, not verified data. Unknown numbers are marked `[TO VERIFY]`.

## The problem

Most land in Ghana is held under customary ownership by stools, skins and families. Records are scattered. The same plot is sold several times. Sellers lack authority. Site plans do not match the ground. Plots sit inside government acquisitions or road reserves. Land guards intimidate buyers. Title registration is slow.

Ghanaians abroad send roughly $4-5B a year home. Much of it goes to land and building. Money sent to relatives or contractors for construction is often diverted, and projects stall.

## The solution: one pipeline

1. **Verify.** A land due-diligence report in 2-4 weeks. Lands Commission searches, an independent licensed surveyor check against the site plan, Ghana Post GPS and satellite images, overlay checks (acquisitions, wetlands, road reserves, flood zones, dispute areas), and confirmation of the seller's authority with the stool or family, with signed and video-recorded consent. Output is a red, amber or green report.
2. **Buy.** Purchase money is held in escrow with a partner bank or licensed escrow agent and released only when conditions are met. Optional conveyancing and title registration tracking.
3. **Build.** Vetted contractors, a quantity surveyor's bill of quantities, and payments released only at milestones (foundation, blocks, lintel, roof, finishing). Each milestone is confirmed by geotagged, time-stamped photos and video plus an independent inspector. Bulk materials are delivered to site. The owner sees budget against actual and a photo timeline on a dashboard.

Over time, Fidero digitises allocation records with traditional authorities under a revenue share.

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
| Extra inspections | $50-100 each |

Illustrative year 3 revenue: about $1.9M a year, mostly in hard currency. Verification starts as a manual service, so revenue begins in month one.

## The ask

Pre-seed: $400k for 18 months. It funds the manual verification service, the escrow partnership and client portal, and the construction management product with the milestone photo app.

## Repository map

| Path | What it holds |
|---|---|
| `README.md` | This summary |
| `docs/proposal.md` | Full business proposal |
| `docs/validation-plan.md` | 90-day plan to launch the manual verification service |
| `docs/partners.md` | Partner types and the first ask to each |
| `docs/operations/verification-report-template.md` | Structure of the red/amber/green land verification report |
| `docs/operations/milestone-schedule.md` | Construction milestone schedule, release evidence and inspector checklists |
| `docs/product/architecture.md` | Proposed architecture for the portal, report workflow, escrow tracking and milestone photo app |

## Naming note

Never use "guard" in Fidero branding or product names. Land guards are the threat the service protects against.
