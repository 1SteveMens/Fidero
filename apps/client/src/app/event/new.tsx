import { useState } from 'react';
import { router } from 'expo-router';
import { space } from '@tenmina/tokens';
import { Button, Choice, Label, Panel, Screen, T } from '@tenmina/ui';
import { Field, ProblemBox, useAction, useGet, words } from '@tenmina/mobile';
import type { Home } from '../../lib';
import { amountOnly, useCountry } from '../../components/country';

const KINDS = ['funeral', 'wedding', 'naming', 'anniversary', 'other'] as const;

/** Today plus n days, as YYYY-MM-DD. */
function isoDay(n: number) {
  const d = new Date(Date.now() + n * 86_400_000);
  return d.toISOString().slice(0, 10);
}

/**
 * Plan an event in the app (SCR-PTL-53, FR-EVT-001): the partner bank holds the
 * budget and pays each checked vendor only against their invoice and the
 * family's confirmation of delivery, after the client and two staff approve.
 */
export default function NewEvent() {
  const country = useCountry();
  const home = useGet<Home>('/v1/home');
  const act = useAction();
  const [f, setF] = useState({ kind: 'funeral', name: '', event_date: isoDay(30), locality: '', budget: '', confirmer: '' });
  const set = (k: keyof typeof f) => (v: string) => setF((x) => ({ ...x, [k]: v }));
  const dateOk = /^\d{4}-\d{2}-\d{2}$/.test(f.event_date) && !Number.isNaN(Date.parse(f.event_date));
  const ready = !!f.name.trim() && dateOk && Number(f.budget) > 0 && !!country.currency;
  const fams = home.data?.family_members ?? [];

  async function create() {
    const r = await act.run<{ id: string }>('POST', '/v1/events', {
      country: country.code,
      kind: f.kind,
      name: f.name.trim(),
      event_date: f.event_date,
      locality: f.locality.trim(),
      budget: { amount: f.budget, currency: country.currency },
      confirmer_family_member_id: f.confirmer || null,
    });
    if (r) router.replace(`/event/${r.id}`);
  }

  return (
    <Screen ground="paper" back eyebrow="Events" title="Plan an event" footer={<Button title="Create the event" disabled={!ready} loading={act.busy} onPress={() => void create()} />}>
      <T v="callout" muted>Tenmina checks each vendor. The bank holds the budget and pays vendors only against their invoice and proof of delivery.</T>
      <Panel style={{ gap: 0, paddingVertical: space[2] }}>
        <Label>Kind</Label>
        {KINDS.map((k) => (
          <Choice key={k} selected={f.kind === k} onPress={() => set('kind')(k)} title={words(k)} />
        ))}
      </Panel>
      <Field label="Name" value={f.name} onChange={set('name')} placeholder="For example: Funeral of Opanyin Kwame Mensah" />
      <Field label="Date" value={f.event_date} onChange={set('event_date')} keyboardType="numbers-and-punctuation" placeholder="YYYY-MM-DD" hint={dateOk ? undefined : 'Write the date as year-month-day, for example 2026-12-19.'} />
      <Field label="Town" value={f.locality} onChange={set('locality')} />
      <Field label={`Budget${country.currency ? ` (${country.currency})` : ''}`} value={f.budget} onChange={(v) => set('budget')(amountOnly(v))} keyboardType="decimal-pad" />
      <Panel style={{ gap: 0, paddingVertical: space[2] }}>
        <Label>Who confirms deliveries at the event</Label>
        <Choice selected={!f.confirmer} onPress={() => set('confirmer')('')} title="Choose later" />
        {fams.map((m) => (
          <Choice key={m.id} selected={f.confirmer === m.id} onPress={() => set('confirmer')(m.id)} title={m.full_name} detail={words(m.relationship)} />
        ))}
      </Panel>
      <ProblemBox problem={act.problem} />
    </Screen>
  );
}
