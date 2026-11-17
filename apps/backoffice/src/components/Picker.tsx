'use client';
/* Searchable picker for forms that ask for a person or another record (03, 6.1d).
 * Staff type two or more letters of a name or reference and choose from the list,
 * instead of pasting an ID. People come from GET /v1/people?search= (staff only,
 * scoped to their countries, emails masked); other records from each module's own
 * list with ?search=. A full ID can still be pasted when a list is not open to you. */
import React, { useEffect, useId, useRef, useState } from 'react';
import { ApiError } from '@tenmina/api-client';
import { call, useSession } from '@tenmina/web-ui';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Row = Record<string, any>;

export type PickKind = 'person' | 'payee' | 'report' | 'case' | 'institution' | 'carer' | 'agent' | 'organisation' | 'partner' | 'insurer' | 'panel';
export type PickSpec = PickKind | { kind: PickKind; query?: Record<string, string> };

const words = (s: unknown) => String(s ?? '').replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());
const join = (...xs: unknown[]) => xs.filter((x) => x !== null && x !== undefined && x !== '').map(String).join(' · ');
const nameOf = (v: unknown) => (v && typeof v === 'object' ? (v as Row).full_name ?? (v as Row).name ?? '' : '');

const KINDS: Record<PickKind, { path: string; noun: string; label: (r: Row) => string; sub: (r: Row) => string }> = {
  person: { path: '/v1/people', noun: 'person', label: (r) => r.full_name, sub: (r) => join((r.roles ?? []).join(' '), r.email_masked) },
  payee: {
    path: '/v1/payees', noun: 'payee', label: (r) => r.legal_name,
    sub: (r) => join(words(r.kind), r.bank_name && r.account_last4 ? `${r.bank_name} ending ${r.account_last4}` : '', words(r.verification_status)),
  },
  report: { path: '/v1/reports', noun: 'report', label: (r) => r.reference, sub: (r) => join(words(r.status), r.case_reference ? `case ${r.case_reference}` : '') },
  case: { path: '/v1/cases', noun: 'case', label: (r) => r.reference, sub: (r) => join(r.title, nameOf(r.client), words(r.status)) },
  institution: { path: '/v1/institutions', noun: 'institution', label: (r) => r.legal_name, sub: (r) => join(words(r.type), r.country, words(r.status)) },
  carer: { path: '/v1/carers', noun: 'carer', label: (r) => nameOf(r.person) || 'Carer', sub: (r) => join(r.areas, words(r.status)) },
  agent: { path: '/v1/errand-agents', noun: 'agent', label: (r) => r.name ?? nameOf(r.person), sub: (r) => words(r.status) },
  organisation: { path: '/v1/organisations', noun: 'organisation', label: (r) => r.name, sub: (r) => join(words(r.kind), r.country, r.registration_number) },
  partner: { path: '/v1/admin/partners', noun: 'partner', label: (r) => r.name, sub: (r) => join(words(r.kind), r.country, words(r.status)) },
  insurer: { path: '/v1/insurance/insurers', noun: 'insurer', label: (r) => r.name, sub: (r) => join(r.licence_number, words(r.status)) },
  panel: { path: '/v1/panel-members', noun: 'panel member', label: (r) => r.name, sub: (r) => join(words(r.kind), r.registration_number, words(r.status)) },
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Which picker a form field takes, from its name and the endpoint it is sent to. */
export function pickFor(name: string, path = ''): PickSpec | undefined {
  const construction = /^\/v1\/(projects|milestones|inspections)\//.test(path) || path === '/v1/projects';
  if (construction) {
    if (name === 'contractor_id') return { kind: 'panel', query: { kind: 'contractor', status: 'active' } };
    if (name === 'inspector_id') return { kind: 'panel', query: { kind: 'inspector', status: 'active' } };
    if (name === 'member_id') {
      const kind = /quantity-surveyor/.test(path) ? 'quantity_surveyor' : /inspector/.test(path) ? 'inspector' : 'contractor';
      return { kind: 'panel', query: { kind, status: 'active' } };
    }
  }
  if (name === 'inspector_id') return { kind: 'person', query: { role: 'IN' } };
  if (name === 'runner_id') return { kind: 'person', query: { role: 'RN' } };
  if (name === 'contractor_id') return /^\/v1\/repairs\//.test(path) ? { kind: 'panel', query: { kind: 'contractor', status: 'active' } } : 'person';
  if (['person', 'person_id', 'client_id', 'owner', 'owner_id', 'recipient_person', 'receiver_person_id', 'contact_person_id', 'bill_to_person',
    'signatory_person_id', 'professional_id', 'assignee_id', 'second_assignee_id', 'on_behalf_of'].includes(name)) return 'person';
  if (name === 'subject' && /^\/v1\/(dpr|admin\/rights)/.test(path)) return 'person';
  if (['payee_id', 'new_payee_id', 'agency_payee_id', 'supplier_payee_id'].includes(name)) return { kind: 'payee', query: { verification_status: 'verified' } };
  if (name === 'report_id') return 'report';
  if (name === 'case_id') return 'case';
  if (name === 'institution_id') return 'institution';
  if (name === 'carer_id' || name === 'replacement_id') return { kind: 'carer', query: { status: 'active' } };
  if (name === 'agent_id') return { kind: 'agent', query: { status: 'active' } };
  if (['organisation', 'organisation_id', 'agency_org_id', 'for_organisation_id'].includes(name)) return 'organisation';
  if (['partner_id', 'bank_partner_id', 'registry_partner_id', 'provider_partner_id', 'transfer_partner_id', 'source_partner_id'].includes(name)) return 'partner';
  if (name === 'insurer_id') return 'insurer';
  return undefined;
}

export function Picker({ spec, value, onChange, required, label, placeholder }: {
  spec: PickSpec; value: string; onChange: (id: string) => void; required?: boolean; label?: string; placeholder?: string;
}) {
  const { kind, query } = typeof spec === 'string' ? { kind: spec, query: undefined } : spec;
  const k = KINDS[kind];
  const { client } = useSession();
  const [text, setText] = useState('');
  const [rows, setRows] = useState<Row[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [chosen, setChosen] = useState<Row | null>(null);
  const listId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const q = text.trim();
  const pasted = UUID.test(q) ? q : null;

  useEffect(() => {
    if (q.length < 2 || pasted) { setRows(null); return; }
    let live = true;
    setBusy(true);
    const t = setTimeout(() => {
      call<Row>(client, 'GET', k.path, undefined, { ...(query ?? {}), search: q })
        .then((d) => { if (live) { setRows((Array.isArray(d) ? d : (d.items as Row[]) ?? []).slice(0, 10)); setRefused(null); setActive(0); } })
        .catch((e) => {
          if (!live) return;
          setRows([]);
          setRefused(e instanceof ApiError && e.problem.status === 403 ? `You cannot search ${k.noun}s here. Paste the ${k.noun}'s ID instead.` : 'The search did not work. Try again, or paste the ID.');
        })
        .finally(() => live && setBusy(false));
    }, 250);
    return () => { live = false; clearTimeout(t); };
  }, [q, pasted, client, k.path, JSON.stringify(query)]); // eslint-disable-line react-hooks/exhaustive-deps

  const options: { id: string; label: string; sub: string; row?: Row }[] = pasted
    ? [{ id: pasted, label: `Use the ID ${pasted.slice(0, 8)}…`, sub: 'Pasted ID' }]
    : (rows ?? []).map((r) => ({ id: String(r.id), label: k.label(r) || String(r.id).slice(0, 8), sub: k.sub(r), row: r }));

  const choose = (o: (typeof options)[number]) => {
    onChange(o.id);
    setChosen(o.row ?? { id: o.id });
    setText('');
    setOpen(false);
  };

  if (value) {
    const lab = chosen && chosen.id === value && chosen !== null && Object.keys(chosen).length > 1 ? k.label(chosen) : `ID ${value.slice(0, 8)}…`;
    const sub = chosen && chosen.id === value && Object.keys(chosen).length > 1 ? k.sub(chosen) : '';
    return (
      <div className="picker-chosen" aria-live="polite">
        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 700, overflowWrap: 'anywhere' }}>{lab}</div>
          {sub ? <div className="muted" style={{ fontSize: 13 }}>{sub}</div> : null}
        </div>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => { onChange(''); setChosen(null); setTimeout(() => inputRef.current?.focus(), 0); }} aria-label={`Change ${label ?? k.noun}`}>Change</button>
      </div>
    );
  }

  const showList = open && (q.length >= 2);
  return (
    <div className="picker">
      <input
        ref={inputRef}
        className="input"
        type="search"
        role="combobox"
        aria-expanded={showList}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={showList && options[active] ? `${listId}-${active}` : undefined}
        aria-label={label}
        placeholder={placeholder ?? `Search by name${kind === 'person' ? ', email or phone' : ' or reference'}`}
        value={text}
        required={required}
        autoComplete="off"
        onChange={(e) => { setText(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); setActive((a) => Math.min(a + 1, options.length - 1)); }
          else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
          else if (e.key === 'Enter' && showList && options[active]) { e.preventDefault(); choose(options[active]); }
          else if (e.key === 'Escape') setOpen(false);
        }}
      />
      {showList ? (
        <ul id={listId} role="listbox" className="picker-list" aria-label={`Matching ${k.noun}s`}>
          {busy && !pasted ? <li className="picker-note" aria-live="polite">Searching…</li> : null}
          {!busy && refused ? <li className="picker-note">{refused}</li> : null}
          {!busy && !refused && !options.length ? <li className="picker-note">No {k.noun} matches “{q}”.</li> : null}
          {options.map((o, i) => (
            <li
              key={o.id}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              className="picker-option"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => choose(o)}
              onMouseEnter={() => setActive(i)}
            >
              <span style={{ fontWeight: 700 }}>{o.label}</span>
              {o.sub ? <span className="muted" style={{ fontSize: 13 }}>{o.sub}</span> : null}
            </li>
          ))}
        </ul>
      ) : q.length === 1 ? <small className="muted">Type at least 2 characters.</small> : null}
    </div>
  );
}
