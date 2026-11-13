"""BLD Construction: the public interface other modules may call.

Projects (FR-BLD-001, FR-BLD-011)
    create_project(actor, *, type, title, asset_id, budget, ...) -> Project
    assign_quantity_surveyor, submit_boq, approve_budget, choose_contractor, sign_contract, open_escrow, start,
    confirm_handover, assign_inspector, propose_variation, decide_variation, cancel, resume
    build_milestones(project, rows, funds=False)      the shared engine PRJ uses for its stages
Panel (FR-BLD-003, FR-BLD-004, FR-BLD-010)
    create_member, add_documents, start_check, approve, suspend, reinstate, remove, add_conflict, link_payee,
    conflict_reasons(inspector, contractor)
Milestones (FR-BLD-005 to FR-BLD-007, FR-BLD-012)
    review_evidence, schedule_inspection, confirm_stage, client_approve, prepare_main, prepare_holdback,
    close_defect, confirm_defect, declare_link, submit_stage_evidence, remind_clients
Payments on both routes (escrow and client_direct)
    payments.prepare, payments.client_approve, payments.staff_decide, payments.record_client_payment,
    payments.confirm_receipt, payments.withdraw, payments.register_subject(part, blockers=, on_status=)

Events published: project.created, project.started, project.completed, project.closed, milestone.status_changed,
milestone.client_approved, inspection.scheduled, inspection.recorded, contractor.removed, work.accepted,
project_payment.confirmed. Consumed: submission.received, flags.cleared, release.*, escrow.funded,
dispute.opened, dispute.resolved, order.paid, case.status_changed, approval.approved, approval.rejected,
fx_rate.updated.
"""
from . import payments  # noqa: F401
from .materials import approve_materials, record_delivery, request_materials  # noqa: F401
from .milestones import (assign_extra_inspection, cancel_inspection, client_approve, close_defect,  # noqa: F401
                         confirm_defect, confirm_stage, declare_link, prepare_holdback, prepare_main,
                         remind_clients, return_milestone, review_evidence, schedule_inspection,
                         submit_stage_evidence)
from .panel import (add_conflict, add_documents, approve, conflict_reasons, create_member, link_payee,  # noqa: F401
                    reinstate, remove, start_check, suspend, track_record)
from .projects import (approve_budget, assign_inspector, assign_quantity_surveyor, build_milestones,  # noqa: F401
                       cancel, choose_contractor, confirm_handover, create_project, decide_variation, open_escrow,
                       propose_variation, resume, sign_contract, start, start_blockers, submit_boq)
