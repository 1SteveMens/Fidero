'use client';
/* Partner orders (FR-PTR-003): order a verification for a consenting client. The client confirms in
   Tenmina and pays Tenmina's fee; the client stays Tenmina's client. */
import { useEffect, useState } from 'react';
import { Button, Card, Field, Input, ProblemBox, Select, Skeleton, Status, When } from '@tenmina/web-ui';
import { EmptyText, PageHead, Section, useAct, words } from '@/components/roles/kit';
import { PartnerBar, usePartner } from '@/components/roles/partner';

type Order = { id: string; reference: string; partner_reference: string; asset_type: string; locality: string; plot_number: string; tier: string; status: string; decided_at: string | null; created_at: string };

export default function PartnerOrders() {
  const { call } = usePartner();
  const act = useAct();
  const [orders, setOrders] = useState<Order[] | null>(null);
  const [f, setF] = useState({ client_email: '', locality: '', plot_number: '', site_plan_ref: '', asset_type: 'plot', seller_name: '', partner_reference: '' });
  const load = () => act.run('load', async () => setOrders(await call<Order[]>('GET', '/v1/partner/orders')));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <div className="stack">
      <PartnerBar />
      <PageHead label="Partner" title="Orders">Verifications you ordered for your customers.</PageHead>
      <Section title="Order a verification">
        <Card className="stack">
          <p className="muted" style={{ margin: 0 }}>Your customer must have a Tenmina account and confirm the order there.</p>
          <Field label="Customer's email at Tenmina"><Input type="email" value={f.client_email} onChange={set('client_email')} /></Field>
          <Field label="What"><Select value={f.asset_type} onChange={set('asset_type')}><option value="plot">Land</option><option value="building">Building</option></Select></Field>
          <Field label="Locality"><Input value={f.locality} onChange={set('locality')} /></Field>
          <Field label="Plot number"><Input value={f.plot_number} onChange={set('plot_number')} /></Field>
          <Field label="Site plan reference"><Input value={f.site_plan_ref} onChange={set('site_plan_ref')} /></Field>
          <Field label="Seller's name"><Input value={f.seller_name} onChange={set('seller_name')} /></Field>
          <Field label="Your reference"><Input value={f.partner_reference} onChange={set('partner_reference')} /></Field>
          <Button variant="primary" disabled={!f.client_email || !f.locality} busy={act.busy === 'o'} onClick={() => act.run('o', async () => { await call('POST', '/v1/partner/orders', f); await load(); }, 'Ordered. Your customer confirms it in Tenmina.')}>Order</Button>
        </Card>
      </Section>
      <Section title="Your orders">
        {orders === null ? <Skeleton /> : orders.length ? orders.map((o) => (
          <Card key={o.id} className="spread">
            <div><div className="label">{o.reference}{o.partner_reference ? ` · ${o.partner_reference}` : ''}</div><strong>{words(o.asset_type)} in {o.locality}{o.plot_number ? `, plot ${o.plot_number}` : ''}</strong><div className="muted" style={{ fontSize: 13 }}><When value={o.created_at} /></div></div>
            <Status value={o.status} />
          </Card>
        )) : <EmptyText>No orders yet.</EmptyText>}
      </Section>
      <ProblemBox error={act.error} />
      {act.toast}
    </div>
  );
}
