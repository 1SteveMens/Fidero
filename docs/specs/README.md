# Fidero product specification set

Six documents that take Fidero from business case to running service. Document 01 is the source of truth. Every other document traces to its IDs.

| No. | Document | What it covers |
|---|---|---|
| 01 | [Requirements and Product Specification](01-requirements-and-product-specification.md) | Business requirements (BRD), product requirements (PRD) and software requirements (SRS) |
| 02 | [Architecture and Technical Design](02-architecture-and-technical-design.md) | System, database, APIs, security and infrastructure |
| 03 | [UI/UX Design](03-ui-ux-design.md) | Wireframes, user flows, design system, and a [clickable prototype](03-prototype/index.html) |
| 04 | [Project Plan and Backlog](04-project-plan-and-backlog.md) | Milestones, epics, user stories and priorities |
| 05 | [Testing and Acceptance](05-testing-and-acceptance.md) | Test strategy, test cases, acceptance testing and traceability |
| 06 | [Deployment and Operations](06-deployment-and-operations.md) | Release procedures, monitoring, incident response and recovery |

## How the IDs connect

| From | To | Example |
|---|---|---|
| Business requirement `BR-nn` (01) | Feature `F-nn` (01) | BR-05 → F-08 |
| Feature `F-nn` (01) | Functional requirement `FR-<MODULE>-nnn` (01) | F-08 → FR-ESC-007 |
| Functional requirement (01) | Epic `EP-<MODULE>` and user story `US-<MODULE>-nnn` (04) | FR-ESC-007 → US-ESC-007 |
| Functional requirement (01) | Design: components, tables, endpoints (02); screens `SCR-…` (03) | FR-ESC-007 → release approval endpoint, SCR-BO screen |
| Functional requirement or rule `RUL-nn` (01) | Test case `TC-…` (05) | FR-ESC-007 → TC-ESC-007-01 |
| Non-functional requirement `NFR-…` (01) | SLOs, alerts and runbooks (06) | NFR-AVL-02 → backup and recovery plan |

A user story number always equals the number of the functional requirement it implements.

## Status

Version 0.1, working draft, 31 October 2026. All figures are working assumptions. Unknowns are marked `[TO VERIFY]`.
