'use client';
/* Tenant view (SCR-PTL-54): the agreement, where rent goes, the rent record. Rent is paid to the owner's
   own account, never to Tenmina (RUL-24). */
import Link from 'next/link';
import { Card, Chip, KV, Money, Status, When, useGet } from '@tenmina/web-ui';
import { EmptyText, EvidenceLink, Loaded, PageHead, Section, items, words, type Page } from '@/components/roles/kit';

import type { Tenancy } from '@/components/roles/tenancy';

export default function TenantHome() {
  const q = useGet<Page<Tenancy>>('/v1/tenancies');
  return (
    <div className="stack">
      <PageHead label="My home" title="Your tenancy">Your agreement and rent record. Tenmina manages the property for the owner.</PageHead>
      <Loaded q={q}>{(d) => items(d).length ? items(d).map((t) => <TenancyView key={t.id} t={t} />) : <EmptyText>No tenancy on your account yet.</EmptyText>}</Loaded>
    </div>
  );
}

function TenancyView({ t }: { t: Tenancy }) {
  const p = t.payment_details;
  const periods = [...t.periods].sort((a, b) => b.due_on.localeCompare(a.due_on));
  return (
    <>
      <Card className="stack">
        <div className="spread"><h2 style={{ margin: 0 }}>{t.property_title}</h2><Status value={t.status} /></div>
        <KV items={[
          ['Rent', <span key="r"><Money value={t.rent} /> {words(t.period).toLowerCase()}</span>],
          ['Due', `Day ${t.due_day} of each period`],
          ['From', <When key="f" value={t.starts_on} />],
          ['To', t.ends_on ? <When key="t" value={t.ends_on} /> : 'No end date'],
          ['Your reference', <span key="ref" className="mono">{t.tenant_reference}</span>],
        ]} />
        <EvidenceLink id={t.agreement_evidence} label="Tenancy agreement" />
      </Card>
      {p ? (
        <div className="card-ink stack">
          <div className="label">How to pay rent</div>
          <div className="statline"><span>Amount</span><span className="v"><Money value={p.amount} /></span></div>
          <div className="statline"><span>Bank</span><span className="v">{p.bank_name}</span></div>
          <div className="statline"><span>Account name</span><span className="v">{p.account_name}</span></div>
          <div className="statline"><span>Account number</span><span className="v mono">{p.account_number}</span></div>
          <div className="statline"><span>Reference</span><span className="v mono">{p.reference}</span></div>
          <p style={{ margin: 0 }}>{p.note || 'Pay the owner\'s own account only. Tenmina never receives rent.'}</p>
        </div>
      ) : null}
      <Section title="Rent record" action={<Link href="/tenant/repairs" className="btn btn-ghost btn-sm">Report a repair</Link>}>
        {periods.map((r) => (
          <Card key={r.id} className="spread">
            <div style={{ minWidth: 0, flex: 1 }}><div className="label">Due <When value={r.due_on} /></div><div style={{ fontSize: 14 }}>{r.status_text}</div></div>
            <div className="rl-right"><Money value={r.expected} />{r.status === 'received' ? <Chip tone="lime">✓ Received</Chip> : <Status value={r.status} />}</div>
          </Card>
        ))}
      </Section>
    </>
  );
}
