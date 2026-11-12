# Decision: test checked plots, and start the escrow pilot with screened established sellers

Date: 12 November 2026
Decided by: the founder

## Context

The verification service checks plots that buyers find themselves. That is where the fraud is and where demand exists today, and it keeps Tenmina neutral. On its own it has gaps: volume depends on buyers who already have a deal, a red report ends the relationship, buyers with no plot have nowhere to go, and escrow volume is hard to plan.

## Decision

1. **Keep buyer-found verification as the way in.** It stays the main product in R0.
2. **Test a small supply of checked plots by hand in R0.** Two or three screened, established sellers have 10 to 20 plots checked. Tenmina offers them to every buyer whose own plot comes back red and to every enquiry with no plot yet. The result decides whether the verified listings marketplace (F-19, planned for R2) moves earlier. See `docs/validation-plan.md` section 4a.
3. **Mix the escrow pilot.** About 6 of the 10 pilot escrows come from 2 or 3 screened established sellers, no more than 3 from any one seller. About 4 come from ordinary family or customary sales, so the pilot also tests the problem Tenmina exists to solve.

## Rules that keep Tenmina neutral

- The buyer remains Tenmina's client. When a buyer chooses a checked plot, Tenmina runs a fresh search and issues the report to that buyer.
- A seller pays a fixed fee per plot checked, the same whatever the verdict. There is no success fee in the test (Q-31 in `docs/specs/01`).
- A plot is offered only with a green report within the validity period (RUL-12), and the buyer sees the full report (RUL-14).
- Every plot gets the full checks. Being established earns a seller no shortcuts.
- Buyers are told when a plot comes from a seller who pays Tenmina to check plots (client terms clause 1.3).
- Sellers never pay Tenmina's professionals or staff, and never see a buyer's report before the buyer.

## What "established" means

Checked, not assumed: registered company; Real Estate Agency Council licence under the Real Estate Agency Act 2020 (Act 1047) where it applies `[TO VERIFY]`; the estate's title or lease checked at the Lands Commission; a court search for disputes; no overlap with acquisitions or reserves; at least 3 references from past buyers; a signed seller agreement (`docs/operations/case-kit/seller-agreement.docx`).

## Consequences

- Tracker: "Looking for land" leads, a Sellers tab with the screening checks, a Checked plots tab, and Review measures for the test. Seller-paid checks are kept out of the day-90 demand counts.
- Validation plan: new section 4a with the test and its decision rule.
- Partners: new section on established land sellers.
- Client terms: clause 1.3. New seller agreement for the lawyer to review.
- Escrow pilot proposal: the pilot mix.
- Specs: Q-31 on success fees; F-19 may move earlier after the test.

All numbers here are working assumptions to test, not verified data.
