/* Where each kind of approval is given. Approvals with their own rules are given on their own screen, where
 * the extra checks run (core/approvals.py DEDICATED); the rest are given on the approval detail. */
export const SUBJECT_LABEL: Record<string, string> = {
  report_release: 'Report release', escrow_release: 'Escrow release', escrow_cancel: 'Escrow cancellation or refund',
  refund: 'Refund', payee_change: 'Payee change', payee_verification: 'Payee verification', programme_account: 'Programme account',
  programme_rate: 'Programme rate', pro_payment_run: 'Payment run', pro_expense_exception: 'Expense exception',
  pro_rate_card_change: 'Rate card change', fee_payment: 'Family payment', care_payment: 'Care payment', errand_payment: 'Errand payment',
  repair_release: 'Repair release', event_payment: 'Event payment', insurance_premium: 'Insurance premium', milestone_release: 'Milestone release',
  project_release: 'Project release', dispute_decision: 'Dispute decision', offline_fee_payment: 'Offline fee payment',
  bank_account_verification: 'Bank account verification', release_rights_grant: 'Release rights', payment_rights_grant: 'Payment rights',
  locked_text_change: 'Locked text change', bulk_export: 'Bulk export', release_setting_change: 'Release setting', country_config_publish: 'Country configuration',
  country_activation: 'Country activation', role_grant: 'Role grant', legal_hold: 'Legal hold', recheck_incident: 'Re-check incident',
  feature_flag_change: 'Feature switch', setting_change: 'Setting change', partner_bank_change: 'Partner bank details',
};

/** The screen for a dedicated approval, or null when it is given on the approval detail. `escrow_cancel` and
 * `refund` may point at a release instruction; the detail page checks that first. */
export function dedicatedHref(subjectType: string, subjectId: string): string | null {
  switch (subjectType) {
    case 'report_release': return `/reports/${subjectId}`;
    case 'escrow_release': return `/escrow/releases/${subjectId}`;
    case 'escrow_cancel': return `/escrow/${subjectId}`;
    case 'payee_change': return `/payees/changes/${subjectId}`;
    case 'payee_verification': return `/payees/${subjectId}`;
    case 'programme_account':
    case 'programme_rate': return '/escrow/fx';
    case 'refund':
    case 'offline_fee_payment': return '/payments';
    case 'pro_payment_run':
    case 'pro_expense_exception':
    case 'pro_rate_card_change': return '/pay-runs';
    case 'fee_payment': return '/fees';
    case 'care_payment': return '/care';
    case 'errand_payment': return '/errands';
    case 'repair_release': return '/property';
    case 'event_payment': return '/events';
    case 'insurance_premium': return '/insurance';
    case 'milestone_release': return '/construction';
    case 'project_release': return '/projects';
    case 'dispute_decision': return '/disputes';
    default: return null;
  }
}
