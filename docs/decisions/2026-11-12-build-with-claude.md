# Decision: Claude writes the software, the founder tests it

Date: 12 November 2026. Decided by the founder.

## What changed

Tenmina has no money yet to hire developers. Until revenue allows it, Claude (the AI coding assistant used in these sessions) writes the code for every part of the platform: the API, the portal, the back office, and both apps, Tenmina and Tenmina Field. The founder tests on real phones and makes every product decision. Field users test Tenmina Field on the Android phones and iPhones they already use.

This replaces, for now, the hired team in `docs/specs/01` C-07 and in `docs/specs/04` sections 2, 5 and 11: the R1 developers, the contract developer (Option A+ and the S14 plan), and the R2 mobile developer and QA engineer (Option R2-A). The sprint capacity tables in 04 no longer plan the work. The order of work in 04, by dependency and priority, still does.

## What does not change

- R0, the manual service, comes first. The gates G0, G1 and G2 still decide when each release opens to clients.
- Every rule in `CLAUDE.md` and document 01. Tenmina never holds client money; the client approves first, then two staff; silence is never approval; evidence is tamper-evident.
- Every requirement, test and design document. Code traces to the requirement IDs in 01 and the tests in 05.

## What still needs people and some money

| Item | Who | Cost (working assumptions) |
|---|---|---|
| Testing on real phones: the founder's iPhone, field users' Android phones and iPhones | Founder, field users | None |
| Expo account for cloud builds of the apps | Founder | Free tier `[TO VERIFY]` |
| Apple Developer Program, needed to install test builds on iPhones and to publish | Founder, in Tenmina's name | About $99 a year `[TO VERIFY]` |
| Google Play Console, needed to publish on Android | Founder | About $25 once `[TO VERIFY]` |
| Signing keys and store accounts held by two trusted people (EN-64, EN-65) | Founder and one other person | None |
| Independent security review of the code before any real escrow release or institution payment runs through the platform | An outside reviewer | `[TO VERIFY]` |
| Cloud hosting once the platform serves clients | Founder | `[TO VERIFY]` |
| Lawyer's view on store rules for payments and financial apps (Q-23, Q-24) | Lawyer | `[TO VERIFY]` |

## How testing works

- **Client app now:** Expo Go on the founder's iPhone, started from the founder's laptop. Steps in `docs/operations/testing-the-apps.md`.
- **Tenmina Field:** screens, camera-only capture and GPS check-in also run in Expo Go. Signing photos with the phone's secure chip (FR-MOB-004) needs a test build: an install file on Android, and on iPhone a build that needs the Apple Developer Program.
- Claude runs the automated tests and checks every screen in a phone-sized browser before each hand-over. The founder confirms on the phone.

## Risks and how we limit them

| Risk | Limit |
|---|---|
| One author reviews its own code | One automated test per business rule (EN-32); the outside security review before money moves; a hired or contract reviewer as soon as revenue allows |
| Knowledge held only in chat sessions | Everything lives in the repository: code, tests, decisions and documents |
| Phone features that only a real device proves | A device test step for each native feature, run by the founder before it is called done |

## When to hire

When monthly revenue `[TO VERIFY]` covers a developer, or at gate G1, whichever comes first, hire one developer to review and own the code, starting with the money and evidence paths.
