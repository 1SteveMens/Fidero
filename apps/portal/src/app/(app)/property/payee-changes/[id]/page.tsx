'use client';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { Button, CodeBoxes, Dialog, HoldButton, ProblemBox, Skeleton, Textarea, When, useGet, useSession } from '@tenmina/web-ui';
import { Ink, PageHead, Section, useAction, words, type Any } from '@/components/kit';

const SOURCE: Record<string, string> = { bank_name_check: 'Account name confirmed by the bank', bank_letter: 'Account name from a bank letter', manual: 'Account name checked by hand' };

/** W-42 · SCR-PTL-55: approve a payee change, on black, with press and hold and the code. Rejecting keeps the old payee. */
export default function PayeeChange() {
  const { id } = useParams<{ id: string }>();
  const { me } = useSession();
  const q = useGet<Any>(`/v1/payee-changes/${id}`);
  const a = useAction();
  const [mode, setMode] = useState<null | 'approve' | 'reject' | 'stop'>(null);
  const [code, setCode] = useState('');
  const [reason, setReason] = useState('');
  if (q.isLoading) return <Ink><Skeleton lines={6} /></Ink>;
  if (!q.data) return <Ink><ProblemBox error={q.error} /></Ink>;
  const ch = q.data;
  const mine = ch.status === 'checks_passed';
  const cooling = ch.cooling_off_until && new Date(ch.cooling_off_until) > new Date() && ch.status === 'applied';
  async function go() {
    const path = mode === 'stop' ? `/v1/payee-changes/${id}/stop` : `/v1/payee-changes/${id}/client-approval`;
    const body = mode === 'stop' ? { code, reason } : { approve: mode === 'approve', code, reason, gesture: 'press_and_hold' };
    await a.run('go', () => a.post(path, body), mode === 'approve' ? 'Approved' : mode === 'stop' ? 'Stopped. The old payee stays.' : 'Rejected. The old payee stays.', () => { setMode(null); setCode(''); q.mutate(); });
  }
  const acct = (label: string, name: string, last4: string, bank?: string) => (
    <div className="card"><div className="label">{label}</div><div style={{ fontWeight: 700 }}>{name}</div><div className="mono">{bank ? `${bank} · ` : ''}account ending {last4}</div></div>
  );
  return (
    <Ink>
      <PageHead back={{ href: ch.escrow ? `/property/escrows/${ch.escrow}` : '/', label: ch.escrow ? 'Escrow' : 'Home' }} label={`Payee change · ${words(ch.status)}`} title={mine ? 'Approve a payee change?' : 'Payee change'} />
      <p style={{ margin: 0 }}>Asked by {words(ch.request_source)} on <When value={ch.requested_at} withTime />. Reason given: {ch.reason}</p>
      <div className="grid2">
        {acct('Old account', ch.previous_account_name || '—', ch.previous_last4 || '—')}
        {acct('New account', ch.account_name, ch.account_last4, ch.bank_name)}
      </div>
      <Section title="Checks on the new payee">
        <div className="card" style={{ paddingTop: 4, paddingBottom: 4 }}>
          <div className="check-row"><span className={`tick ${ch.national_id_check ? 'done' : ''}`}>{ch.national_id_check ? '✓' : ''}</span><div>Identity checked against the national identity system</div><span /></div>
          <div className="check-row"><span className={`tick ${ch.account_name_source ? 'done' : ''}`}>{ch.account_name_source ? '✓' : ''}</span><div>{SOURCE[ch.account_name_source] ?? 'Account name check'}</div><span /></div>
        </div>
      </Section>
      {ch.cooling_off_until ? <p className="mono" style={{ margin: 0 }}>No money can go to the new account until <When value={ch.cooling_off_until} withTime />.</p> : null}
      <p className="muted" style={{ margin: 0 }}>We never change who gets paid because of a message, email or call.</p>
      {mine ? (
        me?.mfa_enabled ? (
          <div className="stack">
            <HoldButton label="Hold to approve the change" onConfirm={() => setMode('approve')} />
            <Button variant="ghost" onClick={() => setMode('reject')}>Reject. Keep the old payee</Button>
          </div>
        ) : <Link className="btn btn-primary" href="/account/security">Set up your authenticator app to decide</Link>
      ) : null}
      {cooling && me?.mfa_enabled ? <Button variant="ghost" onClick={() => setMode('stop')}>Stop this change</Button> : null}
      <ProblemBox error={!mode ? a.error : null} />
      <Dialog open={!!mode} onClose={() => setMode(null)} title={mode === 'approve' ? 'Enter your code' : mode === 'stop' ? 'Stop the change' : 'Reject the change'} ink>
        <div className="stack">
          {mode !== 'approve' ? <label className="field"><span>Why</span><Textarea value={reason} onChange={(e) => setReason(e.target.value)} /></label> : null}
          <p className="muted" style={{ margin: 0 }}>Code from your authenticator app</p>
          <CodeBoxes value={code} onChange={setCode} autoFocus />
          <ProblemBox error={a.error} />
          <Button variant={mode === 'approve' ? 'action' : 'dark'} block disabled={code.length !== 6} busy={a.busy === 'go'} onClick={go}>{mode === 'approve' ? 'Approve the change' : mode === 'stop' ? 'Stop the change' : 'Reject the change'}</Button>
        </div>
      </Dialog>
      {a.toast}
    </Ink>
  );
}
