# Fidero: context for Claude sessions

Fidero (from *fides*, trust) is a verification, escrow and payment-release platform for people abroad who buy land and property or fund projects at home. Ghana is the launch market. Expansion to other countries starts with a Nigeria pilot. Land is the launch product. Existing buildings, construction, off-plan homes and project funds follow.

The founder is in Ghana and runs three ventures. This repository is only for Fidero. FarmPrint (cocoa traceability) and Kestrels (illegal-mining monitoring) have their own repositories and sessions. Do not work on them here.

## Where things are

- Business plan, the formal document: Claude doc at https://claude.ai/artifact/Mofu9Bu722tegJofEMTQ1H. Edit it with the Claude Docs tools, not by copying it into the repository.
- Original business proposal: private Claude doc at https://claude.ai/artifact/6Ubez2eMb24wnnHU8Gh93a. It may not be readable from the cloud.
- Repository documents: see the map in `README.md`.

## Writing rules

- Plain English, short sentences, no filler.
- Every figure is a working assumption, not verified data. Say so.
- Never invent statistics. Where a number is needed and unknown, write `[TO VERIFY]`.
- Never use the word "guard" in branding or product names. Land guards are the threat Fidero protects against.
- Keep the business plan doc and the repository documents consistent. A change to one usually needs the same change in the other.

## Core design rules

- Fidero never holds client money. A licensed bank or escrow agent does, under Bank of Ghana guidance.
- Every product line uses one engine: verify the asset or people, hold the money, release only against evidence.
- Each new product line or country opens only after the previous phase passes its gate.
- Each new country repeats the manual verification phase and a 90-day validation before any software is localised.

## Git

- The repository was created empty. The first branch pushed, `claude/quirky-wozniak-an94wx`, is currently its only branch. Check the default branch on GitHub before starting new work.
- Do not open pull requests unless the founder asks.
