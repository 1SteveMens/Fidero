# Fidero: context for Claude sessions

Fidero (from *fides*, trust) is the trusted agent at home for people abroad. Anyone in the diaspora who needs something done in their home country can have it checked, paid against proof and shown to them. The engine is the same for every line: verify the asset or the people, a licensed partner holds the money, release only against evidence. Ghana is the launch market. Land verification is the launch product. Other lines and countries follow.

Product families: Property (land, buildings, construction, off-plan, listings, property management), Family (payments direct to institutions, care visits, insurer partner cover), Projects and errands (project funds, paperwork and errands, events). The redefinition from a land platform to a diaspora platform is recorded in `docs/decisions/2026-11-01-diaspora-platform.md`. Read it first.

The founder is in Ghana and runs three ventures. This repository is only for Fidero. FarmPrint (cocoa traceability) and Kestrels (illegal-mining monitoring) have their own repositories and sessions. Do not work on them here.

## Where things are

- Business plan, the formal document: Claude doc at https://claude.ai/artifact/Mofu9Bu722tegJofEMTQ1H. Edit it with the Claude Docs tools, not by copying it into the repository.
- Original business proposal: private Claude doc at https://claude.ai/artifact/6Ubez2eMb24wnnHU8Gh93a. It may not be readable from the cloud.
- Clickable prototype: https://claude.ai/artifact/FzGbi543d8uvhyXpDDasLK, built from `docs/specs/03-prototype/index.html`.
- Repository documents: see the map in `README.md`. The specification set in `docs/specs/` is the source of truth for the product; document 01 holds every requirement ID.

## Writing rules

- Plain English, short sentences, no filler.
- Every figure is a working assumption, not verified data. Say so.
- Never invent statistics. Where a number is needed and unknown, write `[TO VERIFY]`.
- Never use the word "guard" in branding or product names. Land guards are the threat Fidero protects against.
- Keep the business plan doc, the repository documents and the specification set consistent. A change to one usually needs the same change in the others. A requirement change goes into `docs/specs/01` first; documents 02 to 06 trace to its IDs.

## Core design rules

- Fidero never holds client money. A licensed bank or escrow agent does, under Bank of Ghana guidance and the equivalent in each country.
- Money is released only to a verified institution, supplier, vendor or professional. Never as cash to a relative.
- Two Fidero staff approve every release. The client approves first. Silence is never approval.
- Every piece of evidence is tamper-evident.
- Each new product line or country opens only after the previous phase passes its gate.
- Country is configuration. Nothing about Ghana is hard-coded. Each new country repeats the manual verification phase and a 90-day validation before any software is localised.
- Insurance is sold only as a licensed insurer's product. Fidero does not transfer money across borders.

## Git

- The repository was created empty. The first branch pushed, `claude/quirky-wozniak-an94wx`, is currently its only branch. Check the default branch on GitHub before starting new work.
- Do not open pull requests unless the founder asks.
