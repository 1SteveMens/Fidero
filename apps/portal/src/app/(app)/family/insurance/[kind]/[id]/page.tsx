'use client';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button, Field, Input, KV, Money, ProblemBox, Select, Skeleton, Textarea, When, useGet } from '@tenmina/web-ui';
import { Copy, EvidenceLink, FilePick, Ink, PageHead, Proof, RadioCard, Section, fileFields, list, useAction, uploadEvidence, words, type Any } from '@/components/kit';

const API: Record<string, string> = { products: 'products', applications: 'applications', policies: 'policies', premiums: 'premiums', claims: 'claims' };
const STATEMENT = 'A policy from the insurer named here. Tenmina does not hold the risk.';

/** SCR-PTL-51 (product and apply), SCR-PTL-52 (policy wallet, premiums, claims). Insurance is the insurer's product (RUL-25). */
export default function Insurance() {
  const { kind, id } = useParams<{ kind: string; id: string }>();
  const q = useGet<Any>(API[kind] ? `/v1/insurance/${API[kind]}/${id}` : null);
  if (!API[kind]) return <ProblemBox error={new Error('Not found')} />;
  if (q.isLoading) return <Skeleton lines={6} />;
  if (!q.data) return <ProblemBox error={q.error} />;
  const d = q.data;
  return kind === 'products' ? <Product p={d} /> : kind === 'applications' ? <Application x={d} refresh={() => q.mutate()} /> : kind === 'policies' ? <Policy p={d} /> : kind === 'premiums' ? <Premium p={d} refresh={() => q.mutate()} /> : <Claim c={d} />;
}

function Product({ p }: { p: Any }) {
  const router = useRouter();
  const fams = useGet<Any>('/v1/family-members');
  const [fm, setFm] = useState('');
  const [route, setRoute] = useState(p.premium_routes?.[0] ?? 'client_direct_to_insurer');
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [consent, setConsent] = useState(false);
  const a = useAction();
  return (
    <div className="stack" style={{ gap: 16 }}>
      <PageHead back={{ href: '/family', label: 'Family' }} label={`${words(p.kind)} cover · ${p.insurer_name}`} title={p.name} />
      <div className="card"><strong>{STATEMENT}</strong><p className="muted" style={{ margin: '6px 0 0' }}>{p.statement}</p></div>
      <p style={{ margin: 0 }}>{p.summary}</p>
      <KV items={[['Premium', <span key="p"><Money value={p.premium} /> a {p.premium_period}</span>], ['Insurer', p.insurer_name]]} />
      {p.terms_evidence ? <EvidenceLink id={p.terms_evidence} label="Read the insurer's terms" /> : null}
      <form className="card stack" onSubmit={(e) => { e.preventDefault(); a.run('go', () => a.post<Any>('/v1/insurance/applications', { product_id: p.id, family_member_id: fm, answers, premium_route: route, submit: true, consent }), undefined, (r) => router.push(`/family/insurance/applications/${r.id}`)); }}>
        <h3 style={{ margin: 0 }}>Apply</h3>
        <Field label="Who is covered"><Select value={fm} onChange={(e) => setFm(e.target.value)} required><option value="">Choose</option>{list(fams.data).map((m: Any) => <option key={m.id} value={m.id}>{m.full_name}</option>)}</Select></Field>
        {(p.application_questions ?? []).map((qq: Any) => <Field key={qq.key ?? qq} label={qq.label ?? String(qq)}><Input value={answers[qq.key ?? qq] ?? ''} onChange={(e) => setAnswers({ ...answers, [qq.key ?? qq]: e.target.value })} /></Field>)}
        {(p.premium_routes ?? []).length > 1 ? (p.premium_routes as string[]).map((r) => (
          <RadioCard key={r} name="route" checked={route === r} onChange={() => setRoute(r)}><strong>{r === 'client_direct_to_insurer' ? 'I pay the insurer myself' : 'The bank pays from money it holds for me'}</strong></RadioCard>
        )) : null}
        <label className="row" style={{ flexWrap: 'nowrap', alignItems: 'flex-start' }}><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} style={{ width: 22, height: 22, flex: 'none' }} /> <span>I agree that Tenmina sends this application and these details to {p.insurer_name}.</span></label>
        <ProblemBox error={a.error} />
        <Button variant="primary" type="submit" busy={!!a.busy} disabled={!fm || !consent}>Send the application</Button>
      </form>
    </div>
  );
}

function Application({ x, refresh }: { x: Any; refresh: () => void }) {
  const a = useAction();
  return (
    <div className="stack" style={{ gap: 16 }}>
      <PageHead back={{ href: '/family', label: 'Family' }} label={`${x.insurer_name} · ${words(x.status)}`} title={x.product_name} sub={x.status_text} />
      <KV items={[['Sent to the insurer', x.submitted_to_insurer_at ? <When key="s" value={x.submitted_to_insurer_at} /> : 'Not yet'], ['Insurer reference', x.insurer_reference || '—'], ['Decided', x.decided_at ? <When key="d" value={x.decided_at} /> : '—'], ['Insurer note', x.insurer_note || '—']]} />
      {!x.submitted_to_insurer_at ? <Button variant="primary" busy={a.busy === 's'} onClick={() => a.run('s', () => a.post(`/v1/insurance/applications/${x.id}/submission`, { consent: true }), 'Sent', refresh)}>Send to the insurer</Button> : null}
      {x.policy ? <Link className="btn btn-dark" href={`/family/insurance/policies/${x.policy}`}>Open the policy</Link> : null}
      {['draft', 'submitted'].includes(x.status) ? <Button variant="ghost" busy={a.busy === 'w'} onClick={() => a.run('w', () => a.post(`/v1/insurance/applications/${x.id}/withdrawal`, {}), 'Withdrawn', refresh)}>Withdraw the application</Button> : null}
      <ProblemBox error={a.error} />
      {a.toast}
    </div>
  );
}

function Policy({ p }: { p: Any }) {
  const router = useRouter();
  const prem = useGet<Any>('/v1/insurance/premiums');
  const claims = useGet<Any>('/v1/insurance/claims');
  const [c, setC] = useState({ description: '', event_date: '' });
  const [docs, setDocs] = useState<Any[]>([]);
  const a = useAction();
  return (
    <div className="stack" style={{ gap: 16 }}>
      <PageHead back={{ href: '/family', label: 'Family' }} label={`${p.insurer_name} · ${p.policy_number}`} title={p.product_name} sub={STATEMENT} />
      <KV items={[['Status', words(p.status)], ['Started', <When key="s" value={p.starts_on} />], ['Renews', <When key="r" value={p.renews_on} />], ['Premium', <span key="p"><Money value={p.premium} /> a {p.premium_period}</span>], ['How it is paid', p.premium_route === 'held_funds_to_insurer' ? 'The bank pays from money held for you' : 'You pay the insurer'], ['Claims contact', p.claim_contact]]} />
      {p.document_evidence ? <EvidenceLink id={p.document_evidence} label="Policy document" /> : null}
      <Section title="Premiums">
        {list(prem.data).filter((x: Any) => x.policy === p.id).map((x: Any) => <Link key={x.id} href={`/family/insurance/premiums/${x.id}`} className="card card-link spread"><span>Due <When value={x.due_on} /> · {words(x.status)}</span><Money value={x.amount} /></Link>)}
      </Section>
      <Section title="Claims">
        {list(claims.data).filter((x: Any) => x.policy === p.id).map((x: Any) => <Link key={x.id} href={`/family/insurance/claims/${x.id}`} className="card card-link"><strong>{x.description}</strong><div className="muted">{x.status_text}</div></Link>)}
        <form className="card stack" onSubmit={(e) => { e.preventDefault(); a.run('c', () => a.post<Any>(`/v1/insurance/policies/${p.id}/claims`, { description: c.description, event_date: c.event_date || null, document_ids: docs.map((d) => d.id) }), undefined, (r) => router.push(`/family/insurance/claims/${r.id}`)); }}>
          <h3 style={{ margin: 0 }}>Start a claim</h3>
          <p className="muted" style={{ margin: 0, fontSize: 14 }}>Tenmina sends it to {p.insurer_name}. The insurer decides and pays.</p>
          <Field label="What happened"><Textarea value={c.description} onChange={(e) => setC({ ...c, description: e.target.value })} required /></Field>
          <Field label="When"><Input type="date" value={c.event_date} onChange={(e) => setC({ ...c, event_date: e.target.value })} /></Field>
          <FilePick label="Add a document" onFile={async (f) => { const ev = await a.run('up', () => uploadEvidence(a.client, f, { type: 'ins_policy', id: p.id, role: 'claim_document' })); if (ev) setDocs([...docs, ev]); }} busy={a.busy === 'up'} />
          {docs.length ? <small className="muted">{docs.length} document(s) attached</small> : null}
          <ProblemBox error={a.error} />
          <Button variant="primary" type="submit" busy={a.busy === 'c'}>Send the claim</Button>
        </form>
      </Section>
    </div>
  );
}

function Premium({ p, refresh }: { p: Any; refresh: () => void }) {
  const [ref, setRef] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const a = useAction();
  const pt = p.pay_to;
  return (
    <Ink>
      <PageHead back={{ href: `/family/insurance/policies/${p.policy}`, label: p.policy_number }} label={`${p.insurer_name} · due ${p.due_on}`} title={p.status === 'due' ? 'Pay the premium' : words(p.status)} />
      <div style={{ fontSize: 32, fontWeight: 800 }}><Money value={p.amount} /></div>
      {pt && p.status === 'due' ? (
        <>
          <section className="card" style={{ paddingTop: 4, paddingBottom: 4 }}>
            {[['Account name', pt.account_name], ['Bank', pt.bank_name], ['Account number', pt.account_number], ['Reference', pt.reference]].map(([k, v]) => (
              <div key={k} className="check-row" style={{ gridTemplateColumns: '1fr auto' }}><div><div className="label">{k}</div><div className="mono" style={{ overflowWrap: 'anywhere' }}>{v}</div></div>{k !== 'Bank' ? <Copy value={String(v)} /> : <span />}</div>
            ))}
          </section>
          <p style={{ margin: 0 }}>{pt.note}</p>
          <form className="card stack" onSubmit={async (e) => { e.preventDefault(); a.run('p', async () => a.post(`/v1/insurance/premiums/${p.id}/client-payment`, { reference: ref, ...(file ? await fileFields(file) : {}) }), 'Thank you. The insurer will confirm.', refresh); }}>
            <h3 style={{ margin: 0 }}>I have paid the insurer</h3>
            <Field label="Transfer reference"><Input value={ref} onChange={(e) => setRef(e.target.value)} /></Field>
            <FilePick label={file ? `Proof: ${file.name}` : 'Add proof (optional)'} onFile={setFile} />
            <Button variant="action" type="submit" busy={!!a.busy}>Tell Tenmina I have paid</Button>
          </form>
        </>
      ) : null}
      {p.release_instruction ? <Link className="btn btn-ghost" href={`/property/releases/${p.release_instruction}`}>The bank payment to the insurer</Link> : null}
      {p.client_reported_at ? <p className="muted" style={{ margin: 0 }}>You reported paying on <When value={p.client_reported_at} />.</p> : null}
      {p.paid_at ? <Proof>Paid <When value={p.paid_at} /></Proof> : null}
      {p.insurer_receipt_evidence ? <EvidenceLink id={p.insurer_receipt_evidence} label="Insurer's receipt" /> : null}
      <ProblemBox error={a.error} />
      {a.toast}
    </Ink>
  );
}

function Claim({ c }: { c: Any }) {
  return (
    <div className="stack" style={{ gap: 16 }}>
      <PageHead back={{ href: `/family/insurance/policies/${c.policy}`, label: 'Policy' }} label={`Claim ${c.insurer_reference || ''}`} title={c.description} sub={c.status_text} />
      <KV items={[['Happened', c.event_date ? <When key="e" value={c.event_date} /> : '—'], ['Sent to the insurer', c.submitted_to_insurer_at ? <When key="s" value={c.submitted_to_insurer_at} /> : 'Not yet'], ['Insurer says', words(c.insurer_status)]]} />
      <Section title="The insurer's updates">
        {(c.updates ?? []).map((u: Any) => <div key={u.id} className="card"><div className="label"><When value={u.created_at} withTime /> · {words(u.insurer_status)}</div>{u.note}{u.evidence ? <div><EvidenceLink id={u.evidence} label="Document" /></div> : null}</div>)}
      </Section>
      {c.outcome_evidence ? <EvidenceLink id={c.outcome_evidence} label="The insurer's decision" /> : null}
      <p className="muted" style={{ margin: 0, fontSize: 14 }}>The insurer decides and pays claims. Tenmina passes on what you send and what the insurer answers.</p>
    </div>
  );
}
