'use client';
/* Payee record: verification with the bank's name check (red only on a mismatch, FR-ESC-015), two staff approve
 * the verification, suspension and reinstatement, and payee changes through the verification flow only (RUL-28). */
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { Blocked, Button, call, Empty, ProblemBox, Skeleton, useGet, useSession } from '@tenmina/web-ui';
import { ActionForm, day, dayTime, DoneSlot, Facts, Head, MySlot, OpenSlot, Panel, useAct, words } from '@/components/core/kit';
import { NameMatch } from '@/components/core/payee';
import { IdLine } from '@/components/core/case/CaseParties';
import type { Approval, Page, Payee, PayeeChange } from '@/components/core/types';

type NatCheck = { id: string; result: string; provider_reference: string; checked_at: string | null; channel: string };

export default function PayeeDetail() {
  const { id } = useParams<{ id: string }>();
  const { client, me, hasRole } = useSession();
  const p = useGet<Payee>(`/v1/payees/${id}`);
  const appr = useGet<Page<Approval>>('/v1/approvals', { subject_type: 'payee_verification', status: 'open' });
  const changes = useGet<Page<PayeeChange>>('/v1/payee-changes', { limit: 100 });
  const nat = useGet<NatCheck>(p.data?.national_id_check ? `/v1/national-id-checks/${p.data.national_id_check}` : null, undefined, { shouldRetryOnError: false });
  const act = useAct();
  if (p.isLoading) return <Skeleton lines={8} />;
  if (!p.data) return <ProblemBox error={p.error ?? 'Payee not found.'} />;
  const x = p.data;
  const req = appr.data?.items.find((a) => a.subject_id === x.id);
  const mine = (changes.data?.items ?? []).filter((c) => c.payee === x.id || c.replaces_payee === x.id);
  const cooling = x.cooling_off_until && new Date(x.cooling_off_until) > new Date();
  const reload = () => { p.mutate(); appr.mutate(); changes.mutate(); };
  return (
    <div className="stack" style={{ gap: 18 }}>
      <Head crumb={{ href: '/payees', label: 'Payees' }} title={x.legal_name}
        chips={<><span className="chip">{words(x.kind)}</span><span className={`chip ${x.verification_status === 'verified' ? 'chip-lime' : ''}`}>{x.verification_status === 'verified' ? '✓ Verified' : words(x.verification_status)}</span><NameMatch value={x.name_match} /></>}
        actions={<>
          {hasRole('RV') && x.verification_status === 'verified' ? <ActionForm label="Suspend" path={`/v1/payees/${id}/suspensions`} fields={[{ name: 'reason', label: 'Reason', type: 'textarea', required: true }]} onDone={reload} submitLabel="Suspend" intro="No release goes to a suspended payee." /> : null}
          {hasRole('RV') && x.verification_status === 'suspended' ? <Button size="sm" variant="dark" busy={act.busy} onClick={() => act.run(() => call(client, 'POST', `/v1/payees/${id}/reinstatements`).then(reload), 'Reinstated.')}>Reinstate</Button> : null}
        </>} />
      {cooling ? <Blocked>The payee&apos;s account changed. No release to the new account until {dayTime(x.cooling_off_until)} (RUL-28).</Blocked> : null}
      {x.verification_status === 'suspended' ? <Blocked title="Suspended">{x.suspend_reason}</Blocked> : null}
      <ProblemBox error={act.error} />
      <div className="grid2">
        <Panel title="Bank account">
          <Facts items={[
            ['Legal name', x.legal_name], ['Bank', x.bank_name], ['Account name at the bank', x.account_name],
            ['Account', <span key="a" className="mono">ending {x.account_last4}</span>], ['Name source', words(x.account_name_source)],
            ['Account version', String(x.account_version)], ['Verified', day(x.verified_at)], ['Valid until', day(x.valid_until)],
          ]} />
          {x.name_match === 'mismatch' ? <p style={{ margin: 0 }}><span className="name-mismatch">The bank&apos;s account name does not match the legal name.</span> It can never be verified; money cannot go there (FR-ESC-015).</p> : null}
          <p className="muted" style={{ margin: 0, fontSize: 13 }}>🔒 Bank details have no edit control. A change goes through a payee change: fresh checks, the client&apos;s approval, two staff and a cooling-off.</p>
        </Panel>
        <Panel title="Identity" actions={hasRole('CM', 'RV', 'AD') ? (
          <ActionForm label="Edit contact" path={`/v1/payees/${id}`} method="PATCH" fields={[{ name: 'contact_email', label: 'Email', initial: x.contact_email }, { name: 'contact_phone', label: 'Phone', initial: x.contact_phone }, { name: 'national_id_check_id', label: 'National identity check ID' }]}
            body={(v) => ({ ...(v.contact_email ? { contact_email: v.contact_email } : {}), ...(v.contact_phone ? { contact_phone: v.contact_phone } : {}), ...(v.national_id_check_id ? { national_id_check_id: v.national_id_check_id } : {}) })} onDone={reload} submitLabel="Save" />
        ) : null}>
          {x.national_id_check ? <IdLine result={nat.data?.result} reference={nat.data?.provider_reference} at={nat.data?.checked_at} channel={nat.data?.channel} />
            : <p className="muted" style={{ margin: 0 }}>{x.subject_type === 'person' ? 'No national identity check yet. Payee cannot be verified until this check passes.' : 'An organisation: checked through its registration.'}</p>}
          <Facts items={[['Email', x.contact_email], ['Phone', x.contact_phone]]} />
        </Panel>
      </div>

      <Panel title="Verification">
        {x.verification_status === 'pending' && !req ? (
          <div className="stack">
            <p style={{ margin: 0 }}>First a staff member checks the evidence and prepares the verification. Then two other staff approve it.</p>
            <div><Button variant="dark" busy={act.busy} disabled={x.name_match !== 'matched'} onClick={() => act.run(() => call(client, 'POST', `/v1/payees/${id}/verifications`).then(reload), 'Prepared. Two approvals needed.')}>I checked the evidence: prepare verification</Button></div>
          </div>
        ) : null}
        {req ? (
          <div className="ground-ink stack" style={{ borderRadius: 16, padding: 14 }}>
            <div className="grid2">
              {[0, 1].map((n) => {
                const a = req.approvals[n];
                const title = `Approval ${n + 1} of 2`;
                if (a) return <DoneSlot key={n} title={title} name={a.approver_name} at={a.at} decision={a.decision} />;
                if (n === req.approvals.length && req.prepared_by !== me?.id && !req.approvals.some((y) => y.approver === me?.id)) {
                  return <MySlot key={n} title={title} confirmText="I checked the legal name, the bank's name check and the identity myself" holdLabel="Press and hold to verify"
                    onApprove={async () => { await call(client, 'POST', `/v1/payees/${id}/verification-approvals`, { decision: 'approve' }); reload(); }}
                    onReturn={async (note) => { await call(client, 'POST', `/v1/payees/${id}/verification-approvals`, { decision: 'reject', note }); reload(); }} returnLabel="Reject with a reason" />;
                }
                return <OpenSlot key={n} title={title} text={req.prepared_by === me?.id ? 'You prepared this. Two other people approve it.' : 'Waiting'} />;
              })}
            </div>
          </div>
        ) : x.verification_status === 'verified' ? <p style={{ margin: 0 }}>✓ Verified {day(x.verified_at)} by two staff.</p> : null}
      </Panel>

      <Panel title="Payee changes" actions={hasRole('CM', 'RV') ? (
        <ActionForm label="Start a payee change" path={`/v1/payees/${id}/changes`} upload={{ subject_type: 'payee', subject_id: id, role: 'account_name_evidence' }} fields={[
          { name: 'reason', label: 'Why the account changes', type: 'textarea', required: true },
          { name: 'request_source', label: 'How it was asked', type: 'select', required: true, options: [{ value: 'staff_in_person', label: 'In person, identity seen by staff' }, { value: 'payee_signed_in', label: 'Payee signed in to Tenmina' }] },
          { name: 'escrow_id', label: 'Escrow affected (ID)' },
          { name: 'bank_name', label: 'New bank', required: true }, { name: 'account_number', label: 'New account number', required: true }, { name: 'account_name', label: 'Account name' },
          { name: 'account_name_source', label: 'Name from', type: 'select', required: true, options: [{ value: 'bank_name_check', label: "The bank's name check" }, { value: 'bank_letter', label: 'A bank letter' }] },
          { name: 'account_name_evidence_id', label: 'Bank letter (if from a letter)', type: 'file' },
        ]} body={(v) => ({ kind: 'new_account', reason: v.reason, request_source: v.request_source, ...(v.escrow_id ? { escrow_id: v.escrow_id } : {}), bank_name: v.bank_name, account_number: v.account_number, account_name: v.account_name || '', account_name_source: v.account_name_source, ...(v.account_name_evidence_id ? { account_name_evidence_id: v.account_name_evidence_id } : {}) })}
          onDone={(out) => { const c = out as { id?: string }; if (c?.id) window.location.href = `/payees/changes/${c.id}`; }} submitLabel="Start change"
          intro="A request that arrived only by message, email or call cannot be entered here. Do not act on it; warn the client on a second channel." />
      ) : null}>
        {changes.isLoading ? <Skeleton /> : mine.length ? (
          <div className="rows">
            {mine.map((c) => (
              <Link key={c.id} href={`/payees/changes/${c.id}`} className="rowlink">
                <div className="main"><div className="title">..{c.previous_last4 || '—'} → {c.bank_name} ..{c.account_last4}</div><div className="meta">{c.reason} · {day(c.requested_at)}</div></div>
                <span className="chip">{words(c.status)}</span>
              </Link>
            ))}
          </div>
        ) : <Empty>No changes.</Empty>}
      </Panel>
      {act.toast}
    </div>
  );
}
