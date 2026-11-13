'use client';
/* One project for the contractor: milestones with what each needs and why it waits; variations agreed
   in writing before the work (RUL-19, US-BLD-008); payments from the bank to your verified account. */
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { Blocked, Button, Card, Chip, Field, Input, Money, ProblemBox, Select, Skeleton, Status, Textarea, When, useGet } from '@tenmina/web-ui';
import { PageHead, PayeeLine, Section, useAct, useApi, words, type Page, items } from '@/components/roles/kit';
import { PaymentCard } from '@/components/roles/PaymentCard';
import { MILESTONE_TEXT, type Milestone, type Project, type ProjectPayment, type Variation } from '@/components/roles/build';

export default function ContractorProject() {
  const { id } = useParams<{ id: string }>();
  const p = useGet<Project>(`/v1/projects/${id}`);
  const ms = useGet<Page<Milestone>>('/v1/milestones', { project_id: id });
  const vs = useGet<Variation[]>(`/v1/projects/${id}/variations`);
  const pays = useGet<ProjectPayment[]>(`/v1/projects/${id}/payments`);
  const api = useApi();
  const act = useAct();
  const [mid, setMid] = useState('');
  const [desc, setDesc] = useState('');
  const [cost, setCost] = useState('');
  const [days, setDays] = useState('0');
  const [decline, setDecline] = useState<Record<string, string>>({});
  if (p.isLoading) return <Skeleton lines={8} />;
  if (p.error || !p.data) return <ProblemBox error={p.error ?? 'Project not found.'} />;
  const prj = p.data;
  const milestones = [...items(ms.data)].sort((a, b) => a.seq - b.seq);
  const cur = prj.budget?.currency ?? 'GHS';

  return (
    <div className="stack">
      <PageHead back={{ href: '/contractor', label: 'Projects' }} label={words(prj.type)} title={prj.title} />
      <div className="row"><Status value={prj.status} />{prj.budget ? <Money value={prj.budget} /> : null}</div>
      {prj.status_reason ? <div className="banner-info">{prj.status_reason}</div> : null}

      <Section title="Milestones">
        <div className="banner-info">Send milestone photos and video from Tenmina Field. The app seals each capture with the time and place, so no old or borrowed photo is accepted (RUL-08).</div>
        {ms.isLoading ? <Skeleton /> : null}
        {milestones.map((m) => (
          <Card key={m.id} className="stack">
            <div className="spread"><div><div className="label">Stage {m.seq} · {m.share_pct}%</div><strong>{m.name}</strong></div><Money value={m.amount} /></div>
            <div className="row">{m.status === 'paid' ? <Chip tone="lime">✓ Paid</Chip> : <Status value={m.status} needsYou={m.accepts_submissions || m.status === 'returned'} />}{m.paid_at ? <span className="muted"><When value={m.paid_at} /></span> : null}</div>
            <span style={{ fontSize: 14 }}>{MILESTONE_TEXT[m.status] ?? words(m.status)}</span>
            {m.freeze_kind ? <Blocked title="Payments frozen">A dispute or review is open on this project.</Blocked> : null}
            {m.waiting_reason && !m.accepts_submissions && m.status === 'not_started' ? <span className="muted" style={{ fontSize: 14 }}>{m.waiting_reason}</span> : null}
            {m.return_reasons.length ? <div><strong>Fix before you resend:</strong><ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>{m.return_reasons.map((r, n) => <li key={n}>{r}</li>)}</ul></div> : null}
            {m.accepts_submissions || m.status === 'returned' ? (
              <div>
                <div className="label">Capture in Tenmina Field</div>
                {m.required_evidence.map((e) => <div key={e.key} className="check-row"><span className="tick" aria-hidden /> <span>{e.label} <span className="muted">({e.media})</span></span></div>)}
              </div>
            ) : null}
          </Card>
        ))}
      </Section>

      <Section title="Variations">
        <p className="muted" style={{ margin: 0 }}>A change of scope is agreed in writing by you and the client before the work starts (RUL-19).</p>
        {(vs.data ?? []).map((v) => (
          <Card key={v.id} className="stack">
            <div className="spread"><strong>{v.description}</strong><Status value={v.status} needsYou={v.status === 'proposed' && !v.contractor_agreed_at} /></div>
            <span>Cost change <Money value={v.cost_change} /> · {v.time_effect_days} days</span>
            <span className="muted" style={{ fontSize: 14 }}>You: {v.contractor_agreed_at ? <>agreed <When value={v.contractor_agreed_at} /></> : 'not yet'} · Client: {v.client_agreed_at ? <>agreed <When value={v.client_agreed_at} /></> : 'not yet'}</span>
            {v.decline_reason ? <span>Declined: {v.decline_reason}</span> : null}
            {v.status === 'proposed' && !v.contractor_agreed_at ? (
              <>
                <Button variant="action" busy={act.busy === v.id} onClick={() => act.run(v.id, async () => { await api('POST', `/v1/variations/${v.id}/agreements`, { decision: 'agree' }); await vs.mutate(); }, 'Agreed in writing.')}>I agree to this change</Button>
                <Field label="Or decline: say why"><Input value={decline[v.id] ?? ''} onChange={(e) => setDecline({ ...decline, [v.id]: e.target.value })} /></Field>
                <Button variant="ghost" disabled={!(decline[v.id] ?? '').trim()} busy={act.busy === 'd' + v.id} onClick={() => act.run('d' + v.id, async () => { await api('POST', `/v1/variations/${v.id}/agreements`, { decision: 'decline', reason: decline[v.id] }); await vs.mutate(); }, 'Declined.')}>Decline</Button>
              </>
            ) : null}
          </Card>
        ))}
        {prj.status === 'active' ? (
          <Card className="stack">
            <h3 style={{ margin: 0 }}>Propose a variation</h3>
            <Field label="Milestone"><Select value={mid} onChange={(e) => setMid(e.target.value)}><option value="">Choose</option>{milestones.filter((m) => m.status !== 'paid').map((m) => <option key={m.id} value={m.id}>{m.seq}. {m.name}</option>)}</Select></Field>
            <Field label="What changes"><Textarea value={desc} onChange={(e) => setDesc(e.target.value)} /></Field>
            <Field label={`Cost change (${cur}, negative for less)`}><Input inputMode="decimal" value={cost} onChange={(e) => setCost(e.target.value)} /></Field>
            <Field label="Extra days"><Input type="number" value={days} onChange={(e) => setDays(e.target.value)} /></Field>
            <Button variant="dark" disabled={!mid || !desc.trim() || !cost} busy={act.busy === 'new'} onClick={() => act.run('new', async () => {
              await api('POST', `/v1/projects/${id}/variations`, { milestone_id: mid, description: desc, cost_change: { amount: cost, currency: cur }, time_effect_days: Number(days) || 0 });
              setDesc(''); setCost(''); await vs.mutate();
            }, 'Proposed. The client agrees or declines in writing.')}>Propose</Button>
          </Card>
        ) : null}
      </Section>

      <Section title="Payments">
        {(pays.data ?? []).length ? (pays.data ?? []).map((x) => <PaymentCard key={x.id} x={x} onDone={() => pays.mutate()} />) : <p className="muted">No payments yet.</p>}
      </Section>
      <ProblemBox error={act.error} />
      {act.toast}
    </div>
  );
}
