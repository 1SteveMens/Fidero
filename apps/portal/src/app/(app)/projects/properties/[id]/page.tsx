'use client';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button, Chip, Field, Input, KV, Money, ProblemBox, Select, Skeleton, Tabs, Textarea, When, useGet } from '@tenmina/web-ui';
import { ActionDialog, EvidenceLink, PageHead, Proof, Section, Upload, list, useAction, useCountry, words, type Any } from '@/components/kit';

/** W-32 · SCR-PTL-47 (and SCR-PTL-46 onboarding): tenancy and rent into the owner's own account, repairs, inspections. */
export default function ManagedProperty() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const country = useCountry();
  const q = useGet<Any>(`/v1/managed-properties/${id}`);
  const rent = useGet<Any[]>(`/v1/managed-properties/${id}/rent-periods`);
  const tl = useGet<Any[]>(`/v1/managed-properties/${id}/timeline`);
  const insp = useGet<Any[]>(`/v1/managed-properties/${id}/inspections`);
  const reps = useGet<Any>('/v1/repairs');
  const banks = useGet<Any>('/v1/bank-accounts');
  const a = useAction();
  const [tab, setTab] = useState('rent');
  const [dlg, setDlg] = useState<null | 'account' | 'mandate' | 'tenancy' | 'repair' | 'end' | 'pause'>(null);
  const [acct, setAcct] = useState('');
  const [mandate, setMandate] = useState<Any>(null);
  const [t, setT] = useState({ tenant_name: '', tenant_email: '', tenant_phone: '', tenant_id_number: '', rent: '', period: 'monthly', due_day: '5', starts_on: '' });
  const [r, setR] = useState({ title: '', description: '', urgent: false });
  const [photos, setPhotos] = useState<Any[]>([]);
  const [reason, setReason] = useState('');
  if (q.isLoading) return <Skeleton lines={8} />;
  if (!q.data) return <ProblemBox error={q.error} />;
  const p = q.data;
  const refresh = () => { q.mutate(); rent.mutate(); tl.mutate(); insp.mutate(); reps.mutate(); };
  const done = () => { setDlg(null); refresh(); };
  const myRepairs = list(reps.data).filter((x: Any) => x.property === id);
  return (
    <div className="stack" style={{ gap: 18 }}>
      <PageHead back={{ href: '/projects', label: 'Projects' }} label={`${words(p.status)} · ${p.asset_reference}`} title={p.title} sub={p.address || p.locality} />
      {(p.blockers ?? []).length ? (
        <section className="card stack">
          <strong>Before we can manage it</strong>
          <ul style={{ margin: 0, paddingLeft: 18 }}>{p.blockers.map((b: Any) => <li key={b.code}>{b.message}</li>)}</ul>
          <div className="row">
            {p.blockers.some((b: Any) => b.code === 'rent-account-missing') ? <Button variant="action" size="sm" onClick={() => setDlg('account')}>Choose the rent account</Button> : null}
          </div>
        </section>
      ) : null}
      {p.fee_order_id ? <Link className="btn btn-ghost btn-sm" href={`/property/orders/${p.fee_order_id}`}>Tenmina&apos;s fee to register it</Link> : null}
      <KV items={[
        ['Ownership', p.ownership_outcome === 'verified' ? <Proof key="o">Checked <When value={p.ownership_verified_at} /></Proof> : words(p.ownership_outcome || 'being checked')],
        ['Rent goes to', p.rent_account ? `${p.rent_account.bank_name} · ${p.rent_account.account_name} · ending ${p.rent_account.last4}` : 'Not chosen yet'],
        ['Bank statement mandate', p.mandate ? `${words(p.mandate.status)}${p.mandate.acknowledged_at ? ', acknowledged by the bank' : ''}` : 'Not signed'],
        ['Next inspection', p.next_inspection_due_on ? <When key="n" value={p.next_inspection_due_on} /> : '—'],
      ]} />
      <div className="row">
        {p.rent_account ? <Button variant="ghost" size="sm" onClick={() => setDlg('account')}>Change rent account</Button> : null}
        {!p.mandate || p.mandate.status !== 'active' ? <Button variant="ghost" size="sm" onClick={() => setDlg('mandate')}>Sign the statement mandate</Button> : null}
        {!p.active_tenancy && p.status === 'managed' ? <Button variant="ghost" size="sm" onClick={() => setDlg('tenancy')}>Record a tenancy</Button> : null}
      </div>
      <p className="muted" style={{ margin: 0, fontSize: 14 }}>The tenant pays rent into your own account. Tenmina reads the bank&apos;s statement lines under your mandate to check rent arrived. Tenmina never collects rent.</p>
      <Tabs current={tab} onChange={setTab} items={[{ key: 'rent', label: 'Rent' }, { key: 'repairs', label: `Repairs (${myRepairs.length})` }, { key: 'inspections', label: 'Inspections' }, { key: 'timeline', label: 'Timeline' }]} />
      {tab === 'rent' ? (
        <Section title="Rent record">
          {(rent.data ?? []).length ? [...(rent.data ?? [])].reverse().map((x: Any) => (
            <div key={x.id} className="card stack" style={{ gap: 4 }}>
              <div className="spread"><span>Due <When value={x.due_on} /></span><Money value={x.expected} /></div>
              <div className="spread"><span className="muted" style={{ fontSize: 14 }}>{x.status_text}</span>{x.status === 'received' ? <Proof>Received</Proof> : <Chip>{words(x.status)}</Chip>}</div>
            </div>
          )) : <p className="muted">No rent periods yet.</p>}
        </Section>
      ) : tab === 'repairs' ? (
        <Section title="Repairs" action={<Button variant="ghost" size="sm" onClick={() => setDlg('repair')}>Report a repair</Button>}>
          {myRepairs.length ? myRepairs.map((x: Any) => <Link key={x.id} href={`/projects/repairs/${x.id}`} className="card card-link spread"><span>{x.title}<div className="muted" style={{ fontSize: 14 }}>{words(x.status)}{x.urgent ? ' · urgent' : ''}</div></span>{x.status === 'quotes_ready' ? <Chip tone="orange">Needs you</Chip> : null}</Link>) : <p className="muted">No repairs.</p>}
        </Section>
      ) : tab === 'inspections' ? (
        <Section title="Inspections">
          {(insp.data ?? []).map((x: Any) => (
            <div key={x.id} className="card stack" style={{ gap: 4 }}>
              <div className="spread"><strong>{words(x.kind)} · {x.scheduled_for}</strong><Chip>{words(x.outcome || x.status)}</Chip></div>
              {x.condition_rating ? <div>Condition: {words(x.condition_rating)}</div> : null}
              {x.notes ? <div className="muted">{x.notes}</div> : null}
              <div className="row">{(x.photos ?? []).slice(0, 6).map((ph: Any) => <EvidenceLink key={ph.id ?? ph} id={ph.id ?? ph.evidence_id ?? ph} label="Photo" variant="preview" />)}</div>
            </div>
          ))}
          <Button variant="ghost" busy={a.busy === 'i'} onClick={() => a.run('i', () => a.post(`/v1/managed-properties/${id}/inspections`, { kind: 'periodic' }), 'Inspection booked', refresh)}>Book an inspection</Button>
        </Section>
      ) : (
        <Section title="Timeline">
          {(tl.data ?? []).map((x: Any, i: number) => <div key={`${x.id}-${i}`} className="card"><div className="label"><When value={x.date} /> · {words(x.kind)}</div><strong>{x.title}</strong>{x.detail ? <div className="muted" style={{ fontSize: 14 }}>{x.detail}</div> : null}</div>)}
        </Section>
      )}
      <ProblemBox error={a.error} />
      <div className="row">
        {p.status === 'managed' ? <Button variant="ghost" onClick={() => setDlg('pause')}>Pause management</Button> : null}
        {p.status === 'paused' ? <Button variant="ghost" busy={a.busy === 'r'} onClick={() => a.run('r', () => a.post(`/v1/managed-properties/${id}/resume`), 'Resumed', refresh)}>Resume</Button> : null}
        {['managed', 'paused', 'onboarding'].includes(p.status) ? <Button variant="ghost" onClick={() => setDlg('end')}>End management</Button> : null}
      </div>

      <ActionDialog open={dlg === 'account'} onClose={() => setDlg(null)} title="Rent account" submit="Save" busy={a.busy === 'acc'} error={a.error}
        onSubmit={() => a.run('acc', () => a.post(`/v1/managed-properties/${id}/rent-account`, { bank_account_id: acct }, 'PUT'), 'Saved', done)}>
        <Field label="Your verified bank account"><Select value={acct} onChange={(e) => setAcct(e.target.value)} required><option value="">Choose</option>{list(banks.data).map((b: Any) => <option key={b.id} value={b.id} disabled={b.verification_status !== 'verified'}>{b.bank_name} ending {b.account_number_last4}{b.verification_status !== 'verified' ? ` (${words(b.verification_status)})` : ''}</option>)}</Select></Field>
        <Link href="/account/bank-accounts" className="muted">Add a bank account</Link>
      </ActionDialog>
      <ActionDialog open={dlg === 'mandate'} onClose={() => setDlg(null)} title="Statement mandate" submit="Send the signed mandate" busy={a.busy === 'm'} error={a.error} disabled={!mandate}
        onSubmit={() => a.run('m', () => a.post(`/v1/managed-properties/${id}/statement-mandates`, { mandate_evidence_id: mandate.id }), 'Sent. The bank acknowledges it next.', done)}>
        <p style={{ margin: 0 }}>Sign the letter that lets your bank share this account&apos;s statement lines with Tenmina, so we can check rent arrived. You can revoke it at any time.</p>
        <Upload subject={{ type: 'managed_property', id, role: 'statement_mandate' }} label={mandate ? 'Signed mandate attached' : 'Attach the signed mandate'} onDone={setMandate} />
      </ActionDialog>
      <ActionDialog open={dlg === 'tenancy'} onClose={() => setDlg(null)} title="Record a tenancy" submit="Save" busy={a.busy === 't'} error={a.error}
        onSubmit={() => a.run('t', () => a.post(`/v1/managed-properties/${id}/tenancies`, { ...t, rent: { amount: t.rent, currency: country.currency }, due_day: Number(t.due_day) }), 'Saved', done)}>
        <Field label="Tenant's name"><Input value={t.tenant_name} onChange={(e) => setT({ ...t, tenant_name: e.target.value })} required /></Field>
        <Field label="Tenant's email"><Input type="email" value={t.tenant_email} onChange={(e) => setT({ ...t, tenant_email: e.target.value })} required /></Field>
        <Field label="Tenant's phone"><Input type="tel" value={t.tenant_phone} onChange={(e) => setT({ ...t, tenant_phone: e.target.value })} /></Field>
        <Field label="Tenant's national ID number" hint="Checked with the national identity system."><Input value={t.tenant_id_number} onChange={(e) => setT({ ...t, tenant_id_number: e.target.value })} /></Field>
        <Field label={`Rent (${country.currency})`}><Input inputMode="decimal" value={t.rent} onChange={(e) => setT({ ...t, rent: e.target.value.replace(/[^\d.]/g, '') })} required /></Field>
        <Field label="Paid"><Select value={t.period} onChange={(e) => setT({ ...t, period: e.target.value })}><option value="monthly">Monthly</option><option value="quarterly">Quarterly</option><option value="half_yearly">Every six months</option><option value="yearly">Yearly</option></Select></Field>
        <Field label="Due on day"><Input type="number" min={1} max={28} value={t.due_day} onChange={(e) => setT({ ...t, due_day: e.target.value })} /></Field>
        <Field label="Starts on"><Input type="date" value={t.starts_on} onChange={(e) => setT({ ...t, starts_on: e.target.value })} required /></Field>
      </ActionDialog>
      <ActionDialog open={dlg === 'repair'} onClose={() => setDlg(null)} title="Report a repair" submit="Report" busy={a.busy === 'rep'} error={a.error} disabled={!photos.length}
        onSubmit={() => a.run('rep', () => a.post<Any>('/v1/repairs', { property_id: id, ...r, photo_ids: photos.map((x) => x.id) }), undefined, (x) => router.push(`/projects/repairs/${x.id}`))}>
        <Field label="What is wrong"><Input value={r.title} onChange={(e) => setR({ ...r, title: e.target.value })} required /></Field>
        <Field label="Details"><Textarea value={r.description} onChange={(e) => setR({ ...r, description: e.target.value })} required /></Field>
        <label className="row" style={{ flexWrap: 'nowrap' }}><input type="checkbox" checked={r.urgent} onChange={(e) => setR({ ...r, urgent: e.target.checked })} style={{ width: 22, height: 22 }} /> Urgent</label>
        <Upload subject={{ type: 'managed_property', id, role: 'repair_photo' }} label="Add a photo" accept="image/*" onDone={(ev) => setPhotos([...photos, ev])} />
        {photos.length ? <small className="muted">{photos.length} photo(s)</small> : null}
      </ActionDialog>
      <ActionDialog open={dlg === 'pause' || dlg === 'end'} onClose={() => setDlg(null)} title={dlg === 'end' ? 'End management' : 'Pause management'} submit={dlg === 'end' ? 'End' : 'Pause'} busy={a.busy === 'pe'} error={a.error}
        onSubmit={() => a.run('pe', () => a.post(`/v1/managed-properties/${id}/${dlg}`, { reason }), 'Done', done)}>
        <Field label="Why"><Textarea value={reason} onChange={(e) => setReason(e.target.value)} required /></Field>
      </ActionDialog>
      {a.toast}
    </div>
  );
}
