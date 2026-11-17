import { useState } from 'react';
import { View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import { space } from '@tenmina/tokens';
import { Button, Choice, Label, Panel, Screen, T } from '@tenmina/ui';
import { Field, LoadState, ProblemBox, itemsOf, moneyOf, useAction, useGet } from '@tenmina/mobile';
import { amountOnly, useCountry } from '../../components/country';

interface Asset {
  id: string;
  reference: string;
  name: string;
  type: string;
  locality: string;
  plot_number: string;
  verified_at: string | null;
}

type Kind = 'construction' | 'funds';
const blankStage = { name: '', amount: '' };
const blankSupplier = { name: '', what_they_supply: '', contact_phone: '', bank_name: '', account_number: '' };

/**
 * Start a project in the app: build in stages on a checked plot (SCR-PTL-25,
 * FR-BLD-001) or fund a project someone runs at home (SCR-PTL-30, FR-PRJ-001).
 * Money is held by the partner bank and paid only to checked payees, stage by
 * stage, after the client approves and two Tenmina staff approve.
 */
export default function NewProject() {
  const params = useLocalSearchParams<{ type?: string }>();
  const country = useCountry();
  const assets = useGet<{ items: Asset[] } | Asset[]>('/v1/assets');
  const act = useAction();
  const [kind, setKind] = useState<Kind>(params.type === 'funds' ? 'funds' : 'construction');
  const [f, setF] = useState({ title: '', description: '', asset_id: '', budget: '', payment_route: 'escrow', runner_name: '', runner_phone: '' });
  const [stages, setStages] = useState([{ ...blankStage }]);
  const [sups, setSups] = useState([{ ...blankSupplier }]);
  const set = (k: keyof typeof f) => (v: string) => setF((x) => ({ ...x, [k]: v }));
  const plots = itemsOf(assets.data);
  const total = stages.reduce((s, x) => s + Number(x.amount || 0), 0);
  const budget = Number(f.budget || 0);

  const ready =
    !!f.title.trim() &&
    budget > 0 &&
    !!country.currency &&
    (kind === 'construction' ? !!f.asset_id : !!f.runner_name.trim() && stages.some((s) => s.name && Number(s.amount) > 0) && Math.abs(total - budget) < 0.005);

  async function start() {
    const base = { type: kind, title: f.title.trim(), description: f.description.trim(), budget: { amount: f.budget, currency: country.currency }, payment_route: f.payment_route, country: country.code };
    const body =
      kind === 'funds'
        ? {
            ...base,
            stages: stages.filter((s) => s.name && s.amount).map((s) => ({ name: s.name.trim(), amount: s.amount })),
            runner: { name: f.runner_name.trim(), phone: f.runner_phone.trim() },
            suppliers: sups.filter((s) => s.name.trim()),
          }
        : { ...base, asset_id: f.asset_id };
    const p = await act.run<{ id: string }>('POST', '/v1/projects', body);
    if (p) router.replace(`/project/${p.id}`);
  }

  return (
    <Screen ground="paper" back eyebrow="Projects" title="Start a project" footer={<Button title="Start the project" disabled={!ready} loading={act.busy} onPress={() => void start()} />}>
      <Panel style={{ gap: 0, paddingVertical: space[2] }}>
        <Label>What kind</Label>
        <Choice selected={kind === 'construction'} onPress={() => setKind('construction')} title="Build on a checked plot" detail="A quantity surveyor prices the work, a vetted contractor builds, and an inspector checks every stage before it is paid." />
        <Choice selected={kind === 'funds'} onPress={() => setKind('funds')} title="Fund a project at home" detail="A shop, a farm, a fit-out. Money goes only to named, checked suppliers against their invoices." />
      </Panel>

      <Field label="Name" value={f.title} onChange={set('title')} placeholder={kind === 'funds' ? 'For example: Poultry farm, Nsawam' : 'For example: Family house, Kasoa'} />
      <Field label="What it is" value={f.description} onChange={set('description')} multiline />

      {kind === 'construction' ? (
        <View style={{ gap: space[2] }}>
          <Label>The plot</Label>
          <LoadState loading={assets.loading} problem={assets.problem} onRetry={assets.reload} hasData={!!assets.data} />
          {assets.data && !plots.length ? (
            <Panel>
              <T v="callout">You need a checked plot first.</T>
              <Button title="Check a plot" variant="dark" onPress={() => router.push('/order')} />
            </Panel>
          ) : null}
          {plots.length ? (
            <Panel style={{ gap: 0, paddingVertical: space[2] }}>
              {plots.map((a) => (
                <Choice
                  key={a.id}
                  selected={f.asset_id === a.id}
                  onPress={() => set('asset_id')(a.id)}
                  title={a.name || [a.plot_number && `Plot ${a.plot_number}`, a.locality].filter(Boolean).join(', ') || a.reference}
                  detail={`${a.reference}${a.verified_at ? ' · checked by Tenmina' : ' · not checked yet'}`}
                />
              ))}
            </Panel>
          ) : null}
        </View>
      ) : null}

      <Field
        label={`Budget${country.currency ? ` (${country.currency})` : ''}`}
        value={f.budget}
        onChange={(v) => set('budget')(amountOnly(v))}
        keyboardType="decimal-pad"
        hint={kind === 'construction' ? "Your first estimate. The quantity surveyor's bill of quantities replaces it." : 'The stages below must add up to it.'}
      />

      <Panel style={{ gap: 0, paddingVertical: space[2] }}>
        <Label>How payments go</Label>
        <Choice selected={f.payment_route === 'escrow'} onPress={() => set('payment_route')('escrow')} title="The bank holds the money" detail="The partner bank pays each stage after you and two Tenmina staff approve." />
        <Choice selected={f.payment_route === 'client_direct'} onPress={() => set('payment_route')('client_direct')} title="I pay each payee myself" detail="Only to the verified payee Tenmina names, after the stage is checked." />
      </Panel>

      {kind === 'funds' ? (
        <>
          <Label>Who runs it at home</Label>
          <Field label="Name" value={f.runner_name} onChange={set('runner_name')} />
          <Field label="Phone" value={f.runner_phone} onChange={set('runner_phone')} keyboardType="phone-pad" hint="The person running it is never paid as a supplier. Tenmina runs a background check on them." />

          <Label>{`Stages · ${moneyOf(total, country.currency)} of ${moneyOf(budget, country.currency)}`}</Label>
          {stages.map((s, i) => (
            <View key={i} style={{ flexDirection: 'row', gap: space[2] }}>
              <View style={{ flex: 2 }}>
                <Field label={`Stage ${i + 1}`} value={s.name} onChange={(v) => setStages((all) => all.map((x, j) => (j === i ? { ...x, name: v } : x)))} />
              </View>
              <View style={{ flex: 1 }}>
                <Field label="Amount" value={s.amount} keyboardType="decimal-pad" onChange={(v) => setStages((all) => all.map((x, j) => (j === i ? { ...x, amount: amountOnly(v) } : x)))} />
              </View>
            </View>
          ))}
          <Button title="Add a stage" variant="quiet" icon="add" onPress={() => setStages((all) => [...all, { ...blankStage }])} />
          {budget > 0 && Math.abs(total - budget) >= 0.005 ? <T v="footnote" muted>{`The stages add up to ${moneyOf(total, country.currency)}. Make them equal the budget.`}</T> : null}

          <Label>Suppliers</Label>
          {sups.map((s, i) => (
            <Panel key={i} style={{ gap: space[2] }}>
              <Field label="Business name" value={s.name} onChange={(v) => setSups((all) => all.map((x, j) => (j === i ? { ...x, name: v } : x)))} />
              <Field label="What they supply" value={s.what_they_supply} onChange={(v) => setSups((all) => all.map((x, j) => (j === i ? { ...x, what_they_supply: v } : x)))} />
              <Field label="Bank" value={s.bank_name} onChange={(v) => setSups((all) => all.map((x, j) => (j === i ? { ...x, bank_name: v } : x)))} />
              <Field label="Account number" value={s.account_number} keyboardType="number-pad" onChange={(v) => setSups((all) => all.map((x, j) => (j === i ? { ...x, account_number: v.replace(/\D/g, '') } : x)))} />
            </Panel>
          ))}
          <Button title="Add a supplier" variant="quiet" icon="add" onPress={() => setSups((all) => [...all, { ...blankSupplier }])} />
          <T v="footnote" muted>Tenmina checks each supplier and their bank account before any money goes to them.</T>
        </>
      ) : null}
      <ProblemBox problem={act.problem} />
    </Screen>
  );
}
