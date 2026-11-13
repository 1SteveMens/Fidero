/** Role sections of the portal (DA-13 and 01 C2): who may open each, and the tabs they see. */
export type Tab = { href: string; label: string; roles?: string[] };
export type RoleSection = { prefix: string; name: string; roles: string[]; tabs: Tab[] };

export const PRO_ROLES = ['LW', 'SV', 'RN', 'IN', 'QS', 'CE'];

export const SECTIONS: RoleSection[] = [
  {
    prefix: '/work', name: 'My work', roles: PRO_ROLES,
    tabs: [
      { href: '/work', label: 'Today' },
      { href: '/work/tasks', label: 'Tasks', roles: ['LW', 'SV', 'RN', 'IN', 'QS'] },
      { href: '/work/reports', label: 'Reports', roles: ['LW', 'SV'] },
      { href: '/work/field', label: 'Visits', roles: ['IN', 'QS', 'CE', 'RN', 'SV'] },
      { href: '/work/pay', label: 'My pay' },
    ],
  },
  {
    prefix: '/seller', name: 'Selling', roles: ['SE', 'DV'],
    tabs: [
      { href: '/seller', label: 'Home' },
      { href: '/seller/listings', label: 'Listings' },
      { href: '/seller/enquiries', label: 'Enquiries' },
      { href: '/seller/invoices', label: 'Invoices' },
      { href: '/seller/organisation', label: 'Team' },
    ],
  },
  {
    prefix: '/contractor', name: 'Building', roles: ['CT'],
    tabs: [
      { href: '/contractor', label: 'Projects' },
      { href: '/contractor/defects', label: 'Defects' },
      { href: '/contractor/payments', label: 'Payments' },
      { href: '/contractor/repairs', label: 'Repairs' },
      { href: '/contractor/ratings', label: 'Ratings' },
    ],
  },
  {
    prefix: '/institution', name: 'Institution', roles: ['IC'],
    tabs: [
      { href: '/institution', label: 'Bills' },
      { href: '/institution/payments', label: 'Payments' },
      { href: '/institution/profile', label: 'Our record' },
    ],
  },
  {
    prefix: '/insurer', name: 'Insurer', roles: ['IS'],
    tabs: [
      { href: '/insurer', label: 'Applications' },
      { href: '/insurer/policies', label: 'Policies' },
      { href: '/insurer/premiums', label: 'Premiums' },
      { href: '/insurer/claims', label: 'Claims' },
      { href: '/insurer/products', label: 'Products' },
    ],
  },
  {
    prefix: '/partner', name: 'Partner', roles: ['PT'],
    tabs: [
      { href: '/partner', label: 'Plot status' },
      { href: '/partner/orders', label: 'Orders' },
      { href: '/partner/usage', label: 'Usage' },
    ],
  },
  {
    prefix: '/family-member', name: 'Confirm', roles: ['FM'],
    tabs: [{ href: '/family-member', label: 'Confirm' }],
  },
  {
    prefix: '/tenant', name: 'My home', roles: ['TN'],
    tabs: [
      { href: '/tenant', label: 'Tenancy' },
      { href: '/tenant/repairs', label: 'Repairs' },
    ],
  },
  {
    prefix: '/authority', name: 'Records', roles: ['AR'],
    tabs: [
      { href: '/authority', label: 'Records' },
      { href: '/authority/listings', label: 'Listings' },
    ],
  },
];

export function sectionFor(path: string): RoleSection | undefined {
  return SECTIONS.find((s) => path === s.prefix || path.startsWith(s.prefix + '/'));
}

export function tabsFor(section: RoleSection, roles: string[]): Tab[] {
  return section.tabs.filter((t) => !t.roles || t.roles.some((r) => roles.includes(r)));
}
