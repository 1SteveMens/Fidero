# Decision: one Tenmina account per client, with commitments inside it

Date: 17 November 2026
Decided by: the founder

## Context

The platform modelled a separate held-funds balance and a separate escrow for each purchase, build, event or repair, shown to the client as several account cards side by side. People abroad think of one account at home, not several.

## Decision

1. **One account per client** at the licensed bank, with one set of pay-in details and one balance shown as "Held at the bank for you", with a line per currency where the client pays in more than one.
2. **Everything is paid from it:** school fees and bills, care visits, errands, insurance premiums, building stages, event vendors, repairs, and the money set aside for a land or house purchase.
3. **Commitments inside the account.** When money is committed to a purchase, a building contract or an event, that amount is set aside inside the account for that deal: "GHS 120,000 set aside for the Kasoa plot". A commitment is released only to that deal's verified payee and only when its conditions are met; a cancelled commitment is refunded to the source account (RUL-29), not returned to free spending, unless the client chooses to keep it in the account.
4. **The bank keeps the separation.** Underneath, the bank tracks each commitment so a release for one purpose can never use money committed to another, and a seller's three-party agreement still guarantees the agreed price is held. The client sees one account; the separation is bookkeeping at the bank.

## Rules unchanged

Tenmina never holds client money. Every release names a verified payee. The client approves first, then two Tenmina staff. Silence is never approval.

## Consequences

- Specs: RUL-34 and the held-funds and escrow requirements in document 01; the escrow and held-funds tables in document 02; the account cards rule in document 03 (one account card with its commitments); tests in document 05.
- Escrow pilot proposal for banks: one account per client with commitments tracked inside it, instead of a virtual account per escrow.
- Code: escrow module, portal home and Family, back office escrow screens, client app Home.

All figures are working assumptions, not verified data.
