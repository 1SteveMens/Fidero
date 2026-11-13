/**
 * The API names things by its own paths (`/cases/{id}`, `/invoices/{id}`).
 * This maps them to the client portal's pages, so a "Needs you" card or a
 * message opens the right screen.
 */
const RULES: [RegExp, string][] = [
  [/^\/cases\/([^/]+)\/(document-requests|requests)\/([^/]+)/, '/property/cases/$1#requests'],
  [/^\/cases\/([^/]+)\/tasks\/[^/]+/, '/property/cases/$1'],
  [/^\/cases\/([^/]+)/, '/property/cases/$1'],
  [/^\/orders\/([^/]+)/, '/property/orders/$1'],
  [/^\/payments\/([^/]+)\/receipt/, '/property/payments/$1'],
  [/^\/reports\/([^/]+)/, '/property/reports/$1'],
  [/^\/escrows\/[^/]+\/payee-changes\/([^/]+)/, '/property/payee-changes/$1'],
  [/^\/payee-changes\/([^/]+)/, '/property/payee-changes/$1'],
  [/^\/escrows\/([^/]+)/, '/property/escrows/$1'],
  [/^\/release-instructions\/([^/]+)/, '/property/releases/$1'],
  [/^\/disputes\/([^/]+)/, '/property/disputes/$1'],
  [/^\/listings\/([^/]+)/, '/property/listings/$1'],
  [/^\/listings$/, '/property/listings'],
  [/^\/enquiries\/([^/]+)/, '/property/enquiries/$1'],
  [/^\/reservations\/([^/]+)/, '/property/reservations/$1'],
  [/^\/partner-orders\/([^/]+)/, '/property/partner-orders/$1'],
  [/^\/assets\/([^/]+)/, '/property/assets/$1'],
  [/^\/ratings\/new\?opportunity=(.+)$/, '/property/rate?opportunity=$1'],
  [/^\/invoices\/([^/]+)/, '/family/invoices/$1'],
  [/^\/family\/invoices\/([^/]+)/, '/family/invoices/$1'],
  [/^\/fees\/payments\/([^/]+)/, '/family/fee-payments/$1'],
  [/^\/fee-payments\/([^/]+)/, '/family/fee-payments/$1'],
  [/^\/fee-schedules\/([^/]+)/, '/family/schedules/$1'],
  [/^\/institutions\/([^/]+)/, '/family/institutions/$1'],
  [/^\/care\/plans\/([^/]+)/, '/family/care/$1'],
  [/^\/care\/visits\/([^/]+)/, '/family/visits/$1'],
  [/^\/care\/concerns\/([^/]+)/, '/family/concerns/$1'],
  [/^\/errands\/([^/]+)/, '/family/errands/$1'],
  [/^\/insurance\/(applications|policies|premiums|claims|products)\/([^/]+)/, '/family/insurance/$1/$2'],
  [/^\/events\/([^/]+)/, '/family/events/$1'],
  [/^\/vendor-payments\/([^/]+)/, '/family/vendor-payments/$1'],
  [/^\/projects\/[^/]+\/payments\/([^/]+)/, '/projects/payments/$1'],
  [/^\/projects\/[^/]+\/variations\/([^/]+)/, '/projects/variations/$1'],
  [/^\/project-payments\/([^/]+)/, '/projects/payments/$1'],
  [/^\/projects\/([^/]+)/, '/projects/$1'],
  [/^\/properties\/([^/]+)/, '/projects/properties/$1'],
  [/^\/repairs\/([^/]+)/, '/projects/repairs/$1'],
  [/^\/referrals/, '/account/referral'],
  [/^\/account(\/.*)?$/, '/account$1'],
];

export function toPortal(link?: string | null): string | undefined {
  if (!link) return undefined;
  if (/^https?:/.test(link)) return link;
  for (const [re, to] of RULES) {
    if (re.test(link)) return link.replace(re, to);
  }
  return undefined;
}

/** Which tab a home item belongs to (W-25: Property, Family, Projects and errands). */
export function familyOf(line: string, kind = ''): 'property' | 'family' | 'projects' | 'account' {
  if (['fee', 'care', 'ins', 'evt', 'family', 'errands'].includes(line)) return 'family';
  if (['construction', 'funds', 'pmg'].includes(line)) return 'projects';
  if (!line && ['bank_account', 'representative', 'identity_check', 'contact_check', 'data_request'].includes(kind)) return 'account';
  if (!line) return 'account';
  return 'property';
}
