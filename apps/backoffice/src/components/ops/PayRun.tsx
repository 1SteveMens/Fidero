'use client';
/* W-41 payment run approval (SCR-BO-39 to SCR-BO-41). Only black, white and lime: no
 * yellow, red or orange next to a person or amount, and no verdict anywhere (5.6b, RUL-26).
 * "Not client money" in lime on the black total (6.1d). */
import React, { useState } from 'react';
import Link from 'next/link';
import { formatMoney } from '@tenmina/api-client';
import { Button, call, CodeBoxes, Empty, Field, HoldButton, ProblemBox, Skeleton, Textarea, useGet, useSession, When } from '@tenmina/web-ui';
import { ActionButton, download, OpsToasts, useOpsToast } from './actions';
import { humanize } from './fmt';
import type { Row } from './spec';
import './ops.css';

type Money = { amount: string; currency: string };
const sum = (lines: Row[], k: string, cur: string): Money => ({ amount: lines.reduce((a, l) => a + Number(l[k]?.amount ?? 0), 0).toFixed(2), currency: cur });

const OUTCOME: Record<string, string> = { pending: 'Waiting for the bank', confirmed: 'Paid', failed: 'Bank returned it', unconfirmed: 'Not confirmed yet' };

function Gate({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <li className="ops-gate">
      <span className={`tick ${ok ? '' : 'no'}`} aria-hidden>{ok ? '✓' : ''}</span>
      <span>{children}<span className="sr-only">{ok ? ' (passed)' : ' (not passed)'}</span></span>
    </li>
  );
}

function Approval({ run, onDone }: { run: Row; onDone: () => void }) {
  const { me, hasRole, client, stepUp } = useSession();
  const toast = useOpsToast();
  const [checked, setChecked] = useState(false);
  const [code, setCode] = useState('');
  const [note, setNote] = useState('');
  const [returning, setReturning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const preparer = me?.id === run.prepared_by;

  const decide = async (decision: 'approve' | 'reject') => {
    setBusy(true); setErr(null);
    try {
      if (code.length !== 6) throw new Error('Enter the six-digit code from your authenticator.');
      await stepUp(code);
      await call(client, 'POST', `/v1/pro/payment-runs/${run.id}/approvals`, { decision, note });
      toast(decision === 'approve' ? 'Run approved. The bulk file is ready.' : 'Run returned to the preparer.');
      onDone();
    } catch (e) { setErr(e); setCode(''); } finally { setBusy(false); }
  };

  if (run.approved_by) {
    return (
      <div className="ops-slot done">
        <div className="label" style={{ color: '#a9a69e' }}>Approval</div>
        <div style={{ fontWeight: 800 }}>✓ {run.approved_by_name}</div>
        <div className="mono" style={{ fontSize: 13 }}><When value={run.approved_at} withTime /> · code verified</div>
      </div>
    );
  }
  if (run.status !== 'pending_approval') {
    return <div className="ops-slot"><div className="label" style={{ color: '#a9a69e' }}>Approval</div><div>Not sent for approval yet.</div></div>;
  }
  if (preparer) {
    return <div className="ops-slot"><div className="label" style={{ color: '#a9a69e' }}>Approval</div><div>You prepared this run. A different person with payment rights must approve it (FR-PRO-005).</div></div>;
  }
  if (!hasRole('PY')) {
    return <div className="ops-slot"><div className="label" style={{ color: '#a9a69e' }}>Approval</div><div>You cannot approve payment runs. Waiting for a person with payment rights.</div></div>;
  }
  return (
    <div className="ops-slot mine stack">
      <div>
        <div className="label" style={{ color: '#a9a69e' }}>Approval · your slot</div>
        <div style={{ fontWeight: 800 }}>{me?.full_name}, payment rights</div>
      </div>
      <label className="row ops-check">
        <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} style={{ accentColor: '#a3ee5b' }} />
        <span>I checked the totals and payees</span>
      </label>
      <Field label="Code from your authenticator"><CodeBoxes value={code} onChange={setCode} /></Field>
      {returning ? (
        <Field label="Comment for the preparer"><Textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      ) : null}
      <ProblemBox error={err} />
      {returning ? (
        <div className="row">
          <Button variant="primary" busy={busy} disabled={!note.trim()} onClick={() => decide('reject')}>Return with comment</Button>
          <Button variant="ghost" style={{ color: '#fff' }} onClick={() => setReturning(false)}>Back</Button>
        </div>
      ) : (
        <>
          <HoldButton tone="lime" label={busy ? 'Working…' : 'Approve run'} disabled={!checked || code.length !== 6 || busy} onConfirm={() => decide('approve')} />
          <Button variant="ghost" style={{ color: '#fff' }} onClick={() => setReturning(true)}>Return with comment</Button>
        </>
      )}
    </div>
  );
}

function RunView({ id }: { id: string }) {
  const { data: run, error, isLoading, mutate } = useGet<Row>(`/v1/pro/payment-runs/${id}`);
  const toast = useOpsToast();
  const [dlErr, setDlErr] = useState<unknown>(null);
  if (error) return <ProblemBox error={error} />;
  if (isLoading || !run) return <Skeleton lines={8} />;
  const lines = (run.lines as Row[]) ?? [];
  const excluded = (run.excluded as Row[]) ?? [];
  const cur = String(run.currency);
  const acct = run.operating_account as Row;
  const done = () => mutate();
  const held = excluded.filter((x) => x.rule === 'RUL-26' || String(x.reason).startsWith('Held'));
  const unverified = excluded.filter((x) => /verif/i.test(String(x.reason)));
  const waitingExpense = excluded.filter((x) => x.kind === 'expense');
  const issued = ['file_issued', 'partly_confirmed', 'confirmed', 'closed'].includes(String(run.status));

  return (
    <div className="stack ops">
      <Link href="/pay-runs" className="label ops-back">← Payment runs</Link>
      <div className="spread" style={{ alignItems: 'flex-start' }}>
        <div>
          <p className="label" style={{ margin: 0 }}>SCR-BO-40 · Payment run</p>
          <h1 style={{ marginBottom: 6, overflowWrap: 'anywhere' }}>{run.reference}</h1>
          <div className="row" style={{ gap: 8 }}>
            <span className="chip">{humanize(String(run.status))}</span>
            <span className="mono">{run.country}</span>
            <span className="mono">Cut-off <When value={run.cut_off_at} withTime /></span>
          </div>
        </div>
      </div>
      {run.status_reason ? <div className="banner-info">{run.status_reason}</div> : null}

      <section className="card-ink stack" aria-label="Total">
        <div className="ops-sentence">
          Pay {formatMoney(run.total_net as Money)} to {lines.length} professional{lines.length === 1 ? '' : 's'} from {acct?.name ?? 'Tenmina\'s operating account'}
          {acct?.bank_name ? ` at ${acct.bank_name}` : ''}{acct?.account_last4 ? `, ending ${acct.account_last4}` : ''}.{' '}
          <span className="ops-lime">Not client money.</span>
        </div>
        <div className="mono" style={{ fontSize: 13, color: '#a9a69e' }}>Gross {formatMoney(run.total_gross as Money)} · Amounts and tax rates are working assumptions [TO VERIFY].</div>
        <div>
          <div className="label" style={{ color: '#a9a69e', marginBottom: 8 }}>Checks (all must pass)</div>
          <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 8 }}>
            <Gate ok={lines.every((l) => l.account_name && l.account_last4)}>Every line pays a verified account in the name on the agreement{unverified.length ? `; ${unverified.length} not verified left out` : ''}</Gate>
            <Gate ok>Every payable is for accepted work; {held.length ? `${held.length} held left out` : 'nothing held'}</Gate>
            <Gate ok>{waitingExpense.length ? `${waitingExpense.length} expense claim${waitingExpense.length === 1 ? '' : 's'} waiting for a second approval left out` : 'Every expense claim over the limit has its second approval'}</Gate>
            <Gate ok={lines.every((l) => l.withholding)}>Tax withheld per the {run.country} configuration</Gate>
            <Gate ok={String(acct?.kind ?? '').startsWith('operating')}>Debit account is an operating account, not an escrow or held-funds account</Gate>
          </ul>
        </div>
      </section>

      <section className="stack">
        <h2 style={{ margin: 0 }}>Lines</h2>
        {lines.length ? (
          <div className="table-wrap">
            <table className="table responsive ops-table">
              <thead><tr><th>Professional</th><th>Role</th><th>Items</th><th>Gross</th><th>Tax</th><th>Expenses</th><th>Net</th><th>Paid to</th>{issued ? <th>Bank</th> : null}{issued || run.status === 'draft' ? <th aria-label="Actions" /> : null}</tr></thead>
              <tbody>
                {lines.map((l) => (
                  <tr key={l.id}>
                    <td data-label="Professional"><strong>{l.professional_name}</strong></td>
                    <td data-label="Role">{humanize(String(l.role))}</td>
                    <td data-label="Items" className="mono">{(l.items as Row[])?.length ?? 0}</td>
                    <td data-label="Gross" className="mono">{formatMoney(l.gross)}</td>
                    <td data-label="Tax" className="mono">{formatMoney(l.withholding)}</td>
                    <td data-label="Expenses" className="mono">{formatMoney(l.reimbursed_expenses)}</td>
                    <td data-label="Net" className="mono" style={{ fontWeight: 800 }}>{formatMoney(l.net)}</td>
                    <td data-label="Paid to" className="mono">{l.account_name} ·{l.account_last4}</td>
                    {issued ? <td data-label="Bank">{OUTCOME[String(l.outcome)] ?? humanize(String(l.outcome))}{l.failure_reason ? <small className="muted" style={{ display: 'block' }}>{l.failure_reason}. We pay it in the next run unless resolved otherwise.</small> : null}</td> : null}
                    {issued || run.status === 'draft' ? (
                      <td data-label="">
                        <div className="row ops-row-actions">
                          <ActionButton a={{ label: 'Remove line', path: '/v1/pro/payment-lines/{id}/removals', tone: 'ghost', when: () => run.status === 'draft' }} row={l} onDone={done} />
                          <ActionButton a={{ label: 'Resolve', path: '/v1/pro/payment-lines/{id}/resolutions', when: (x) => ['failed', 'unconfirmed'].includes(String(x.outcome)) && !x.resolution, fields: [{ name: 'letter_evidence_id', type: 'file', upload: { subject_type: 'pro_payment_run', subjectId: () => String(run.id) }, label: 'Bank letter (for confirmed by bank letter)' }] }} row={l} onDone={done} />
                          <ActionButton a={{ label: 'Check bank letter', path: '/v1/pro/payment-lines/{id}/letter-checks', tone: 'primary', when: (x) => x.resolution === 'confirmed_by_bank_letter' && !x.resolved_by, fields: [{ name: 'accept', default: true, label: 'The letter confirms this payment' }], confirm: 'You did not record the letter.' }} row={l} onDone={done} />
                        </div>
                      </td>
                    ) : null}
                  </tr>
                ))}
                <tr>
                  <td data-label="Total"><strong>Total</strong></td><td data-label="" /><td data-label="" />
                  <td data-label="Gross" className="mono">{formatMoney(sum(lines, 'gross', cur))}</td>
                  <td data-label="Tax" className="mono">{formatMoney(sum(lines, 'withholding', cur))}</td>
                  <td data-label="Expenses" className="mono">{formatMoney(sum(lines, 'reimbursed_expenses', cur))}</td>
                  <td data-label="Net" className="mono" style={{ fontWeight: 800 }}>{formatMoney(run.total_net as Money)}</td>
                  <td data-label="" />{issued ? <td data-label="" /> : null}{issued || run.status === 'draft' ? <td data-label="" /> : null}
                </tr>
              </tbody>
            </table>
          </div>
        ) : <Empty>No lines. Nothing is due by this cut-off.</Empty>}
      </section>

      <section className="stack">
        <h2 style={{ margin: 0 }}>Left out, and why</h2>
        {excluded.length ? (
          <ul className="ops-checklist">
            {excluded.map((x) => (
              <li key={x.id}><span className="tick" aria-hidden /> <span><strong>{x.professional}</strong> · {humanize(String(x.kind))} · <span className="mono">{x.amount} {x.currency}</span><small className="muted" style={{ display: 'block' }}>{x.reason}</small></span></li>
            ))}
          </ul>
        ) : <p className="muted" style={{ margin: 0 }}>Nothing left out.</p>}
      </section>

      <section className="card-ink">
        <div className="grid2">
          <div className="ops-slot done">
            <div className="label" style={{ color: '#a9a69e' }}>Prepared by</div>
            <div style={{ fontWeight: 800 }}>✓ {run.prepared_by_name ?? 'Preparer'}</div>
            <div className="mono" style={{ fontSize: 13 }}><When value={run.created_at} withTime /></div>
          </div>
          <Approval run={run} onDone={done} />
        </div>
      </section>

      {run.status === 'draft' ? (
        <div className="row ops-actions">
          <ActionButton a={{ label: 'Send for approval', path: '/v1/pro/payment-runs/{id}/submit', tone: 'primary', confirm: 'A different person with payment rights must approve it.' }} row={run} onDone={done} size="md" />
          <ActionButton a={{ label: 'Refresh lines', path: '/v1/pro/payment-runs/{id}/refresh', tone: 'dark' }} row={run} onDone={done} size="md" />
          <ActionButton a={{ label: 'Withdraw run', path: '/v1/pro/payment-runs/{id}/withdraw', tone: 'ghost' }} row={run} onDone={done} size="md" />
        </div>
      ) : null}
      {run.status === 'pending_approval' ? (
        <div className="row ops-actions"><ActionButton a={{ label: 'Withdraw run', path: '/v1/pro/payment-runs/{id}/withdraw', tone: 'ghost' }} row={run} onDone={done} size="md" /></div>
      ) : null}

      <section className="card stack" aria-label="Bulk file">
        <h2 style={{ margin: 0 }}>Bulk file</h2>
        {run.file_sha256 ? (
          <>
            <p style={{ margin: 0 }}>Built in the bank&apos;s format ({run.file_format}). Check this SHA-256 when you upload it to the bank&apos;s portal.</p>
            <div className="mono" style={{ overflowWrap: 'anywhere', background: '#0b0b0b', color: '#a3ee5b', padding: 12, borderRadius: 10 }}>{run.file_sha256}</div>
            <div className="row">
              {run.file_downloadable ? <Button variant="dark" onClick={async () => { setDlErr(null); try { await download(`/v1/pro/payment-runs/${run.id}/file`, `${run.reference}.csv`); toast('Downloaded. The download is logged.'); } catch (e) { setDlErr(e); } }}>Download file</Button> : null}
              <ActionButton a={{ label: 'Mark uploaded to the bank', path: '/v1/pro/payment-runs/{id}/uploads', when: (r) => !r.uploaded_at && r.status === 'file_issued', confirm: 'You uploaded the file with this hash to the operating bank\'s portal.' }} row={run} onDone={done} size="md" />
              <ActionButton a={{ label: 'Import bank confirmation', path: '/v1/pro/payment-runs/{id}/confirmations', tone: 'primary', when: (r) => ['file_issued', 'partly_confirmed'].includes(String(r.status)), only: ['content', 'filename'], fields: [{ name: 'content', type: 'textfile', label: 'Confirmation file from the bank', required: true, fileNameField: 'filename' }, { name: 'filename', type: 'hidden' }] }} row={run} onDone={done} size="md" />
            </div>
            {run.uploaded_at ? <p className="muted" style={{ margin: 0 }}>Uploaded by {run.uploaded_by_name} · <When value={run.uploaded_at} withTime /></p> : null}
            <ProblemBox error={dlErr} />
          </>
        ) : <p className="muted" style={{ margin: 0 }}>After approval the bulk file is built here with its SHA-256. Status then moves to File issued, and to Confirmed when the bank&apos;s confirmation is imported.</p>}
      </section>
    </div>
  );
}

export function PayRunPage({ id }: { id: string }) {
  return <OpsToasts><RunView id={id} /></OpsToasts>;
}
