'use client';
/* Payee change approval · SCR-BO-42 · W-43 (FR-ESC-016, RUL-28). One sentence of who changes from which account to
 * which; the evidence ticked in lime; the client's approval first; two staff slots with the second factor; the
 * cooling-off countdown with its end time and the "Release blocked" banner. No override of the cooling-off. */
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Blocked, Button, call, ProblemBox, Skeleton, Ticket, useGet, useSession } from '@tenmina/web-ui';
import { ActionForm, dayTime, DoneSlot, Gate, MySlot, OpenSlot, useAct, words } from '@/components/core/kit';
import { idState } from '@/components/core/case/CaseParties';
import type { Approval, Payee, PayeeChange } from '@/components/core/types';

type NatCheck = { id: string; result: string; provider_reference: string; checked_at: string | null };

function left(until: string): string {
  const ms = new Date(until).getTime() - Date.now();
  if (ms <= 0) return 'ended';
  const d = Math.floor(ms / 86400000);
  const h = Math.floor((ms % 86400000) / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  return d ? `${d} d ${h} h left` : `${h} h ${m} min left`;
}

export default function PayeeChangeView() {
  const { id } = useParams<{ id: string }>();
  const { client, me, hasRole } = useSession();
  const ch = useGet<PayeeChange>(`/v1/payee-changes/${id}`);
  const x = ch.data;
  const payee = useGet<Payee>(x?.payee ? `/v1/payees/${x.payee}` : null);
  const req = useGet<Approval>(x?.approval_request ? `/v1/approvals/${x.approval_request}` : null);
  const nat = useGet<NatCheck>(x?.national_id_check ? `/v1/national-id-checks/${x.national_id_check}` : null, undefined, { shouldRetryOnError: false });
  const act = useAct();
  const [, tick] = useState(0);
  useEffect(() => { const t = setInterval(() => tick((n) => n + 1), 60000); return () => clearInterval(t); }, []);
  if (ch.isLoading) return <Skeleton lines={8} />;
  if (!x) return <ProblemBox error={ch.error ?? 'Change not found.'} />;
  const reload = () => { ch.mutate(); req.mutate(); nat.mutate(); };
  const refund = x.kind === 'refund_destination';
  const cooling = x.status === 'applied' && x.cooling_off_until && new Date(x.cooling_off_until) > new Date();
  const closed = ['stopped', 'rejected', 'withdrawn'].includes(x.status);
  const idOk = nat.data?.result === 'match';
  const nameOk = x.account_name_source === 'bank_name_check' || !!x.account_checked_by;
  const iPrepared = x.requested_by === me?.id;
  const staffOpen = x.status === 'pending_approval' || (x.status === 'client_approved' && !!req.data);
  const approvals = req.data?.approvals ?? [];
  const who = payee.data?.legal_name ?? (refund ? 'the client' : 'the payee');

  return (
    <div className="ground-ink stack" style={{ gap: 18, borderRadius: 24, padding: 'clamp(16px, 3vw, 28px)' }}>
      <header className="stack" style={{ gap: 8 }}>
        <Link href="/payees?tab=changes" className="label" style={{ textDecoration: 'none' }}>← Payee changes</Link>
        <div className="label">Payee change · {words(x.kind)}{x.escrow ? <> · <Link href={`/escrow/${x.escrow}`} style={{ color: 'inherit' }}>escrow</Link></> : null}</div>
        <div className="row" style={{ gap: 8 }}><span className="chip chip-ink" style={{ background: '#242424' }}>{cooling ? 'Cooling-off' : words(x.status)}</span></div>
      </header>
      {cooling ? <Blocked>Release blocked to the new account until {dayTime(x.cooling_off_until)} ({left(x.cooling_off_until!)}). Shown on every affected escrow. No override.</Blocked> : null}
      {x.status === 'stopped' ? <Blocked title="Stopped">{x.stop_reason} The payee is suspended for review.</Blocked> : null}

      <Ticket top={<>
        <div className="label">{refund ? 'Refund destination' : 'Change'}</div>
        <div style={{ fontSize: 20, fontWeight: 800 }}>{who}</div>
      </>} bottom={<div style={{ fontSize: 16 }}>
        {refund ? 'Refund to ' : <>From account ending <span className="mono">{x.previous_last4 || '—'}</span>{x.previous_account_name ? ` (${x.previous_account_name})` : ''} to </>}
        <strong>{x.bank_name}</strong>, account ending <span className="mono">{x.account_last4}</span>{x.account_name ? <>, name <strong>{x.account_name}</strong></> : null}.
        <div className="muted" style={{ fontSize: 14, marginTop: 6 }}>Asked {dayTime(x.requested_at)} · {words(x.request_source).toLowerCase()} · {x.reason}</div>
        {payee.data && payee.data.name_match === 'mismatch' ? <div style={{ marginTop: 8 }}><span className="name-mismatch">Bank name check: not matched</span></div> : null}
      </div>} />

      <section className="stack" style={{ gap: 0 }} aria-label="Evidence">
        <div className="label" style={{ marginBottom: 4 }}>Evidence · all must pass</div>
        <Gate ok={idOk} title={`Identity of ${refund ? 'the client' : 'the new payee'}: ${idState(nat.data?.result).text}`} detail={nat.data?.provider_reference ? `National identity system, ref ${nat.data.provider_reference}, ${dayTime(nat.data.checked_at)}` : undefined} rule="RUL-31" />
        <Gate ok={nameOk} title={x.account_name_source === 'bank_name_check' ? `Account name from the bank's name check: ${x.account_name || '—'}` : x.account_checked_by ? 'Bank letter checked by a second person' : 'Bank letter not checked by a second person yet'} rule="FR-ESC-015" />
        <Gate ok title="Client told on a second channel" detail="Sent automatically when the change was started." />
        <Gate ok={!!x.client_approved_at} title={x.client_approved_at ? `Client approved, code verified, ${dayTime(x.client_approved_at)}` : 'Waiting for the client. Staff approvals open after the client approves.'} rule="RUL-11" />
      </section>

      {!closed && x.status === 'requested' && hasRole('CM', 'RV') ? (
        <div className="row">
          {!idOk ? <ActionForm label="Run the identity check" variant="primary" path={`/v1/payee-changes/${id}/identity-check`} fields={[{ name: 'subject_name', label: 'Name', initial: who }, { name: 'id_number', label: 'National ID number', required: true }]} onDone={reload} submitLabel="Check" intro="Never a photo of the card (RUL-31)." /> : null}
          {!nameOk ? <Button variant="primary" size="sm" busy={act.busy} onClick={() => act.run(() => call(client, 'POST', `/v1/payee-changes/${id}/account-check`).then(reload), 'Account checked.')}>I checked the bank letter</Button> : null}
        </div>
      ) : null}

      <div className="grid2">
        {[0, 1].map((n) => {
          const a = approvals[n];
          const title = `Approval ${n + 1} of 2`;
          if (a) return <DoneSlot key={n} title={title} name={a.approver_name} at={a.at} decision={a.decision} />;
          if (staffOpen && n === approvals.length) {
            if (iPrepared) return <OpenSlot key={n} title={title} text="You started this change. You cannot approve it." />;
            if (approvals.some((y) => y.approver === me?.id)) return <OpenSlot key={n} title={title} text="A different person must give approval 2 (RUL-05)." />;
            if (!hasRole('RR')) return <OpenSlot key={n} title={title} text="Waiting for a reviewer with release rights." />;
            return <MySlot key={n} title={title} confirmText="I checked the identity and the account name myself" holdLabel="Press and hold to approve the change"
              onApprove={async () => { await call(client, 'POST', `/v1/payee-changes/${id}/approvals`, { decision: 'approve' }); reload(); }}
              onReturn={async (note) => { await call(client, 'POST', `/v1/payee-changes/${id}/approvals`, { decision: 'reject', note }); reload(); }} returnLabel="Reject with a reason" />;
          }
          return <OpenSlot key={n} title={title} text={x.client_approved_at ? 'Waiting' : 'Opens after the client approves.'} />;
        })}
      </div>
      <div style={{ fontSize: 14, opacity: 0.85 }}>Then: the cooling-off runs to its end time. Releases to the new account follow the usual gates. The client can stop it during the cooling-off.</div>

      <div className="row">
        {cooling && hasRole('RV') ? <ActionForm label="Stop this change" path={`/v1/payee-changes/${id}/stop`} fields={[{ name: 'reason', label: 'Why (e.g. it looks like fraud)', type: 'textarea', required: true }]} onDone={reload} submitLabel="Stop" intro="The old account is kept and the payee is suspended for review." /> : null}
        {!closed && x.status !== 'applied' && (iPrepared || hasRole('RV')) ? <Button size="sm" variant="ghost" style={{ color: '#fff' }} busy={act.busy} onClick={() => act.run(() => call(client, 'POST', `/v1/payee-changes/${id}/withdraw`).then(reload), 'Withdrawn.')}>Withdraw</Button> : null}
      </div>
      <ProblemBox error={act.error} />
      {act.toast}
    </div>
  );
}
