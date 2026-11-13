'use client';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { Button, Field, Input, KV, Money, ProblemBox, Skeleton, Textarea, When, useGet } from '@tenmina/web-ui';
import { ActionDialog, Item, PageHead, Proof, Section, StepUpButton, list, money, useAction, useCountry, words, type Any } from '@/components/kit';

/** W-29 and SCR-PTL-44: the care plan, its visits, the standing approval and the carer as payee. */
export default function CarePlan() {
  const { id } = useParams<{ id: string }>();
  const country = useCountry();
  const q = useGet<Any>(`/v1/care-plans/${id}`);
  const visits = useGet<Any>('/v1/care-visits');
  const st = useGet<Any>(`/v1/care-plans/${id}/statement`);
  const terms = useGet<Any>(q.data?.needs_client === 'activate' ? '/v1/catalogue/terms' : null, { country: country.code });
  const a = useAction();
  const [sa, setSa] = useState(false);
  const [max, setMax] = useState('');
  const [code, setCode] = useState('');
  const [stop, setStop] = useState<null | 'pause' | 'end'>(null);
  const [reason, setReason] = useState('');
  if (q.isLoading) return <Skeleton lines={6} />;
  if (!q.data) return <ProblemBox error={q.error} />;
  const p = q.data;
  const refresh = () => q.mutate();
  const days = Array.isArray(p.schedule?.weekly) ? p.schedule.weekly : String(p.schedule?.weekly ?? '').replace(/[[\]"]/g, '').split(',').filter(Boolean);
  return (
    <div className="stack" style={{ gap: 18 }}>
      <PageHead back={{ href: '/family', label: 'Family' }} label={`${p.reference} · ${words(p.status)}`} title={`Care visits for ${p.family_member?.full_name}`} sub={p.address} />
      {p.needs_client === 'activate' ? (
        <section className="needs-you" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
          <div><div className="label" style={{ color: '#0b0b0b' }}>Needs you</div><strong>{p.carer?.name} is ready to visit. Accept the terms to start.</strong></div>
          {terms.data ? <div style={{ fontSize: 14 }}>{terms.data.terms.text}</div> : null}
          <StepUpButton label="Accept and start the visits" variant="dark" onRun={() => a.post(`/v1/care-plans/${id}/activate`, { terms_version: terms.data?.terms_version ?? '', scope_version: terms.data?.scope_version ?? '' }).then(refresh)} />
        </section>
      ) : null}
      {p.needs_client === 'approve_carer' ? (
        <section className="needs-you" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
          <div><div className="label" style={{ color: '#0b0b0b' }}>Needs you</div><strong>Agree {p.carer?.name} as the payee for visits</strong><div style={{ fontSize: 14 }}>The bank pays the carer only after you agree, and only for confirmed visits.</div></div>
          <StepUpButton label="Agree the carer as payee" variant="dark" onRun={() => a.post(`/v1/care-plans/${id}/carer-approvals`).then(refresh)} />
        </section>
      ) : null}
      <KV items={[
        ['Carer', p.carer ? `${p.carer.name} · ${words(p.carer.status)}` : 'Tenmina is choosing a vetted carer'],
        ['Days', days.map((d: string) => words(d)).join(', ') || '—'],
        ['Time', p.schedule?.window],
        ['Fee per visit', <Money key="f" value={p.visit_fee} />],
        ['Confirmed by', (p.confirmers ?? []).map((c: Any) => c.full_name).join(', ')],
        ['Next visit', p.next_visit_at ? <When key="n" value={p.next_visit_at} withTime /> : '—'],
      ]} />
      <Section title="Tasks">
        {(p.items ?? []).map((it: Any) => <div key={it.id} className="card"><strong>{it.label || words(it.kind)}</strong>{it.photo_required ? <span className="muted"> · photo agreed</span> : null}{it.instructions ? <div className="muted" style={{ fontSize: 14 }}>{it.instructions}</div> : null}</div>)}
      </Section>
      <Section title="Paying the carer">
        {p.standing_approval && p.standing_approval.status === 'active' ? (
          <div className="card stack">
            <Proof>Standing approval up to <Money value={money(p.standing_approval.monthly_max, p.standing_approval.currency)} /> a month</Proof>
            <span className="muted" style={{ fontSize: 14 }}>Confirmed visits are paid without asking you each time, up to this amount. Two Tenmina staff still approve each payment.</span>
            <Button variant="ghost" size="sm" busy={a.busy === 'w'} onClick={() => a.run('w', () => a.post(`/v1/care-plans/${id}/standing-approvals`, undefined, 'DELETE'), 'Withdrawn', refresh)}>Withdraw it</Button>
          </div>
        ) : (
          <div className="card stack">
            <span>Each visit payment waits for your approval. You can give a standing approval up to a monthly amount instead.</span>
            <Button variant="ghost" onClick={() => setSa(true)}>Give a standing approval</Button>
          </div>
        )}
        {p.fee_order_id ? <Link className="btn btn-ghost" href={`/property/orders/${p.fee_order_id}`}>Tenmina&apos;s fee for the plan{p.fee_paid_at ? ' (paid)' : ''}</Link> : null}
        {st.data ? <div className="card"><div className="label">Visits by status</div>{Object.entries(st.data.by_status ?? {}).map(([k, v]: [string, Any]) => <div key={k} className="spread"><span>{words(k)} ({v.count})</span><span className="mono">{p.visit_fee?.currency} {v.amount}</span></div>)}</div> : null}
      </Section>
      <Section title="Visits">
        {list(visits.data).filter((v: Any) => v.plan === id).length ? list(visits.data).filter((v: Any) => v.plan === id).map((v: Any) => <Item key={v.id} href={`/family/visits/${v.id}`} meta={new Date(v.window_start).toLocaleString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })} title={v.carer?.name ?? 'Visit'} sentence={`${words(v.status)}${v.confirmed_at ? ', confirmed' : ''}`} />) : <p className="muted">No visits yet.</p>}
      </Section>
      <ProblemBox error={a.error} />
      <div className="row">
        {p.status === 'active' ? <Button variant="ghost" onClick={() => setStop('pause')}>Pause visits</Button> : null}
        {p.status === 'paused' ? <Button variant="ghost" busy={a.busy === 'r'} onClick={() => a.run('r', () => a.post(`/v1/care-plans/${id}/resume`), 'Resumed', refresh)}>Resume visits</Button> : null}
        {['active', 'paused', 'draft'].includes(p.status) ? <Button variant="ghost" onClick={() => setStop('end')}>End the plan</Button> : null}
      </div>
      <ActionDialog ink open={sa} onClose={() => setSa(false)} title="Standing approval" submit="Give the approval" busy={a.busy === 'sa'} error={a.error} disabled={!max || code.length !== 6}
        onSubmit={() => a.run('sa', () => a.post(`/v1/care-plans/${id}/standing-approvals`, { monthly_max: max, code }), 'Standing approval given', () => { setSa(false); refresh(); })}>
        <Field label={`Up to this much a month (${p.visit_fee?.currency})`}><Input inputMode="decimal" value={max} onChange={(e) => setMax(e.target.value.replace(/[^\d.]/g, ''))} /></Field>
        <Field label="Code from your authenticator app"><Input inputMode="numeric" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} /></Field>
      </ActionDialog>
      <ActionDialog open={!!stop} onClose={() => setStop(null)} title={stop === 'end' ? 'End the plan' : 'Pause visits'} submit={stop === 'end' ? 'End' : 'Pause'} busy={a.busy === 's'} error={a.error}
        onSubmit={() => a.run('s', () => a.post(`/v1/care-plans/${id}/${stop}`, { reason }), 'Done', () => { setStop(null); refresh(); })}>
        <Field label="Why"><Textarea value={reason} onChange={(e) => setReason(e.target.value)} required /></Field>
      </ActionDialog>
      {a.toast}
    </div>
  );
}
