'use client';
import { formatMoney } from '@tenmina/api-client';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { Blocked, Button, Chip, Field, Input, KV, Money, NeedsYou, ProblemBox, Select, Skeleton, Steps, When, useGet } from '@tenmina/web-ui';
import { ActionDialog, Bar, EvidenceLink, PageHead, Proof, Section, list, uploadEvidence, useAction, words, type Any } from '@/components/kit';

/** W-19 · SCR-PTL-22: the build dashboard (and the project fund dashboard, SCR-PTL-30). */
export default function ProjectDashboard() {
  const { id } = useParams<{ id: string }>();
  const p = useGet<Any>(`/v1/projects/${id}`);
  const d = useGet<Any>(`/v1/projects/${id}/dashboard`);
  const vars = useGet<Any[]>(`/v1/projects/${id}/variations`);
  const defects = useGet<Any>('/v1/defects');
  const a = useAction();
  if (p.isLoading || d.isLoading) return <Skeleton lines={8} />;
  if (!p.data || !d.data) return <ProblemBox error={p.error ?? d.error} />;
  const pr = p.data;
  const db = d.data;
  const funds = pr.type === 'funds';
  const refresh = () => { p.mutate(); d.mutate(); vars.mutate(); };
  const awaiting = (db.payments ?? []).filter((x: Any) => x.status === 'awaiting_client' || x.status === 'awaiting_client_payment');
  const openVars = (vars.data ?? []).filter((v: Any) => v.status === 'proposed' && !v.client_agreed_at);
  const myDefects = list(defects.data).filter((x: Any) => x.project_id === id);
  return (
    <div className="stack" style={{ gap: 18 }}>
      <PageHead back={{ href: '/projects', label: 'Projects' }} label={`${funds ? 'Project fund' : words(pr.type)} · ${words(pr.status)}`} title={pr.title}
        sub={funds ? `Run by ${pr.runner_name}` : [pr.contractor_name && `Contractor: ${pr.contractor_name}`, db.inspector && `Inspector: ${db.inspector}`].filter(Boolean).join(' · ')} />
      {awaiting.map((x: Any) => <NeedsYou key={x.id} title={x.status === 'awaiting_client' ? `Approve ${x.label}` : `Pay ${x.payee}: ${x.label}`} detail="Nothing is paid until you approve." href={`/projects/payments/${x.id}`} />)}
      {openVars.map((v: Any) => <NeedsYou key={v.id} title={`Agree a change: ${v.description}`} detail={`${formatMoney(v.cost_change)}, ${v.time_effect_days} days.`} href={`/projects/variations/${v.id}`} />)}
      {pr.status_reason ? <Blocked title={words(pr.status)}>{pr.status_reason}</Blocked> : null}
      <section className="card stack">
        <div className="spread"><strong>Budget</strong><Money value={db.budget} /></div>
        <Bar value={Number(db.paid.amount)} max={Number(db.budget.amount) + Number(db.variations_agreed?.amount ?? 0)} label="Paid against the budget" />
        <KV items={[
          ['Paid', <Money key="p" value={db.paid} />], ['Left', <Money key="l" value={db.remaining} />],
          ...(Number(db.variations_agreed?.amount) ? [['Agreed changes', <Money key="v" value={db.variations_agreed} />] as [string, React.ReactNode]] : []),
          ...(Number(db.defect_value_held?.amount) ? [['Held for defects', <Money key="d" value={db.defect_value_held} />] as [string, React.ReactNode]] : []),
          ...(Number(db.retention_held?.amount) ? [['Retention held', <Money key="r" value={db.retention_held} />] as [string, React.ReactNode]] : []),
          ['How payments go', db.route === 'escrow' ? 'From money held at the bank' : 'You pay the verified payee yourself'],
          ...(db.guide_budget ? [['Guide', <span key="g"><Money value={db.guide_budget} /> (a guide, not a charge)</span>] as [string, React.ReactNode]] : []),
        ]} />
      </section>
      {pr.escrow_id ? <Link className="card-ink card-link" href={`/property/escrows/${pr.escrow_id}`}><div className="label" style={{ color: '#a9a69e' }}>Held at the bank</div><Money value={db.held_at_bank} /> <span style={{ color: '#a9a69e' }}>· open the escrow</span></Link> : null}
      {pr.status === 'setup' && !funds ? <SetupSteps pr={pr} onDone={refresh} /> : null}
      {funds ? <Funds pr={pr} db={db} onDone={refresh} /> : null}
      <Section title={funds ? 'Stages' : 'Milestones'}>
        <Steps items={(db.milestones ?? []).map((m: Any) => ({ label: `${m.name} · ${formatMoney(m.amount)}`, state: m.status === 'paid' ? 'done' : m.needs_client || ['submitted', 'inspected', 'evidence_checked', 'approved', 'in_progress'].includes(m.status) ? 'now' : 'next', detail: words(m.status) }))} />
        <div className="stack" style={{ gap: 6 }}>{(db.milestones ?? []).map((m: Any) => <Link key={m.id} href={`/projects/milestones/${m.id}`} className="btn btn-ghost btn-sm" style={{ justifyContent: 'space-between' }}><span>{m.name}</span>{m.needs_client ? <Chip tone="orange">Needs you</Chip> : <span className="mono muted">{words(m.status)}</span>}</Link>)}</div>
      </Section>
      {(db.inspections ?? []).length ? (
        <Section title="Inspections">
          {db.inspections.map((i: Any) => <div key={i.id} className="card"><div className="spread"><strong>{i.milestone}</strong><Chip>{words(i.outcome || i.status)}</Chip></div><div className="muted" style={{ fontSize: 14 }}>{i.inspector} · {i.recorded_at ? <When value={i.recorded_at} /> : `planned ${i.scheduled_for}`}{Number(i.defect_value?.amount) ? ` · defects ${formatMoney(i.defect_value)}` : ''}</div></div>)}
        </Section>
      ) : null}
      {myDefects.length ? (
        <Section title="Defects">
          {myDefects.map((x: Any) => (
            <div key={x.id} className="card stack" style={{ gap: 4 }}>
              <div className="spread"><strong>{x.description}</strong><Money value={x.value} /></div>
              <span className="muted" style={{ fontSize: 14 }}>{words(x.status)}. The value is held back until the inspector confirms the fix.</span>
              <div className="row">{(x.photo_evidence_ids ?? []).map((e: string) => <EvidenceLink key={e} id={e} label="Photo" variant="preview" />)}</div>
            </div>
          ))}
        </Section>
      ) : null}
      {(db.payments ?? []).length ? (
        <Section title="Payments">
          {db.payments.map((x: Any) => <Link key={x.id} href={`/projects/payments/${x.id}`} className="card card-link spread"><span>{x.label}<div className="muted" style={{ fontSize: 14 }}>{x.payee} · {words(x.status)}</div></span><Money value={x.amount} /></Link>)}
        </Section>
      ) : null}
      {(vars.data ?? []).length ? (
        <Section title="Changes to the work">
          {(vars.data ?? []).map((v: Any) => <Link key={v.id} href={`/projects/variations/${v.id}`} className="card card-link spread"><span>{v.description}<div className="muted" style={{ fontSize: 14 }}>{words(v.status)}</div></span><Money value={v.cost_change} /></Link>)}
        </Section>
      ) : null}
      {(db.photo_timeline ?? []).length ? (
        <Section title="Photos">
          {db.photo_timeline.slice(-12).reverse().map((ph: Any) => <div key={ph.evidence_id} className="card spread"><span>{ph.milestone} · {words(ph.role)} · <When value={ph.captured_at} />{ph.app_captured ? ' · taken in Tenmina Field' : ''}</span><EvidenceLink id={ph.evidence_id} label="See" variant="preview" /></div>)}
        </Section>
      ) : null}
      <ProblemBox error={a.error} />
      <div className="row">
        {pr.asset_id ? <Link className="btn btn-ghost" href={`/property/assets/${pr.asset_id}`}>The plot</Link> : null}
        {pr.report_id ? <Link className="btn btn-ghost" href={`/property/reports/${pr.report_id}`}>The report</Link> : null}
        {!funds && pr.status === 'active' ? <Button variant="ghost" busy={a.busy === 'x'} onClick={() => a.run('x', () => a.post<Any>(`/v1/projects/${id}/extra-inspections`, {}), 'Extra inspection ordered', (o) => { if (o?.id) location.href = `/property/orders/${o.id}`; })}>Order an extra inspection</Button> : null}
        <Link className="btn btn-ghost" href={`/property/disputes/new?project=${id}`}>Open a dispute</Link>
      </div>
      {a.toast}
    </div>
  );
}

function SetupSteps({ pr, onDone }: { pr: Any; onDone: () => void }) {
  const a = useAction();
  const boq = useGet<Any>(`/v1/projects/${pr.id}/boq`, undefined, { shouldRetryOnError: false });
  return (
    <Section title="Setting up">
      <Steps items={[
        { label: 'Bill of quantities from the quantity surveyor', state: boq.data ? 'done' : 'now' },
        { label: 'You approve the budget', state: pr.budget_approved_at ? 'done' : boq.data ? 'now' : 'next' },
        { label: 'Contract signed', state: pr.contract_signed_at ? 'done' : 'next' },
        { label: 'Work starts', state: pr.started_at ? 'done' : 'next' },
      ]} />
      {boq.data && !pr.budget_approved_at ? (
        <div className="card stack">
          <div className="spread"><strong>Bill of quantities</strong><Money value={boq.data.total ?? boq.data.amount} /></div>
          {(boq.data.split ?? []).map((s: Any) => <div key={s.key} className="spread"><span>{s.name}</span><span className="mono">{s.share_pct}%</span></div>)}
          <Button variant="action" busy={!!a.busy} onClick={() => a.run('b', () => a.post(`/v1/projects/${pr.id}/budget-approval`), 'Budget approved', onDone)}>Approve the budget</Button>
        </div>
      ) : null}
      <ProblemBox error={a.error} />
    </Section>
  );
}

function Funds({ pr, db, onDone }: { pr: Any; db: Any; onDone: () => void }) {
  const f = db.funds ?? {};
  const sup = useGet<Any[]>(`/v1/projects/${pr.id}/suppliers`);
  const inv = useGet<Any[]>(`/v1/projects/${pr.id}/invoices`);
  const agr = useGet<Any>(`/v1/projects/${pr.id}/agreement`, undefined, { shouldRetryOnError: false });
  const a = useAction();
  const [dlg, setDlg] = useState<null | 'sup' | 'inv'>(null);
  const [s, setS] = useState({ name: '', what_they_supply: '', contact_phone: '', bank_name: '', account_number: '' });
  const [iv, setIv] = useState({ supplier_id: '', milestone_id: '', number: '', amount: '', description: '' });
  const [file, setFile] = useState<File | null>(null);
  const cur = pr.budget?.currency;
  async function submitInvoice() {
    await a.run('inv', async () => {
      if (!file) throw new Error('Choose the invoice file.');
      const ev = await uploadEvidence(a.client, file, { type: 'prj_supplier', id: iv.supplier_id, role: 'invoice' });
      return a.post(`/v1/projects/${pr.id}/invoices`, { supplier_id: iv.supplier_id, milestone_id: iv.milestone_id, number: iv.number, amount: { amount: iv.amount, currency: cur }, description: iv.description, evidence_ids: [ev.id] });
    }, 'Invoice sent for checking', () => { setDlg(null); inv.mutate(); onDone(); });
  }
  return (
    <>
      <div className="card"><strong>{f.disclaimer}</strong></div>
      {agr.data && !agr.data.accepted_at ? (
        <section className="needs-you" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
          <div><div className="label" style={{ color: '#0b0b0b' }}>Needs you</div><strong>Read and accept the project agreement</strong><p style={{ whiteSpace: 'pre-wrap', fontSize: 14, margin: '6px 0 0' }}>{agr.data.text}</p></div>
          <Button variant="dark" busy={a.busy === 'agr'} onClick={() => a.run('agr', () => a.post(`/v1/projects/${pr.id}/agreement`), 'Accepted', () => { agr.mutate(); onDone(); })}>I accept</Button>
        </section>
      ) : agr.data?.accepted_at ? <Proof>Agreement accepted <When value={agr.data.accepted_at} /></Proof> : null}
      {(f.funding_blockers ?? []).length ? <div className="card"><strong>Before the money can move</strong><ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>{f.funding_blockers.map((b: Any, i: number) => <li key={i}>{b.message ?? String(b)}</li>)}</ul></div> : null}
      <Section title="Suppliers" action={<Button variant="ghost" size="sm" onClick={() => setDlg('sup')}>Add</Button>}>
        {(sup.data ?? []).map((x: Any) => <div key={x.id} className="card spread"><span><strong>{x.name}</strong><div className="muted" style={{ fontSize: 14 }}>{x.what_they_supply || x.bank_name}{x.account_last4 ? ` · account ending ${x.account_last4}` : ''}</div></span>{x.payee_verified ? <Proof>Verified</Proof> : <Chip>{words(x.status)}</Chip>}</div>)}
      </Section>
      <Section title="Invoices" action={(sup.data ?? []).length ? <Button variant="ghost" size="sm" onClick={() => setDlg('inv')}>Add an invoice</Button> : undefined}>
        {(inv.data ?? []).length ? (inv.data ?? []).map((x: Any) => <div key={x.id} className="card spread"><span>{x.supplier_name ?? 'Supplier'} · <span className="mono">{x.number}</span><div className="muted" style={{ fontSize: 14 }}>{words(x.status)}</div></span><Money value={x.amount} /></div>) : <p className="muted">No invoices yet. Invoices are paid only to named, checked suppliers, and only once.</p>}
      </Section>
      <ProblemBox error={a.error} />
      <ActionDialog open={dlg === 'sup'} onClose={() => setDlg(null)} title="Add a supplier" submit="Add and ask Tenmina to check" busy={a.busy === 'sup'} error={a.error}
        onSubmit={() => a.run('sup', () => a.post(`/v1/projects/${pr.id}/suppliers`, s), 'Added', () => { setDlg(null); sup.mutate(); onDone(); })}>
        <Field label="Business name"><Input value={s.name} onChange={(e) => setS({ ...s, name: e.target.value })} required /></Field>
        <Field label="What they supply"><Input value={s.what_they_supply} onChange={(e) => setS({ ...s, what_they_supply: e.target.value })} /></Field>
        <Field label="Phone"><Input type="tel" value={s.contact_phone} onChange={(e) => setS({ ...s, contact_phone: e.target.value })} /></Field>
        <Field label="Bank"><Input value={s.bank_name} onChange={(e) => setS({ ...s, bank_name: e.target.value })} /></Field>
        <Field label="Account number"><Input inputMode="numeric" value={s.account_number} onChange={(e) => setS({ ...s, account_number: e.target.value })} /></Field>
      </ActionDialog>
      <ActionDialog open={dlg === 'inv'} onClose={() => setDlg(null)} title="Add an invoice" submit="Send for checking" busy={a.busy === 'inv'} error={a.error} onSubmit={submitInvoice}>
        <Field label="Supplier"><Select value={iv.supplier_id} onChange={(e) => setIv({ ...iv, supplier_id: e.target.value })} required><option value="">Choose</option>{(sup.data ?? []).map((x: Any) => <option key={x.id} value={x.id}>{x.name}</option>)}</Select></Field>
        <Field label="Stage"><Select value={iv.milestone_id} onChange={(e) => setIv({ ...iv, milestone_id: e.target.value })} required><option value="">Choose</option>{(db.milestones ?? []).map((m: Any) => <option key={m.id} value={m.id}>{m.name}</option>)}</Select></Field>
        <Field label="Invoice number"><Input value={iv.number} onChange={(e) => setIv({ ...iv, number: e.target.value })} required /></Field>
        <Field label={`Amount (${cur})`}><Input inputMode="decimal" value={iv.amount} onChange={(e) => setIv({ ...iv, amount: e.target.value.replace(/[^\d.]/g, '') })} required /></Field>
        <Field label="What for"><Input value={iv.description} onChange={(e) => setIv({ ...iv, description: e.target.value })} /></Field>
        <label className="field"><span>The invoice file</span><input type="file" accept="image/*,application/pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></label>
      </ActionDialog>
    </>
  );
}
