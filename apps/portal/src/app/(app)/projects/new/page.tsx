'use client';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button, Field, Input, ProblemBox, Select, Textarea, useGet } from '@tenmina/web-ui';
import { PageHead, RadioCard, Section, list, useAction, useCountry, type Any } from '@/components/kit';

/** SCR-PTL-25 (start a build on a checked plot) and SCR-PTL-30 (a project fund with stages and suppliers). */
export default function NewProject() {
  const country = useCountry();
  const router = useRouter();
  const assets = useGet<Any>('/v1/assets');
  const [type, setType] = useState('construction');
  const [f, setF] = useState({ title: '', description: '', asset_id: '', budget: '', payment_route: 'escrow', runner_name: '', runner_phone: '' });
  const [stages, setStages] = useState([{ name: '', amount: '' }]);
  const [sups, setSups] = useState([{ name: '', what_they_supply: '', contact_phone: '', bank_name: '', account_number: '' }]);
  const a = useAction();
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });
  const total = stages.reduce((s, x) => s + Number(x.amount || 0), 0);
  function body() {
    const base = { type, title: f.title, description: f.description, budget: { amount: f.budget, currency: country.currency }, payment_route: f.payment_route, country: country.code };
    if (type === 'funds') return { ...base, stages: stages.filter((s) => s.name).map((s) => ({ name: s.name, amount: s.amount })), runner: { name: f.runner_name, phone: f.runner_phone }, suppliers: sups.filter((s) => s.name) };
    return { ...base, asset_id: f.asset_id || null };
  }
  return (
    <form className="stack" style={{ gap: 16 }} onSubmit={(e) => { e.preventDefault(); a.run('go', () => a.post<Any>('/v1/projects', body()), undefined, (p) => router.push(`/projects/${p.id}`)); }}>
      <PageHead back={{ href: '/projects', label: 'Projects' }} label="Projects" title="Start a project" />
      <RadioCard name="type" checked={type === 'construction'} onChange={() => setType('construction')}><strong>Build on a checked plot</strong><div className="muted" style={{ fontSize: 14 }}>A quantity surveyor prices the work, a vetted contractor builds, an inspector checks every stage before it is paid.</div></RadioCard>
      <RadioCard name="type" checked={type === 'funds'} onChange={() => setType('funds')}><strong>Fund a project someone runs at home</strong><div className="muted" style={{ fontSize: 14 }}>A shop, a farm, a fit-out. Money goes only to named, checked suppliers against invoices.</div></RadioCard>
      <Field label="Name"><Input value={f.title} onChange={set('title')} required /></Field>
      <Field label="What it is"><Textarea value={f.description} onChange={set('description')} /></Field>
      {type === 'construction' ? <Field label="The plot"><Select value={f.asset_id} onChange={set('asset_id')}><option value="">Choose</option>{list(assets.data).map((x: Any) => <option key={x.id} value={x.id}>{x.name || x.locality} ({x.reference})</option>)}</Select></Field> : null}
      <Field label={`Budget (${country.currency})`} hint={type === 'construction' ? "Your first estimate. The quantity surveyor's bill of quantities replaces it." : 'The stages below must add up to it.'}><Input inputMode="decimal" value={f.budget} onChange={(e) => setF({ ...f, budget: e.target.value.replace(/[^\d.]/g, '') })} required /></Field>
      <Field label="How payments go"><Select value={f.payment_route} onChange={set('payment_route')}><option value="escrow">The bank holds the money and pays each stage</option><option value="client_direct">I pay each verified payee myself</option></Select></Field>
      {type === 'funds' ? <>
        <Section title="Who runs it at home">
          <Field label="Name"><Input value={f.runner_name} onChange={set('runner_name')} required /></Field>
          <Field label="Phone"><Input type="tel" value={f.runner_phone} onChange={set('runner_phone')} /></Field>
          <p className="muted" style={{ margin: 0, fontSize: 14 }}>The person running it is never paid as a supplier. Tenmina runs a background check on them.</p>
        </Section>
        <Section title={`Stages (${total.toLocaleString('en-GB')} of ${Number(f.budget || 0).toLocaleString('en-GB')})`}>
          {stages.map((s, i) => (
            <div key={i} className="row"><div style={{ flex: 2, minWidth: 150 }}><Field label={`Stage ${i + 1}`}><Input value={s.name} onChange={(e) => setStages(stages.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} /></Field></div><div style={{ flex: 1, minWidth: 100 }}><Field label="Amount"><Input inputMode="decimal" value={s.amount} onChange={(e) => setStages(stages.map((x, j) => (j === i ? { ...x, amount: e.target.value.replace(/[^\d.]/g, '') } : x)))} /></Field></div></div>
          ))}
          <Button type="button" variant="ghost" onClick={() => setStages([...stages, { name: '', amount: '' }])}>Add a stage</Button>
        </Section>
        <Section title="Suppliers">
          {sups.map((s, i) => (
            <div key={i} className="card stack">
              <Field label="Business name"><Input value={s.name} onChange={(e) => setSups(sups.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} /></Field>
              <Field label="What they supply"><Input value={s.what_they_supply} onChange={(e) => setSups(sups.map((x, j) => (j === i ? { ...x, what_they_supply: e.target.value } : x)))} /></Field>
              <Field label="Bank"><Input value={s.bank_name} onChange={(e) => setSups(sups.map((x, j) => (j === i ? { ...x, bank_name: e.target.value } : x)))} /></Field>
              <Field label="Account number"><Input inputMode="numeric" value={s.account_number} onChange={(e) => setSups(sups.map((x, j) => (j === i ? { ...x, account_number: e.target.value } : x)))} /></Field>
            </div>
          ))}
          <Button type="button" variant="ghost" onClick={() => setSups([...sups, { name: '', what_they_supply: '', contact_phone: '', bank_name: '', account_number: '' }])}>Add a supplier</Button>
        </Section>
      </> : null}
      <ProblemBox error={a.error} />
      <Button variant="primary" type="submit" busy={!!a.busy}>Start the project</Button>
    </form>
  );
}
