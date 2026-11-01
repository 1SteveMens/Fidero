# Fidero

Fidero (from *fides*, trust) is the trusted agent at home for people abroad. Anyone in the diaspora who needs something done in their home country, from buying a plot to paying a parent's hospital bill, can have it checked, paid against proof, and shown to them. Ghana is the launch market. Land verification is the launch product. Nigeria follows from month 6 and Kenya from month 15.

All figures in this repository are working assumptions, not verified data. Unknown numbers are marked `[TO VERIFY]`.

## The problem

People abroad cannot see, verify or control what happens at home. They send money to a relative and hope.

- Land is sold twice. Sellers lack authority. Site plans do not match the ground. Plots sit inside acquisitions or road reserves. Land guards intimidate buyers.
- Building money is diverted. Projects stall.
- School fees never reach the school. Hospital bills arrive by WhatsApp at 2am with no invoice. Nobody checks on an elderly parent. A house at home is lived in rent-free by relatives. Paperwork needs someone trusted to stand in a queue.

Ghanaians abroad sent home about $7.8B in 2025 and Nigerians about $21.8B (press reports of central bank figures, `[TO VERIFY]`). Most of it passes through relatives with no accountability.

## The solution: one engine

Every Fidero line works the same way.

1. **Verify** the asset or the people: the plot, the seller, the school, the hospital, the carer, the contractor, the tenant.
2. **Hold** the money with a licensed partner bank or escrow agent. Fidero never holds client money.
3. **Release** it only against evidence, and only to a verified institution, supplier, vendor or professional. Never as cash to a relative.
4. **Show** the client every step in plain language.

## Product families

| Family | Line | What Fidero verifies | What releases the money | Release |
|---|---|---|---|---|
| **Property** | Land verification | Searches, survey, overlays, seller authority and consent | Report conditions met and indenture signed | R1 |
| | Building verification | Land checks plus permit, structural inspection, occupancy, rates and utilities | Conditions met, transfer signed, keys handed over | R1 |
| | Construction on own plot | Contractor, bill of quantities | Inspected milestones | R2 |
| | Off-plan homes | Developer title, permits, company, track record | Stages confirmed by app evidence and inspector | R2 |
| | Verified listings | Plot or property verified once, badge with date | Fresh search, then escrow | R2 |
| | Property management | Tenant, agreement, condition | Rent paid to the owner's own account; repairs paid against quotes and inspection | R2 |
| **Family** | Fees to institutions | The school, hospital, clinic or agency and its invoice | Paid direct to the institution, receipt returned | R1 |
| | Care visits | The carer and the care plan | Visit confirmed by check-in, photos and the family | R2 |
| | Health and funeral cover | The licensed insurer and the policy | Premiums paid to the insurer; claims paid by the insurer | R2 |
| **Projects and errands** | Project funds | Budget, person running it, suppliers | Suppliers paid against invoices; stages confirmed | R2 |
| | Paperwork and errands | The agency, the agent, the checklist | Fees paid to the agency; completion confirmed by the document | R2 |
| | Events and ceremonies | Vendors and the budget | Vendors paid against invoices and delivery evidence | R3 |
| **Later** | Relocation and shipping, vehicles, investing | Demand `[TO VERIFY]` | To be designed | R3 or later |

Land is the launch product because it is the highest-value, least-served problem and it builds the field team and the bank partnership that every other line uses. The family lines create monthly contact with clients.

## Verified listings

From month 9, sellers can pay to have a plot or property verified once and listed with a "Fidero Verified" badge. Buyers browse the listings and buy through escrow, so one verification serves many buyers. The model borrows from Alibaba: verified sellers, payment held until delivery, public track records and a dispute process. A fresh search still runs before any money moves, licensed third parties do the checks, and buyers see the full report. Developers list first, then families and stools through the records programme. Details are in `docs/proposal.md`.

## Customers

- People abroad in the UK, US, Canada, Germany and the Netherlands with family, property or plans at home. First target.
- Local professionals buying land.
- Banks and mortgage lenders needing collateral checks.
- Developers, schools, hospitals and insurers who want a trusted channel to the diaspora.

## Countries

Ghana first. Country is configuration in the software from the first release. Nigeria starts its manual phase from month 6 and Kenya from month 15. Each runs its own 90-day validation before any software is localised. The decision is recorded in `docs/decisions/2026-11-01-diaspora-platform.md`.

## Revenue model (assumptions)

| Service | Price |
|---|---|
| Verification, diaspora tier | $250-600 per plot |
| Verification, local tier | GHS 2,000-4,000 per plot |
| Escrow | 1-2% of price, minimum $200 |
| Conveyancing | $300-800 |
| Construction management | 5-8% of build value |
| Materials margin | 3-7% |
| Payment to an institution | Flat fee per payment or monthly plan `[TO VERIFY]` |
| Care visits | Per visit or monthly plan `[TO VERIFY]` |
| Property management | Share of rent `[TO VERIFY]` plus repair management fee |
| Paperwork and errands | Per errand `[TO VERIFY]` plus official fees at cost |
| Insurer partner lines | Commission from the insurer `[TO VERIFY]` |
| Bank and developer API checks | Per check, price `[TO VERIFY]` |
| Verified listing and success fee, paid by the seller | `[TO VERIFY]` |
| Extra inspections | $50-100 each |

Illustrative year 3 revenue: `[TO VERIFY]`, to be rebuilt from the 90-day validation numbers and the new lines. Verification starts as a manual service, so revenue begins in month one.

## The ask

Pre-seed: $400k for 18 months `[TO VERIFY]` against the wider scope. It funds the manual verification service, the escrow partnership and client portal, payments to institutions, the field app, and the second country's manual phase.

## Repository map

| Path | What it holds |
|---|---|
| `README.md` | This summary |
| `CLAUDE.md` | Context and writing rules for Claude sessions working on Fidero |
| `docs/decisions/` | Decision records. Start with `2026-11-01-diaspora-platform.md` |
| `docs/proposal.md` | Full business proposal |
| `docs/validation-plan.md` | 90-day plan to launch the manual verification service |
| `docs/partners.md` | Partner types and the first ask to each |
| `docs/operations/verification-report-template.md` | Structure of the red/amber/green land verification report |
| `docs/operations/milestone-schedule.md` | Construction milestone schedule, release evidence and inspector checklists |
| `docs/product/architecture.md` | Early architecture proposal. Superseded in detail by `docs/specs/02` |
| `docs/specs/` | Product specification set: requirements (BRD, PRD, SRS), architecture, UI/UX, project plan and backlog, testing, deployment and operations |

## Naming note

Never use "guard" in Fidero branding or product names. Land guards are the threat the service protects against.
