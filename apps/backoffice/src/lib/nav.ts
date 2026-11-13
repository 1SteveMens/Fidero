/** Back office sections (03, 6.1d). Each module's screens live under its href. */
export type NavItem = { href: string; label: string; roles?: string[]; countKey?: string };
export type NavGroup = { label?: string; items: NavItem[] };

export const NAV: NavGroup[] = [
  {
    items: [
      { href: '/', label: 'My work', countKey: 'my_work' },
      { href: '/approvals', label: 'Approvals', countKey: 'approvals' },
    ],
  },
  {
    label: 'Property',
    items: [
      { href: '/cases', label: 'Cases' },
      { href: '/reports', label: 'Reports' },
      { href: '/geo', label: 'Maps and layers' },
      { href: '/escrow', label: 'Escrow' },
      { href: '/payees', label: 'Payees' },
      { href: '/construction', label: 'Construction' },
      { href: '/projects', label: 'Project funds' },
      { href: '/listings', label: 'Listings' },
      { href: '/property', label: 'Property management' },
      { href: '/records', label: 'Records programme' },
    ],
  },
  {
    label: 'Family',
    items: [
      { href: '/fees', label: 'Family payments' },
      { href: '/care', label: 'Care visits' },
      { href: '/errands', label: 'Errands' },
      { href: '/insurance', label: 'Insurance' },
      { href: '/events', label: 'Events' },
    ],
  },
  {
    label: 'People and money',
    items: [
      { href: '/clients', label: 'Clients and orders' },
      { href: '/payments', label: 'Fee payments' },
      { href: '/professionals', label: 'Professionals' },
      { href: '/pay-runs', label: 'Payment runs', roles: ['PY', 'RV', 'AD'] },
      { href: '/disputes', label: 'Disputes' },
      { href: '/field', label: 'Field and devices' },
    ],
  },
  {
    label: 'Control',
    items: [
      { href: '/analytics', label: 'Analytics' },
      { href: '/audit', label: 'Audit log', roles: ['RV', 'AD', 'DPO'] },
      { href: '/privacy', label: 'Data protection' },
      { href: '/partners', label: 'Partner API' },
      { href: '/admin', label: 'Admin', roles: ['AD'] },
    ],
  },
];

export const STAFF_ROLES = ['CM', 'RV', 'AD', 'AN', 'DPO', 'SUP'];
