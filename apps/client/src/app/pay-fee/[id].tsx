import { useState } from 'react';
import { View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, space } from '@tenmina/tokens';
import { Button, Chip, Choice, Label, Panel, Screen, T, Tick } from '@tenmina/ui';
import { Field, LoadState, ProblemBox, money, newUuid, useAction, useGet, useSession, words, type ApiMoney } from '@tenmina/mobile';

interface Order {
  id: string;
  reference: string;
  product_name: string;
  status: string;
  price: ApiMoney;
  local_price: ApiMoney | null;
  paid_at: string | null;
  can_pay: boolean;
  missing: string[];
  case_id: string | null;
  last_payment_message: string;
}

interface Started {
  payment: { id: string; status: string; method: string };
  checkout_url: string;
}

/**
 * Pay Tenmina's fee in the app (SCR-APP-06; FR-APP-005, DA-12). Tenmina's fee
 * only, never purchase, building or project money, which goes to the partner
 * bank. The licensed payment provider takes the card or mobile money: with the
 * development provider its checkout is a form in the app; a real provider's
 * hosted checkout opens in a sheet inside the app. Never the website, and never
 * an in-app purchase: the fee is for work done in the real world
 * (docs/decisions/2026-11-17-in-app-everything.md).
 */
export default function PayFee() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { me } = useSession();
  const order = useGet<Order>(`/v1/orders/${id}`);
  const act = useAction();
  const [method, setMethod] = useState<'card' | 'mobile_money'>('card');
  const [phone, setPhone] = useState(me?.phone ?? '');
  const [key] = useState(() => newUuid());
  const d = order.data;

  async function pay() {
    const started = await act.run<Started>(
      'POST',
      `/v1/orders/${id}/payments`,
      { method, return_url: `tenmina://pay-fee/${id}`, ...(method === 'mobile_money' ? { wallet_phone: phone.trim() } : {}) },
      { idempotencyKey: `fee-${id}-${method}-${key}` },
    );
    if (!started) return;
    if (started.checkout_url.includes('/fake-checkout')) {
      // The development provider: its checkout is a form inside the app.
      router.push({ pathname: '/checkout/[id]', params: { id: started.payment.id, order: id } });
      return;
    }
    // A real provider hosts card and mobile money entry itself; it opens in a sheet inside the app.
    await WebBrowser.openAuthSessionAsync(started.checkout_url, `tenmina://pay-fee/${id}`);
    await act.run('POST', `/v1/payments/${started.payment.id}/refresh`);
    order.reload();
  }

  const momoOk = method !== 'mobile_money' || phone.replace(/\D/g, '').length >= 9;

  return (
    <Screen
      ground="ink"
      back
      title="Pay Tenmina's fee"
      footer={
        d && !d.paid_at ? (
          <Button title={method === 'card' ? 'Pay by card' : 'Pay by mobile money'} icon="lock-closed" disabled={!d.can_pay || !momoOk} loading={act.busy} onPress={() => void pay()} />
        ) : (
          <Button title="Done" onPress={() => (d?.case_id ? router.replace(`/case/${d.case_id}`) : router.back())} />
        )
      }
    >
      <LoadState loading={order.loading} problem={order.problem} onRetry={order.reload} hasData={!!d} />
      {d ? (
        <>
          <Panel>
            <Label>{d.reference}</Label>
            <T v="headline">{d.product_name}</T>
            <T v="amount" style={{ fontSize: 34, lineHeight: 40 }}>{money(d.price)}</T>
            {d.local_price && d.local_price.currency !== d.price.currency ? <T v="footnote" muted>{`About ${money(d.local_price)}`}</T> : null}
            <View style={{ flexDirection: 'row', gap: space[2] }}>
              {d.paid_at ? <Chip label="Paid" tone="lime" icon="checkmark" /> : <Chip label={words(d.status)} tone="paper" />}
            </View>
          </Panel>
          {d.paid_at ? (
            <Panel style={{ flexDirection: 'row', alignItems: 'center' }}>
              <Tick />
              <T v="callout" style={{ flex: 1 }}>{d.case_id ? 'Paid. Your case starts now.' : 'Paid. Thank you.'}</T>
            </Panel>
          ) : (
            <>
              <Panel style={{ gap: 0, paddingVertical: space[2] }}>
                <Label>How you pay</Label>
                <Choice selected={method === 'card'} onPress={() => setMethod('card')} title="Card" detail="Visa or Mastercard, through the payment provider" />
                <Choice selected={method === 'mobile_money'} onPress={() => setMethod('mobile_money')} title="Mobile money" detail="You approve a prompt on your phone" />
              </Panel>
              {method === 'mobile_money' ? (
                <Field label="Mobile money number" value={phone} onChange={setPhone} keyboardType="phone-pad" hint="The prompt goes to this number. Tenmina keeps only the last 4 digits." />
              ) : null}
              <Panel style={{ gap: space[2] }}>
                <View style={{ flexDirection: 'row', gap: space[3] }}>
                  <Ionicons name="information-circle-outline" size={20} color={brand.lime} />
                  <T v="callout" style={{ flex: 1 }}>This pays Tenmina for the work, through the licensed payment provider. It stays in the app.</T>
                </View>
                <T v="footnote" muted>Money for a purchase, a build or a family bill never goes through this screen. It goes to the partner bank.</T>
                {d.missing.length ? <T v="footnote" muted>{`Before you can pay: ${d.missing.join(', ')}`}</T> : null}
                {d.last_payment_message ? <T v="footnote" muted>{d.last_payment_message}</T> : null}
              </Panel>
            </>
          )}
          <ProblemBox problem={act.problem} />
        </>
      ) : null}
    </Screen>
  );
}
