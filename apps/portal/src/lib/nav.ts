/** Portal sections (03, information architecture): the same tabs as the client app. */
export const TABS = [
  { href: '/', label: 'Home' },
  { href: '/property', label: 'Property' },
  { href: '/family', label: 'Family' },
  { href: '/projects', label: 'Projects' },
  { href: '/account', label: 'Account' },
];
/** Pages for professionals, sellers, institutions, partners and others who use the portal (DA-13). */
export const ROLE_HOME: Record<string, string> = {
  LW: '/work', SV: '/work', RN: '/work', IN: '/work', QS: '/work', CE: '/work',
  SE: '/seller', DV: '/seller', CT: '/contractor', IC: '/institution', PT: '/partner', IS: '/insurer',
  FM: '/family-member', TN: '/tenant', AR: '/authority',
};
