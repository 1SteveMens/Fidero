# Phone apps UI audit: raw results

Run 2026-11-17 20:12 UTC by `scripts/ui-audit/apps.js` on the web export of each app, against the seeded development data (`seed_dev`).
Modes: 390x844 light, 390x844 dark, 375x667 light, 375x667 dark. Contrast 4.5:1, or 3:1 for text 24 px and up, bold 18.66 px and up, and icons.

Screens visited: 200 (267 views including sheets and in-place changes), each checked in 4 modes.

| Check | Findings |
|---|---|
| invisible-text | 0 |
| contrast | 0 |
| overflow | 0 |
| cut-off | 0 |
| overlap | 0 |
| touch-target | 0 |
| empty | 0 |
| still-loading | 0 |
| broken-image | 0 |
| bad-text | 0 |
| raw-data | 0 |
| dead-link | 0 |
| navigation | 0 |
| console (for information) | 6 |

## console

- `/case/[id]` as client/ama [all]: api 404: GET /v1/cases/01a1eae1-eba5-7910-92d5-a3fc44a8a942
- `/release/[id]` as client/ama [all]: api 404: GET /v1/account/commitments/01a1eae1-8e32-7cf3-a49e-799b0beec4fb
- `/report/[id]` as client/ama [all]: api 404: GET /v1/account/commitments/01a1eae1-8e32-7cf3-a49e-799b0beec4fb
- `/` as client/kofi [all]: api 404: GET /v1/account
- `/case/[id]` as client/kofi [all]: api 404: GET /v1/account
- `/money` as client/kofi [all]: api 404: GET /v1/account

## Coverage

- client/public: 5 screens.
- client/ama: 68 screens. Not reached: `/checkout/[id]`, `/concern/[id]`, `/face-id`, `/payee-change/[id]`, `/turn-on-notifications`.
- client/kofi: 41 screens. Not reached: `/care-plan/[id]`, `/care-visit/[id]`, `/checkout/[id]`, `/concern/[id]`, `/dispute/[id]`, `/errand/[id]`, `/escrow/[id]`, `/event/[id]`, `/face-id`, `/fee-payment/[id]`, `/invoice/[id]`, `/managed/[id]`, `/payee-change/[id]`, `/policy/[id]`, `/premium/[id]`, `/project/[id]`, `/release/[id]`, `/repair/[id]`, `/report/[id]`, `/set-aside/[id]`, `/turn-on-notifications`.
- field/public: 3 screens.
- field/inspector: 13 screens. Not reached: `/errand/[id]`, `/pay/[id]`.
- field/carer: 11 screens. Not reached: `/errand/[id]`, `/pay/[id]`.
- field/agent: 11 screens. Not reached: `/errand/[id]`, `/pay/[id]`.
- field/runner: 16 screens. Not reached: `/errand/[id]`.
- field/surveyor: 12 screens. Not reached: `/errand/[id]`.
- field/lawyer: 11 screens. Not reached: `/errand/[id]`, `/job/[type]/[id]`.
- field/qs: 9 screens. Not reached: `/errand/[id]`, `/job/[type]/[id]`, `/pay/[id]`.
