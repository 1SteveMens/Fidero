'use client';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useState } from 'react';
import { Button, Field, Input, ProblemBox, Select, Textarea, useGet } from '@tenmina/web-ui';
import { PageHead, Section, list, useAction, useCountry, words, type Any } from '@/components/kit';

const KINDS = ['medicine', 'meal', 'reading', 'companionship', 'transport', 'groceries', 'hospital_visit', 'other'];
const DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];

/** W-29 · SCR-PTL-43: care plan setup. Address, visits per week, tasks, agreed photos, who confirms. */
function NewCare() {
  const sp = useSearchParams();
  const router = useRouter();
  const country = useCountry();
  const fams = useGet<Any>('/v1/family-members');
  const members = list(fams.data);
  const [fm, setFm] = useState(sp.get('member') || '');
  const [days, setDays] = useState<string[]>(['tue', 'fri']);
  const [window, setWindow] = useState({ from: '09:00', to: '12:00' });
  const [items, setItems] = useState<Any[]>([{ key: 'company', kind: 'companionship', label: 'Sit and talk with her', photo_required: false, photo_allowed: false, reading_required: false }]);
  const [confirmers, setConfirmers] = useState<string[]>([]);
  const [fee, setFee] = useState('');
  const [channel, setChannel] = useState('sms');
  const [notes, setNotes] = useState('');
  const [address, setAddress] = useState('');
  const a = useAction();
  const member = members.find((m: Any) => m.id === fm);
  const setItem = (i: number, k: string, v: unknown) => setItems(items.map((x, j) => (j === i ? { ...x, [k]: v } : x)));
  async function submit() {
    await a.run('go', () => a.post<Any>('/v1/care-plans', {
      family_member_id: fm, items: items.map((x, i) => ({ ...x, key: x.key || `task${i + 1}`, photo_allowed: x.photo_allowed || x.photo_required })),
      schedule: { weekly: days, window: `${window.from}-${window.to}` }, visit_fee: { amount: fee, currency: country.currency },
      confirmers, address: address || member?.address || '', confirm_channel: channel, notes,
      point: member?.latitude ? { lat: member.latitude, lng: member.longitude } : undefined,
    }), undefined, (p) => router.push(`/family/care/${p.id}`));
  }
  return (
    <form className="stack" style={{ gap: 16 }} onSubmit={(e) => { e.preventDefault(); submit(); }}>
      <PageHead back={{ href: '/family', label: 'Family' }} label="Care visits" title="Arrange care visits" sub="A vetted carer visits. Each visit is confirmed by the family before the carer is paid. Silence is never confirmation." />
      <Field label="Who for"><Select value={fm} onChange={(e) => setFm(e.target.value)} required><option value="">Choose</option>{members.map((m: Any) => <option key={m.id} value={m.id}>{m.full_name}</option>)}</Select></Field>
      <Field label="Address for visits"><Input value={address || member?.address || ''} onChange={(e) => setAddress(e.target.value)} /></Field>
      <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
        <legend className="label" style={{ marginBottom: 8 }}>Days</legend>
        <div className="tile-btns">{DAYS.map((d) => <button type="button" key={d} aria-pressed={days.includes(d)} className={`btn ${days.includes(d) ? 'btn-dark' : 'btn-ghost'}`} style={{ minWidth: 56 }} onClick={() => setDays(days.includes(d) ? days.filter((x) => x !== d) : [...days, d])}>{words(d)}</button>)}</div>
      </fieldset>
      <div className="row"><Field label="From"><Input type="time" value={window.from} onChange={(e) => setWindow({ ...window, from: e.target.value })} /></Field><Field label="To"><Input type="time" value={window.to} onChange={(e) => setWindow({ ...window, to: e.target.value })} /></Field></div>
      <Section title="What the carer does">
        {items.map((it, i) => (
          <div key={i} className="card stack">
            <Field label="Task"><Select value={it.kind} onChange={(e) => setItem(i, 'kind', e.target.value)}>{KINDS.map((k) => <option key={k} value={k}>{words(k)}</option>)}</Select></Field>
            <Field label="In your words"><Input value={it.label} onChange={(e) => setItem(i, 'label', e.target.value)} /></Field>
            <label className="row" style={{ flexWrap: 'nowrap' }}><input type="checkbox" checked={it.photo_required} onChange={(e) => setItem(i, 'photo_required', e.target.checked)} style={{ width: 22, height: 22 }} /> A photo is agreed for this task</label>
            {items.length > 1 ? <Button type="button" variant="ghost" size="sm" onClick={() => setItems(items.filter((_, j) => j !== i))}>Remove</Button> : null}
          </div>
        ))}
        <Button type="button" variant="ghost" onClick={() => setItems([...items, { key: '', kind: 'other', label: '', photo_required: false, photo_allowed: false, reading_required: false }])}>Add a task</Button>
      </Section>
      <Section title="Who confirms each visit">
        <p className="muted" style={{ margin: 0, fontSize: 14 }}>They get a code on their own phone. The carer never sees it.</p>
        {members.filter((m: Any) => m.may_confirm_visits).map((m: Any) => (
          <label key={m.id} className="row" style={{ flexWrap: 'nowrap' }}><input type="checkbox" checked={confirmers.includes(m.id)} onChange={(e) => setConfirmers(e.target.checked ? [...confirmers, m.id] : confirmers.filter((x) => x !== m.id))} style={{ width: 22, height: 22 }} /> {m.full_name}</label>
        ))}
        <Field label="Send the code by"><Select value={channel} onChange={(e) => setChannel(e.target.value)}><option value="sms">SMS</option><option value="whatsapp">WhatsApp</option><option value="app">The Tenmina app</option></Select></Field>
      </Section>
      <Field label={`Carer's fee per visit (${country.currency})`} hint="As agreed with your case manager. Paid only after the visit is confirmed."><Input inputMode="decimal" value={fee} onChange={(e) => setFee(e.target.value.replace(/[^\d.]/g, ''))} required /></Field>
      <Field label="Notes for the carer"><Textarea value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
      <ProblemBox error={a.error} />
      <Button variant="primary" type="submit" busy={!!a.busy} disabled={!fm || !days.length || !confirmers.length}>Set up the plan</Button>
    </form>
  );
}

export default function Page() { return <Suspense><NewCare /></Suspense>; }
