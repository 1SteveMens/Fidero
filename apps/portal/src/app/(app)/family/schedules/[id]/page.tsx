'use client';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Button, Field, Input, ProblemBox, Select, Skeleton, useGet } from '@tenmina/web-ui';
import { Item, PageHead, Section, list, useAction, useCountry, words, type Any } from '@/components/kit';

/** SCR-PTL-41: a recurring fee schedule. We remind you and ask for your approval each time; nothing is paid automatically. */
export default function Schedule() {
  const { id } = useParams<{ id: string }>();
  const isNew = id === 'new';
  const router = useRouter();
  const country = useCountry();
  const q = useGet<Any>(isNew ? null : `/v1/fee-schedules/${id}`);
  const inst = useGet<Any>('/v1/institutions', { status: 'verified' });
  const fams = useGet<Any>('/v1/family-members');
  const bills = useGet<Any>(isNew ? null : '/v1/invoices');
  const [f, setF] = useState<Any>({ institution_id: '', family_member_id: '', period: 'term', amount: '', next_due_on: '', reminder_lead_days: 14, label: '' });
  useEffect(() => { if (q.data) setF({ ...f, amount: q.data.expected?.amount, next_due_on: q.data.next_due_on, reminder_lead_days: q.data.reminder_lead_days, label: q.data.label }); }, [q.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const a = useAction();
  if (!isNew && q.isLoading) return <Skeleton lines={5} />;
  const s = q.data;
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  const expected = { amount: f.amount, currency: s?.expected?.currency || country.currency };
  return (
    <form className="stack" style={{ gap: 16 }} onSubmit={(e) => {
      e.preventDefault();
      if (isNew) a.run('go', () => a.post<Any>('/v1/fee-schedules', { institution_id: f.institution_id, family_member_id: f.family_member_id, period: f.period, expected, next_due_on: f.next_due_on, reminder_lead_days: Number(f.reminder_lead_days), label: f.label }), undefined, (r) => router.push(`/family/schedules/${r.id}`));
      else a.run('go', () => a.post(`/v1/fee-schedules/${id}`, { expected, next_due_on: f.next_due_on, reminder_lead_days: Number(f.reminder_lead_days), label: f.label }, 'PATCH'), 'Saved', () => q.mutate());
    }}>
      <PageHead back={{ href: '/family', label: 'Family' }} label={isNew ? 'Regular fees' : `${s?.institution_name} · every ${s?.period} · ${words(s?.status)}`} title={isNew ? 'Set up regular fees' : s?.label || 'Regular fees'} sub="We remind you before each due date and ask for your approval every time. Nothing is ever paid without it." />
      {isNew ? <>
        <Field label="Institution (verified only)"><Select value={f.institution_id} onChange={set('institution_id')} required><option value="">Choose</option>{list(inst.data).map((i: Any) => <option key={i.id} value={i.id}>{i.legal_name}</option>)}</Select></Field>
        <Field label="For"><Select value={f.family_member_id} onChange={set('family_member_id')} required><option value="">Choose</option>{list(fams.data).map((m: Any) => <option key={m.id} value={m.id}>{m.full_name}</option>)}</Select></Field>
        <Field label="How often"><Select value={f.period} onChange={set('period')}><option value="term">Each term</option><option value="month">Each month</option><option value="quarter">Each quarter</option></Select></Field>
      </> : null}
      <Field label="Name (optional)"><Input value={f.label} onChange={set('label')} /></Field>
      <Field label={`Expected amount (${expected.currency})`}><Input inputMode="decimal" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value.replace(/[^\d.]/g, '') })} required /></Field>
      <Field label="Next due date"><Input type="date" value={f.next_due_on} onChange={set('next_due_on')} required /></Field>
      <Field label="Remind me this many days before"><Input type="number" min={1} max={60} value={f.reminder_lead_days} onChange={set('reminder_lead_days')} /></Field>
      <ProblemBox error={a.error} />
      <Button variant="primary" type="submit" busy={a.busy === 'go'}>{isNew ? 'Set up' : 'Save'}</Button>
      {s ? (
        <div className="row">
          {s.status === 'active' ? <Button type="button" variant="ghost" busy={a.busy === 'p'} onClick={() => a.run('p', () => a.post(`/v1/fee-schedules/${id}`, { status: 'paused' }, 'PATCH'), 'Paused', () => q.mutate())}>Pause</Button> : null}
          {s.status === 'paused' ? <Button type="button" variant="ghost" busy={a.busy === 'p'} onClick={() => a.run('p', () => a.post(`/v1/fee-schedules/${id}`, { status: 'active' }, 'PATCH'), 'Resumed', () => q.mutate())}>Resume</Button> : null}
          {s.status !== 'ended' ? <Button type="button" variant="ghost" busy={a.busy === 'e'} onClick={() => a.run('e', () => a.post(`/v1/fee-schedules/${id}`, { status: 'ended' }, 'PATCH'), 'Ended', () => q.mutate())}>End</Button> : null}
          <Link className="btn btn-ghost" href={`/family/members/${s.family_member}`}>Statement</Link>
        </div>
      ) : null}
      {s ? (
        <Section title="Bills from this schedule">
          {list(bills.data).filter((b: Any) => b.schedule === id).map((b: Any) => <Item key={b.id} href={`/family/invoices/${b.id}`} title={b.description || b.institution_reference} sentence={b.status_text} amount={b.amount} />)}
        </Section>
      ) : null}
      {a.toast}
    </form>
  );
}
