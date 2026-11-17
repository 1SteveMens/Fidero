import { useState } from 'react';
import { View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, space } from '@tenmina/tokens';
import { Button, Label, Panel, Screen, T, Tick, haptic } from '@tenmina/ui';
import { Field, LoadState, ProblemBox, money, useAction, useGet, words, type ApiMoney } from '@tenmina/mobile';

interface Info {
  payment_id: string;
  provider_ref: string;
  merchant: string;
  amount: ApiMoney;
  method: string;
  status: string;
  outcomes: string[];
  note: string;
}

const DONE: Record<string, string> = {
  confirmed: 'Paid',
  failed: 'Not paid',
  pending_approval: 'Waiting for the provider',
  initiated: 'Waiting for the provider',
};

/**
 * The payment provider's checkout for Tenmina's fee, inside the app (SCR-APP-06).
 * This is the development provider's form: the card is a test card and nothing
 * typed here leaves the phone; the provider's answer comes back to Tenmina by
 * its signed webhook. A real provider shows its own secure form.
 */
export default function Checkout() {
  const { id, order } = useLocalSearchParams<{ id: string; order?: string }>();
  const info = useGet<Info>(`/v1/payments/${id}/fake-checkout`);
  const act = useAction();
  const [card, setCard] = useState('4242 4242 4242 4242');
  const [expiry, setExpiry] = useState('12 / 30');
  const [cvc, setCvc] = useState('123');
  const [result, setResult] = useState<string>();
  const d = info.data;
  const momo = d?.method === 'mobile_money';
  const status = result ?? (d && d.status !== 'initiated' ? d.status : undefined);
  const paid = status === 'confirmed';

  async function complete(outcome: string) {
    const p = await act.run<{ status: string }>('POST', `/v1/payments/${id}/fake-checkout`, { outcome }, { idempotencyKey: `checkout-${id}-${outcome}` });
    if (p) {
      haptic(p.status === 'confirmed' ? 'success' : 'warning');
      setResult(p.status);
    }
  }

  const cardOk = card.replace(/\D/g, '').length >= 15 && expiry.replace(/\D/g, '').length >= 4 && cvc.replace(/\D/g, '').length >= 3;
  const back = () => (order ? router.replace(`/pay-fee/${order}`) : router.back());

  return (
    <Screen
      ground="ink"
      back
      eyebrow="Payment provider · test"
      title={momo ? 'Approve on your phone' : 'Card details'}
      footer={
        d ? (
          status ? (
            <Button title={paid ? 'Done' : 'Back to the fee'} onPress={back} />
          ) : momo ? (
            <>
              <Button title="I approved the prompt" icon="checkmark" loading={act.busy} onPress={() => void complete('approve_prompt')} />
              <Button title="I rejected it" variant="quiet" disabled={act.busy} onPress={() => void complete('reject_prompt')} />
            </>
          ) : (
            <>
              <Button title={`Pay ${money(d.amount)}`} icon="lock-closed" disabled={!cardOk} loading={act.busy} onPress={() => void complete('success')} />
              <Button title="Try a declined card" variant="quiet" disabled={act.busy} onPress={() => void complete('decline')} />
            </>
          )
        ) : undefined
      }
    >
      <LoadState loading={info.loading} problem={info.problem} onRetry={info.reload} hasData={!!d} />
      {d ? (
        <>
          <Panel>
            <Label>{d.merchant}</Label>
            <T v="amount" style={{ fontSize: 34, lineHeight: 40 }}>{money(d.amount)}</T>
            <T v="footnote" muted>{`${words(d.method)} · ${d.provider_ref}`}</T>
          </Panel>
          {status ? (
            <Panel tone={paid ? 'lime' : 'surface'} style={{ flexDirection: 'row', alignItems: 'center' }}>
              {paid ? <Tick /> : <Ionicons name="close-circle" size={22} color={brand.paper} />}
              <View style={{ flex: 1 }}>
                <T v="headline" color={paid ? brand.ink : undefined}>{DONE[status] ?? words(status)}</T>
                <T v="footnote" color={paid ? brand.ink : undefined} muted={!paid}>
                  {paid ? 'The provider confirmed it. Your receipt is in your account.' : 'Nothing was taken. Go back to try again, or choose another way to pay.'}
                </T>
              </View>
            </Panel>
          ) : momo ? (
            <Panel style={{ gap: space[2] }}>
              <Ionicons name="phone-portrait-outline" size={26} color={brand.lime} />
              <T v="headline">We sent a payment prompt to your mobile money number.</T>
              <T v="callout" muted>Enter your PIN on the prompt to approve it. Then come back here.</T>
            </Panel>
          ) : (
            <>
              <Field label="Card number" value={card} onChange={setCard} keyboardType="number-pad" autoComplete="off" />
              <View style={{ flexDirection: 'row', gap: space[3] }}>
                <View style={{ flex: 1 }}>
                  <Field label="Expiry" value={expiry} onChange={setExpiry} keyboardType="number-pad" autoComplete="off" />
                </View>
                <View style={{ flex: 1 }}>
                  <Field label="Security code" value={cvc} onChange={setCvc} keyboardType="number-pad" autoComplete="off" secure />
                </View>
              </View>
            </>
          )}
          <View style={{ flexDirection: 'row', gap: space[3] }}>
            <Ionicons name="shield-checkmark-outline" size={18} color={brand.lime} />
            <T v="footnote" muted style={{ flex: 1 }}>{`${d.note} Tenmina never sees or keeps card numbers: only the brand and the last 4 digits come back.`}</T>
          </View>
          <ProblemBox problem={act.problem} />
        </>
      ) : null}
    </Screen>
  );
}
