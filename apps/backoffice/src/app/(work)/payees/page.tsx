'use client';
/* Payees: the registry of verified institutions, suppliers, vendors and professionals (RUL-22), payee change
 * approvals oldest first (SCR-BO-42), and identity checks (SCR-BO-44): national identity checks and the manual
 * document check queue for clients. */
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useState } from 'react';
import { Empty, Field, Input, ProblemBox, Select, Skeleton, Tabs, useGet, useSession } from '@tenmina/web-ui';
import { ActionForm, day, dayTime, Head, words } from '@/components/core/kit';
import { IdLine } from '@/components/core/case/CaseParties';
import { NameMatch } from '@/components/core/payee';
import type { Page, Payee, PayeeChange } from '@/components/core/types';

const KINDS = ['institution', 'supplier', 'vendor', 'professional', 'contractor', 'agency', 'insurer', 'carer', 'seller', 'developer', 'client_own_account'];
type NatCheck = { id: string; country: string; subject_role: string; subject_name: string; id_number: string; channel: string; adapter: string; requested_at: string; result: string; provider_reference: string; checked_at: string | null; attempts: number; context_type: string; context_id: string | null };
type IdCheck = { id: string; person: { id: string; full_name?: string; name?: string } | null; method: string; provider: string; provider_reference: string; provider_result: string; document_type: string; document_number: string; status: string; reviewed_at: string | null; notes: string; created_at: string };

const DRAFT_ID = '00000000-0000-0000-0000-000000000000';

function NewPayee({ onDone }: { onDone: () => void }) {
  const { hasRole } = useSession();
  if (!hasRole('CM', 'RV')) return null;
  return (
    <ActionForm label="+ New payee" variant="dark" path="/v1/payees" upload={{ subject_type: 'payee', subject_id: DRAFT_ID, country: 'GH' }} fields={[
      { name: 'kind', label: 'Kind', type: 'select', required: true, options: KINDS.filter((k) => k !== 'client_own_account').map((k) => ({ value: k, label: words(k) })) },
      { name: 'subject_type', label: 'Who it is in Tenmina', type: 'select', required: true, options: ['institution', 'supplier', 'panel_member', 'organisation', 'person', 'partner'].map((k) => ({ value: k, label: words(k) })) },
      { name: 'subject_id', label: 'Their record ID', required: true },
      { name: 'legal_name', label: 'Legal name', required: true }, { name: 'legal_name_evidence_id', label: 'Registration or ID record', type: 'file', required: true },
      { name: 'bank_name', label: 'Bank', required: true }, { name: 'account_number', label: 'Account number', required: true },
      { name: 'account_name_source', label: 'Account name from', type: 'select', required: true, options: [{ value: 'bank_name_check', label: "The bank's name check" }, { value: 'bank_letter', label: 'A bank letter' }] },
      { name: 'account_name', label: 'Account name (from a bank letter)' }, { name: 'account_name_evidence_id', label: 'Bank letter', type: 'file' },
      { name: 'contact_email', label: 'Email' }, { name: 'contact_phone', label: 'Phone' },
    ]} body={(v) => ({ country: 'GH', kind: v.kind, subject_type: v.subject_type, subject_id: v.subject_id, legal_name: v.legal_name, legal_name_evidence_id: v.legal_name_evidence_id, bank_name: v.bank_name, account_number: v.account_number, account_name: v.account_name || '', account_name_source: v.account_name_source, ...(v.account_name_evidence_id ? { account_name_evidence_id: v.account_name_evidence_id } : {}), contact_email: v.contact_email || '', contact_phone: v.contact_phone || '' })}
      onDone={(out) => { onDone(); const p = out as { id?: string }; if (p?.id) window.location.href = `/payees/${p.id}`; }} submitLabel="Add payee" intro="A payee is verified only when the bank's account name matches the legal name and two staff approve." />
  );
}

function Registry() {
  const [kind, setKind] = useState('');
  const [status, setStatus] = useState('');
  const [q, setQ] = useState('');
  const list = useGet<Page<Payee>>('/v1/payees', { limit: 100, ...(kind ? { kind } : {}), ...(status ? { verification_status: status } : {}) });
  const needle = q.trim().toLowerCase();
  const rows = (list.data?.items ?? []).filter((p) => !needle || `${p.legal_name} ${p.account_name} ${p.bank_name}`.toLowerCase().includes(needle));
  return (
    <div className="stack">
      <div className="filters">
        <Field label="Kind"><Select value={kind} onChange={(e) => setKind(e.target.value)}><option value="">All</option>{KINDS.map((k) => <option key={k} value={k}>{words(k)}</option>)}</Select></Field>
        <Field label="Status"><Select value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All</option>{['pending', 'verified', 'suspended', 'revoked'].map((k) => <option key={k} value={k}>{words(k)}</option>)}</Select></Field>
        <Field label="Search"><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name or bank" /></Field>
        <NewPayee onDone={() => list.mutate()} />
      </div>
      <ProblemBox error={list.error} />
      {list.isLoading ? <Skeleton lines={6} /> : rows.length ? (
        <div className="rows">
          {rows.map((p) => (
            <Link key={p.id} href={`/payees/${p.id}`} className="rowlink">
              <div className="main">
                <div className="label">{words(p.kind)}</div>
                <div className="title">{p.legal_name}</div>
                <div className="meta">{p.bank_name} · account ending <span className="mono">{p.account_last4}</span>{p.cooling_off_until && new Date(p.cooling_off_until) > new Date() ? ` · cooling-off until ${dayTime(p.cooling_off_until)}` : ''}</div>
              </div>
              <div className="row" style={{ gap: 6 }}>
                <NameMatch value={p.name_match} />
                <span className={`chip ${p.verification_status === 'verified' ? 'chip-lime' : ''}`}>{p.verification_status === 'verified' ? '✓ Verified' : words(p.verification_status)}</span>
              </div>
            </Link>
          ))}
        </div>
      ) : <Empty>No payees match.</Empty>}
    </div>
  );
}

function Changes() {
  const [status, setStatus] = useState('');
  const list = useGet<Page<PayeeChange>>('/v1/payee-changes', { limit: 100, ...(status ? { status } : {}) });
  const rows = [...(list.data?.items ?? [])].sort((a, b) => a.requested_at.localeCompare(b.requested_at));
  return (
    <div className="stack">
      <div className="strip-ink"><span aria-hidden>🔒</span>We never change who gets paid because of a message, email or call. Start the payee verification flow and warn the client on a second channel.</div>
      <div className="filters">
        <Field label="Status"><Select value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All</option>{['requested', 'checks_passed', 'client_approved', 'pending_approval', 'applied', 'stopped', 'rejected', 'withdrawn'].map((k) => <option key={k} value={k}>{words(k)}</option>)}</Select></Field>
      </div>
      <ProblemBox error={list.error} />
      {list.isLoading ? <Skeleton lines={4} /> : rows.length ? (
        <div className="rows">
          {rows.map((c) => {
            const cooling = c.cooling_off_until && new Date(c.cooling_off_until) > new Date() && c.status === 'applied';
            return (
              <Link key={c.id} href={`/payees/changes/${c.id}`} className="rowlink">
                <div className="main">
                  <div className="label">{words(c.kind)} · asked {day(c.requested_at)} · {words(c.request_source)}</div>
                  <div className="title">{c.kind === 'refund_destination' ? 'Refund to another account' : `..${c.previous_last4 || '—'} → ${c.bank_name} ..${c.account_last4}`}</div>
                  <div className="meta">{c.reason}</div>
                </div>
                {cooling ? <span className="chip chip-ink">🔒 Cooling-off to {dayTime(c.cooling_off_until)}</span> : <span className="chip">{words(c.status)}</span>}
              </Link>
            );
          })}
        </div>
      ) : <Empty>No payee changes.</Empty>}
    </div>
  );
}

function Identity() {
  const { hasRole } = useSession();
  const nat = useGet<Page<NatCheck>>('/v1/national-id-checks', { limit: 100 });
  const manual = useGet<Page<IdCheck>>('/v1/identity-checks', { status: 'pending' });
  return (
    <div className="stack" style={{ gap: 16 }}>
      <section className="stack" aria-label="National identity checks">
        <div className="spread">
          <h2 style={{ margin: 0, fontSize: 18 }}>National identity checks</h2>
          {hasRole('CM', 'RV') ? (
            <ActionForm label="+ Run a check" path="/v1/national-id-checks" fields={[
              { name: 'subject_role', label: 'Who', type: 'select', required: true, options: ['seller', 'grantor', 'consenting_party', 'signatory', 'payee', 'client'].map((x) => ({ value: x, label: words(x) })) },
              { name: 'subject_name', label: 'Name', required: true }, { name: 'id_number', label: 'National ID number', required: true },
              { name: 'adapter', label: 'How', type: 'select', initial: 'api', options: [{ value: 'api', label: 'Through the service' }, { value: 'staff_portal', label: 'Staff portal' }] },
            ]} onDone={() => nat.mutate()} submitLabel="Check" intro="Result, reference and time only. Never a photo of the card; no biometric data (RUL-31)." />
          ) : null}
        </div>
        <ProblemBox error={nat.error} />
        {nat.isLoading ? <Skeleton /> : nat.data?.items.length ? (
          <div className="rows">
            {nat.data.items.map((c) => (
              <div key={c.id} className="rowlink">
                <div className="main">
                  <div className="label">{words(c.subject_role)} · {words(c.adapter)} · asked {dayTime(c.requested_at)}</div>
                  <div className="title">{c.subject_name} <span className="mono muted" style={{ fontSize: 12 }}>{c.id_number}</span></div>
                  <IdLine result={c.result} reference={c.provider_reference} at={c.checked_at} channel={c.channel} />
                </div>
                <div className="row" style={{ gap: 6 }}>
                  {['pending', 'unavailable'].includes(c.result) && c.adapter === 'staff_portal' ? (
                    <ActionForm label="Record portal result" variant="dark" path={`/v1/national-id-checks/${c.id}/staff-result`} fields={[
                      { name: 'id_number', label: 'ID number checked', required: true },
                      { name: 'result', label: 'Result', type: 'select', required: true, options: [{ value: 'match', label: 'Match' }, { value: 'no_match', label: 'No match' }, { value: 'not_found', label: 'Not found' }] },
                      { name: 'provider_reference', label: "The system's reference", required: true }, { name: 'returned_name', label: 'Name the system returned' },
                    ]} onDone={() => nat.mutate()} submitLabel="Save" />
                  ) : null}
                  {['pending', 'unavailable'].includes(c.result) && c.adapter === 'api' ? <ActionForm label="Try again" path={`/v1/national-id-checks/${c.id}/retry`} onDone={() => nat.mutate()} submitLabel="Try again" /> : null}
                </div>
              </div>
            ))}
          </div>
        ) : <Empty>No national identity checks.</Empty>}
      </section>
      <section className="stack" aria-label="Manual checks">
        <h2 style={{ margin: 0, fontSize: 18 }}>Client document checks waiting</h2>
        <p className="muted" style={{ margin: 0, fontSize: 14 }}>For clients whose provider check could not finish. Party and payee checks never use this route.</p>
        <ProblemBox error={manual.error} />
        {manual.isLoading ? <Skeleton /> : manual.data?.items.length ? (
          <div className="rows">
            {manual.data.items.map((c) => (
              <div key={c.id} className="rowlink">
                <div className="main"><div className="title">{c.person?.full_name ?? c.person?.name ?? 'Client'}</div><div className="meta">{words(c.document_type)} {c.document_number} · {words(c.method)} · {dayTime(c.created_at)}</div></div>
                <ActionForm label="Decide" variant="dark" path={`/v1/identity-checks/${c.id}/manual-decision`} fields={[
                  { name: 'document_type', label: 'Document', initial: c.document_type, required: true }, { name: 'document_number', label: 'Number', initial: '', required: true },
                  { name: 'outcome', label: 'Outcome', type: 'select', required: true, options: [{ value: 'passed', label: 'Passed' }, { value: 'failed', label: 'Failed' }] }, { name: 'notes', label: 'Notes', type: 'textarea' },
                ]} onDone={() => manual.mutate()} submitLabel="Save" />
              </div>
            ))}
          </div>
        ) : <Empty>No manual checks waiting.</Empty>}
      </section>
    </div>
  );
}

function PayeesHome() {
  const sp = useSearchParams();
  const router = useRouter();
  const tab = sp.get('tab') ?? 'registry';
  return (
    <div className="stack" style={{ gap: 18 }}>
      <Head title="Payees" sub="Money goes only to a verified institution, supplier, vendor or professional. Never as cash to a relative." />
      <div className="tabs-scroll"><Tabs items={[{ key: 'registry', label: 'Registry' }, { key: 'changes', label: 'Payee changes' }, { key: 'identity', label: 'Identity checks' }]} current={tab} onChange={(k) => router.replace(`/payees?tab=${k}`)} /></div>
      {tab === 'registry' ? <Registry /> : tab === 'changes' ? <Changes /> : <Identity />}
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<Skeleton />}><PayeesHome /></Suspense>;
}
