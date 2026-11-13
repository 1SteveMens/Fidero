import type { SectionSpec } from '../spec';

export const listings: SectionSpec = {
  href: '/listings',
  title: 'Listings',
  screens: 'SCR-BO-16',
  intro: 'Only checked land and buildings go live. Sellers are screened first. Suspend or remove a listing the moment a check fails; a buyer\'s reservation always needs a fresh official search.',
  resources: [
    {
      key: 'listings', label: 'Listings', list: '/v1/listings', subject: 'listing',
      columns: [
        { key: 'reference', label: 'Listing', kind: 'ref' },
        { key: 'title', label: 'Title', kind: 'name' },
        { key: 'locality', label: 'Where', kind: 'text' },
        { key: 'price', label: 'Price', kind: 'money' },
        { key: 'checks_date', label: 'Checked', kind: 'date' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status', 'q'],
      hide: ['media'],
      links: { asset_id: '/geo/assets' },
      actions: [
        { label: 'Suspend', path: '/v1/listings/{id}/suspensions', tone: 'dark', roles: ['RV', 'AD'], when: (r) => ['live', 'reserved'].includes(r.status), confirm: 'The listing leaves search at once. The seller and any buyer with a reservation are told.' },
        { label: 'Reinstate', path: '/v1/listings/{id}/reinstatements', roles: ['RV', 'AD'], when: (r) => r.status === 'suspended' },
        { label: 'Remove', path: '/v1/listings/{id}/removals', tone: 'danger', roles: ['RV', 'AD'], when: (r) => !['removed', 'sold', 'withdrawn'].includes(r.status), confirm: 'Removing the seller removes every listing they have.' },
        { label: 'Edit', path: '/v1/listings/{id}', method: 'PATCH', tone: 'ghost', when: (r) => ['draft', 'in_verification', 'rejected'].includes(r.status) },
      ],
      subs: [{ label: 'Photos and documents', from: 'media', columns: [{ key: 'kind', label: 'Kind', kind: 'text' }, { key: 'caption', label: 'Caption', kind: 'text' }, { key: 'sha256', label: 'SHA-256', kind: 'mono' }] }],
    },
    {
      key: 'verification', label: 'In verification', list: '/v1/listings', listQuery: { status: 'in_verification' }, detail: '/v1/listings/{id}', subject: 'listing',
      intro: 'Listings waiting for their checks. The check runs as a case; open it from the listing.',
      columns: [
        { key: 'reference', label: 'Listing', kind: 'ref' },
        { key: 'title', label: 'Title', kind: 'name' },
        { key: 'seller', label: 'Seller', kind: 'name' },
        { key: 'origin', label: 'From', kind: 'text' },
      ],
    },
    {
      key: 'screenings', label: 'Seller screenings', list: '/v1/seller-screenings', subject: 'seller_screening',
      intro: 'Each check passed, failed or not applicable, with evidence. A seller is established only when all apply.',
      columns: [
        { key: 'organisation_name', label: 'Seller', kind: 'name' },
        { key: 'decided_at', label: 'Decided', kind: 'date' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      title: (r) => r.organisation_name,
      create: { label: 'Open a screening', path: '/v1/seller-screenings', fields: [{ name: 'organisation_id', label: 'Seller organisation', source: { path: '/v1/organisations', label: (o) => o.name } }] },
      actions: [
        { label: 'Record a check', path: '/v1/seller-screenings/{id}/checks', tone: 'primary', when: (r) => r.status === 'in_progress', fields: [{ name: 'evidence_id', type: 'file' }] },
        { label: 'Decide', path: '/v1/seller-screenings/{id}/decisions', roles: ['RV', 'AD'], when: (r) => r.status === 'in_progress' },
      ],
    },
    {
      key: 'reservations', label: 'Reservations', list: '/v1/reservations',
      columns: [
        { key: 'reference', label: 'Reservation', kind: 'ref' },
        { key: 'listing', label: 'Listing', kind: 'name' },
        { key: 'buyer_name', label: 'Buyer', kind: 'text' },
        { key: 'fresh_search_status', label: 'Fresh search', kind: 'status' },
        { key: 'expires_at', label: 'Expires', kind: 'date' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      actions: [
        { label: 'Record failed fresh search', path: '/v1/reservations/{id}/fresh-search-results', tone: 'danger', when: (r) => r.status === 'active', confirm: 'A failed fresh search ends the reservation and suspends the listing.' },
        { label: 'Withdraw', path: '/v1/reservations/{id}/withdrawals', tone: 'ghost', when: (r) => r.status === 'active' },
      ],
    },
    {
      key: 'enquiries', label: 'Enquiries', list: '/v1/enquiries',
      columns: [
        { key: 'reference', label: 'Enquiry', kind: 'ref' },
        { key: 'buyer_name', label: 'Buyer', kind: 'name' },
        { key: 'wanted_locality', label: 'Wants', kind: 'text' },
        { key: 'budget', label: 'Budget', kind: 'money' },
        { key: 'status', label: 'Status', kind: 'status' },
      ],
      filters: ['status'],
      actions: [
        { label: 'Reply', path: '/v1/enquiries/{id}/replies', tone: 'primary', when: (r) => r.status === 'open', fields: [{ name: 'answer', type: 'textarea' }] },
        { label: 'Close', path: '/v1/enquiries/{id}/closures', tone: 'ghost', when: (r) => r.status !== 'closed' },
      ],
    },
  ],
};
