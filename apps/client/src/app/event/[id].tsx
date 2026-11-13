import { View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import { space } from '@tenmina/tokens';
import { Button, Chip, Label, Panel, Screen, T } from '@tenmina/ui';
import { LoadState, Section, day, money, useApi, useLoad, words, type ApiMoney } from '@tenmina/mobile';
import { Figures } from '../../components/rows';
import { InlineApproval } from '../../components/InlineApproval';

interface Event {
  id: string;
  kind: string;
  name: string;
  event_date: string;
  locality: string;
  budget: ApiMoney;
  escrow: string | null;
  escrow_reference: string;
  confirmer: { name: string } | null;
  status: string;
  fee_order_id: string | null;
  warnings: string[];
  vendors: { id: string; kind: string; name: string; quote: ApiMoney | null; payee: { name: string; status: string; account_last4: string } | null; status: string; blockers: { message: string }[] }[];
  budget_vs_actual: { quotes: ApiMoney; committed: ApiMoney; paid: ApiMoney; remaining: ApiMoney; warnings: string[] };
}

interface VendorPayment {
  id: string;
  vendor_name: string;
  kind: string;
  amount: ApiMoney;
  description: string;
  status: string;
  client_approved_at: string | null;
  paid_at: string | null;
  missing: string[];
}

/**
 * An event (FR-EVT-001 to FR-EVT-004): the budget, each verified vendor and
 * their payments. Vendors are paid by the bank against a quote, an invoice and
 * the family's confirmation of delivery. Never cash to a relative.
 */
export default function EventScreen() {
  const api = useApi();
  const { id } = useLocalSearchParams<{ id: string }>();
  const data = useLoad(async (a) => {
    const [event, payments] = await Promise.all([a.get<Event>(`/v1/events/${id}`), a.get<VendorPayment[]>(`/v1/events/${id}/vendor-payments`)]);
    return { event, payments };
  }, `event-${id}`);
  const d = data.data?.event;
  const payments = data.data?.payments ?? [];
  const waiting = payments.filter((p) => p.status === 'evidenced' && !p.client_approved_at);

  return (
    <Screen ground="paper" back eyebrow={d ? `${words(d.kind)} · ${day(d.event_date)} · ${d.locality}` : 'Event'} title={d?.name}>
      <LoadState loading={data.loading} problem={data.problem} onRetry={data.reload} hasData={!!d} />
      {d ? (
        <>
          <Chip label={words(d.status)} tone="paper" />
          {waiting.map((p) => (
            <InlineApproval
              key={p.id}
              title={`${words(p.kind)}: ${p.description}`}
              amount={p.amount}
              payee={p.vendor_name}
              onApprove={() => api.post(`/v1/vendor-payments/${p.id}/client-approval`, { confirm_amount: p.amount, acknowledge_budget_warning: true })}
              onDone={data.reload}
            />
          ))}
          <Figures
            items={[
              ['Budget', d.budget],
              ['Paid', d.budget_vs_actual.paid],
              ['Committed', d.budget_vs_actual.committed],
              ['Left', d.budget_vs_actual.remaining],
            ]}
          />
          {[...d.warnings, ...d.budget_vs_actual.warnings].map((w) => (
            <Panel key={w}>
              <T v="callout">{w}</T>
            </Panel>
          ))}
          <Section title="Vendors">
            {d.vendors.map((v) => (
              <Panel key={v.id} style={{ gap: space[1] }}>
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[2] }}>
                  <T v="headline" style={{ flex: 1, fontSize: 15 }}>{v.name}</T>
                  <Chip label={words(v.status)} tone={v.status === 'verified' ? 'lime' : 'paper'} />
                </View>
                <Label>{`${words(v.kind)}${v.quote ? ` · quote ${money(v.quote)}` : ''}${v.payee ? ` · ••${v.payee.account_last4}` : ''}`}</Label>
                {v.blockers.map((b) => (
                  <T key={b.message} v="footnote" muted>{b.message}</T>
                ))}
              </Panel>
            ))}
          </Section>
          {payments.length ? (
            <Section title="Payments">
              <Panel style={{ gap: 0, paddingVertical: space[1] }}>
                {payments.map((p, i) => (
                  <View key={p.id} style={{ paddingVertical: space[3], borderTopWidth: i ? 1 : 0, borderTopColor: '#ECEAE4', gap: 2 }}>
                    <View style={{ flexDirection: 'row', gap: space[2] }}>
                      <T v="callout" style={{ flex: 1 }}>{`${p.vendor_name}: ${p.description}`}</T>
                      <T v="headline" style={{ fontSize: 15 }}>{money(p.amount)}</T>
                    </View>
                    <Label>{p.paid_at ? `Paid ${day(p.paid_at)}` : words(p.status)}</Label>
                    {p.missing.length ? <T v="footnote" muted>{`Waiting for: ${p.missing.join(', ')}`}</T> : null}
                  </View>
                ))}
              </Panel>
            </Section>
          ) : null}
          {d.confirmer ? <T v="footnote" muted>{`${d.confirmer.name} confirms deliveries on the day, with a code on their own phone.`}</T> : null}
          {d.escrow ? <Button title={`Money held: ${d.escrow_reference}`} variant="quiet" icon="lock-closed-outline" onPress={() => router.push(`/escrow/${d.escrow}`)} /> : null}
        </>
      ) : null}
    </Screen>
  );
}
