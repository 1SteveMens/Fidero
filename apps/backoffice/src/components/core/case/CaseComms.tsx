'use client';
/* Requests to the client (FR-CASE-008) and the case thread (FR-CASE-015). A message that mentions a new account
 * gets the payee lock banner (5.6c): payee details are never taken from a message. */
import { useState } from 'react';
import { Button, call, Empty, ProblemBox, Skeleton, Textarea, useGet, useSession } from '@tenmina/web-ui';
import { ActionForm, day, dayTime, Panel, useAct, words } from '../kit';
import type { CaseDetail, DocRequest, Message } from '../types';

const ACCOUNT_WORDS = /(account|bank|acct|momo|mobile money|iban|sort code|pay (it|to|into))/i;

export function CaseComms({ c, reload }: { c: CaseDetail; reload: () => void }) {
  const { client } = useSession();
  const reqs = useGet<DocRequest[]>(`/v1/cases/${c.id}/document-requests`);
  const msgs = useGet<Message[]>(`/v1/cases/${c.id}/messages`);
  const [body, setBody] = useState('');
  const act = useAct();
  const open = ['paid', 'in_progress', 'on_hold', 'in_review'].includes(c.status);
  return (
    <div className="cols">
      <Panel title="Messages with the client">
        {msgs.isLoading ? <Skeleton /> : msgs.data?.length ? (
          <div className="thread">
            {msgs.data.map((m) => (
              <div key={m.id} className={`bubble ${m.side === 'client' ? '' : 'staff'}`}>
                <div className="label">{m.sender?.name ?? words(m.side)} · {dayTime(m.created_at)}</div>
                <div style={{ whiteSpace: 'pre-wrap' }}>{m.body}</div>
                {m.side === 'client' && ACCOUNT_WORDS.test(m.body) ? <div className="strip-ink" style={{ marginTop: 8, fontSize: 13 }}><span aria-hidden>🔒</span>Payee details are never taken from a message. Start a payee change instead.</div> : null}
              </div>
            ))}
          </div>
        ) : <Empty>No messages yet.</Empty>}
        <ProblemBox error={msgs.error} />
        <form className="stack" onSubmit={async (e) => { e.preventDefault(); const ok = await act.run(() => call(client, 'POST', `/v1/cases/${c.id}/messages`, { body }), 'Message sent.'); if (ok !== undefined) { setBody(''); msgs.mutate(); } }}>
          <label className="field"><span>Reply</span><Textarea value={body} onChange={(e) => setBody(e.target.value)} required /></label>
          <ProblemBox error={act.error} />
          <div><Button type="submit" busy={act.busy}>Send</Button></div>
        </form>
        {act.toast}
      </Panel>
      <Panel title="Requests to the client" actions={open ? (
        <ActionForm label="+ Request a document" path={`/v1/cases/${c.id}/document-requests`} fields={[
          { name: 'title', label: 'What you need', required: true, placeholder: "Seller's ID number" },
          { name: 'description', label: 'Why and how (shown to the client)', type: 'textarea' },
          { name: 'due_on', label: 'Due on', type: 'date' },
        ]} body={(v) => ({ title: v.title, description: v.description, due_on: v.due_on || null })} onDone={() => { reqs.mutate(); reload(); }} submitLabel="Send request" />
      ) : null}>
        {reqs.isLoading ? <Skeleton /> : reqs.data?.length ? (
          <div className="rows">
            {reqs.data.map((r) => (
              <div key={r.id} className="rowlink">
                <div className="main">
                  <div className="title">{r.title}</div>
                  <div className="meta">{r.description}{r.due_on ? ` · due ${day(r.due_on)}` : ''}{r.received_at ? ` · received ${day(r.received_at)}` : ''}</div>
                </div>
                <div className="row" style={{ gap: 6 }}>
                  <span className={`chip ${r.status === 'received' ? 'chip-lime' : ''}`}>{r.status === 'received' ? '✓ Received' : words(r.status)}</span>
                  {r.status === 'open' ? <ActionForm label="Cancel" path={`/v1/document-requests/${r.id}/cancel`} fields={[{ name: 'reason', label: 'Reason', type: 'textarea', required: true }]} onDone={() => reqs.mutate()} submitLabel="Cancel request" /> : null}
                </div>
              </div>
            ))}
          </div>
        ) : <Empty>No requests yet.</Empty>}
      </Panel>
    </div>
  );
}
