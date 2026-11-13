'use client';
/* Policies you issued through Tenmina: renewals (US-INS-003). */
import { useState } from 'react';
import { Button, Card, Field, Input, KV, Money, ProblemBox, Status, When, useGet } from '@tenmina/web-ui';
import { EmptyText, EvidenceLink, Loaded, PageHead, items, useAct, useApi, words, type Page } from '@/components/roles/kit';
import { InsurerLine, type Policy } from '@/components/roles/insurer';

export default function InsurerPolicies() {
  const q = useGet<Page<Policy>>('/v1/insurance/policies');
  return (
    <div className="stack">
      <PageHead label="Insurer" title="Policies">Record a renewal so the client&apos;s policy wallet shows the new date.</PageHead>
      <InsurerLine />
      <Loaded q={q}>{(d) => items(d).length ? items(d).map((p) => <PolicyCard key={p.id} p={p} onDone={() => q.mutate()} />) : <EmptyText>No policies yet.</EmptyText>}</Loaded>
    </div>
  );
}

function PolicyCard({ p, onDone }: { p: Policy; onDone: () => void }) {
  const api = useApi();
  const act = useAct();
  const [renews, setRenews] = useState('');
  return (
    <Card className="stack">
      <div className="spread"><div><div className="label mono">{p.policy_number}</div><strong>{p.product_name}</strong></div><Status value={p.status} /></div>
      <KV items={[['Premium', <span key="p"><Money value={p.premium} /> a {p.premium_period}</span>], ['Paid', words(p.premium_route)], ['Started', <When key="s" value={p.starts_on} />], ['Renews', <When key="r" value={p.renews_on} />], ['Claims contact', p.claim_contact || '—']]} />
      <EvidenceLink id={p.document_evidence} label="Policy document" />
      {p.status === 'active' ? (
        <div className="row" style={{ alignItems: 'flex-end' }}>
          <Field label="New renewal date"><Input type="date" value={renews} onChange={(e) => setRenews(e.target.value)} /></Field>
          <Button variant="dark" disabled={!renews} busy={act.busy === 'r'} onClick={() => act.run('r', async () => { await api('POST', `/v1/insurance/policies/${p.id}/renewals`, { renews_on: renews }); onDone(); }, 'Renewal recorded.')}>Record renewal</Button>
        </div>
      ) : null}
      <ProblemBox error={act.error} />
      {act.toast}
    </Card>
  );
}
