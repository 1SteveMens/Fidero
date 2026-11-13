'use client';
/* Institution contact: bills to confirm and bills to send (US-FEE-002, FR-FEE-002). Tenmina pays only
   the institution's own verified account (RUL-22). */
import { useState } from 'react';
import { Button, Card, Field, Input, Money, ProblemBox, Select, Status, Textarea, When, useGet } from '@tenmina/web-ui';
import { EmptyText, FilePick, Loaded, PageHead, Section, items, useAct, useApi, words, type Page } from '@/components/roles/kit';
import { toBase64 } from '@/components/roles/files';
import type { FeeInvoice, Institution } from '@/components/roles/fees';

export default function InstitutionBills() {
  const inst = useGet<Page<Institution>>('/v1/institutions');
  const q = useGet<Page<FeeInvoice>>('/v1/invoices');
  const all = items(q.data);
  const toConfirm = all.filter((i) => !i.contact_confirmed && (i.status === 'submitted' || i.status === 'checked'));
  const rest = all.filter((i) => !toConfirm.includes(i));
  return (
    <div className="stack">
      <PageHead label="Institution" title="Bills">{items(inst.data)[0]?.legal_name ?? 'Bills that families abroad pay through Tenmina.'}</PageHead>
      <Loaded q={q}>
        {() => (
          <>
            <Section title="To confirm">
              {toConfirm.length ? toConfirm.map((i) => <ConfirmCard key={i.id} i={i} onDone={() => q.mutate()} />) : <EmptyText>No bills waiting for you.</EmptyText>}
            </Section>
            <SendBill institutions={items(inst.data)} onDone={() => q.mutate()} />
            <Section title="All bills">
              {rest.length ? rest.map((i) => (
                <Card key={i.id} className="stack" style={{ gap: 4 }}>
                  <div className="spread"><div><div className="label">{i.institution_reference}</div><strong>{i.description || 'Bill'}</strong></div><Money value={i.amount} /></div>
                  <div className="row" style={{ fontSize: 14 }}><Status value={i.status} />{i.due_on ? <span className="muted">Due <When value={i.due_on} /></span> : null}</div>
                  <span style={{ fontSize: 14 }}>{i.status_text}</span>
                </Card>
              )) : <EmptyText>No other bills.</EmptyText>}
            </Section>
          </>
        )}
      </Loaded>
    </div>
  );
}

function ConfirmCard({ i, onDone }: { i: FeeInvoice; onDone: () => void }) {
  const api = useApi();
  const act = useAct();
  return (
    <Card className="stack">
      <div className="spread"><div><div className="label">{i.institution_reference}</div><strong>{i.description || 'Bill'}</strong></div><Money value={i.amount} /></div>
      <span style={{ fontSize: 14 }}>For a {i.family_member?.relationship ?? 'student or patient'} of a Tenmina client{i.due_on ? <>, due <When value={i.due_on} /></> : null}. Confirm this is a real bill from {i.institution.name}.</span>
      <Button variant="action" busy={act.busy === 'c'} onClick={() => act.run('c', async () => { await api('POST', `/v1/invoices/${i.id}/contact-confirmation`, { reason: '' }); onDone(); }, 'Confirmed. Thank you.')}>Yes, this is our bill</Button>
      <span className="muted" style={{ fontSize: 13 }}>If it is not, do nothing and call Tenmina. The bill is not paid until it is confirmed and checked.</span>
      <ProblemBox error={act.error} />
      {act.toast}
    </Card>
  );
}

function SendBill({ institutions, onDone }: { institutions: Institution[]; onDone: () => void }) {
  const api = useApi();
  const act = useAct();
  const [instId, setInstId] = useState('');
  const [f, setF] = useState({ ref: '', tenmina: '', description: '', amount: '', currency: 'GHS', due: '' });
  const [file, setFile] = useState<File | null>(null);
  const inst = institutions.find((x) => x.id === instId) ?? institutions[0];
  if (!inst) return null;
  return (
    <Section title="Send a bill">
      <Card className="stack">
        <p className="muted" style={{ margin: 0 }}>Quote the Tenmina reference the family gave you. Tenmina checks it against the student or patient before anyone pays.</p>
        {institutions.length > 1 ? <Field label="Institution"><Select value={inst.id} onChange={(e) => setInstId(e.target.value)}>{institutions.map((x) => <option key={x.id} value={x.id}>{x.legal_name}</option>)}</Select></Field> : null}
        <Field label="Tenmina reference"><Input value={f.tenmina} onChange={(e) => setF({ ...f, tenmina: e.target.value })} /></Field>
        <Field label="Your bill number"><Input value={f.ref} onChange={(e) => setF({ ...f, ref: e.target.value })} /></Field>
        <Field label="What it is for"><Input value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
        <div className="grid2" style={{ gridTemplateColumns: '2fr 1fr', gap: 8 }}>
          <Field label="Amount"><Input inputMode="decimal" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field>
          <Field label="Currency"><Input value={f.currency} maxLength={3} onChange={(e) => setF({ ...f, currency: e.target.value.toUpperCase() })} /></Field>
        </div>
        <Field label="Due date"><Input type="date" value={f.due} onChange={(e) => setF({ ...f, due: e.target.value })} /></Field>
        <FilePick label="The bill (PDF or photo)" file={file} onFile={setFile} accept="application/pdf,image/*" />
        <Button variant="dark" disabled={!file || !f.ref || !f.amount || !f.tenmina} busy={act.busy === 's'} onClick={() => act.run('s', async () => {
          await api('POST', '/v1/invoices', {
            institution_id: inst.id, tenmina_reference: f.tenmina, institution_reference: f.ref, description: f.description,
            amount: { amount: f.amount, currency: f.currency }, due_on: f.due || null,
            document_base64: await toBase64(file!), content_type: file!.type || 'application/pdf', file_name: file!.name,
          });
          setF({ ref: '', tenmina: '', description: '', amount: '', currency: f.currency, due: '' }); setFile(null); onDone();
        }, 'Bill sent. Tenmina checks it and the family approves it.')}>Send the bill</Button>
        <ProblemBox error={act.error} />
      </Card>
      {act.toast}
      <span className="muted" style={{ fontSize: 13 }}>Paid only to {inst.payee ? `${inst.payee.account_name}, account ending ${inst.payee.account_last4}` : 'your verified account'}. {words(inst.status)}.</span>
    </Section>
  );
}
