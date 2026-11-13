import { useState } from 'react';
import { View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, space } from '@tenmina/tokens';
import { Button, Chip, Label, Panel, Screen, T, Tick } from '@tenmina/ui';
import { LoadState, ProblemBox, money, portalUrl, useAction, useGet, useSession, words, type ApiMoney } from '@tenmina/mobile';

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

/**
 * Pay Tenmina's fee in the app (SCR-APP-06; FR-APP-005, DA-12). Tenmina's fee
 * only, never purchase, building or project money. In "web" mode the fee is paid
 * on the Tenmina website in the browser, never as an in-app purchase.
 */
export default function PayFee() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { config } = useSession();
  const order = useGet<Order>(`/v1/orders/${id}`);
  const act = useAction();
  const [opened, setOpened] = useState(false);
  const web = (config?.fee_payment_mode ?? 'web') === 'web';
  const d = order.data;

  async function pay() {
    if (web) {
      await WebBrowser.openBrowserAsync(`${portalUrl()}/orders/${id}/pay`);
    } else {
      const p = await act.run<{ checkout_url: string }>('POST', `/v1/orders/${id}/payments`, { method: 'card', return_url: 'tenmina://pay-fee/' + id });
      if (p?.checkout_url) await WebBrowser.openBrowserAsync(p.checkout_url);
    }
    setOpened(true);
    order.reload();
  }

  return (
    <Screen
      ground="ink"
      back
      title="Pay Tenmina's fee"
      footer={
        d && !d.paid_at ? (
          <>
            <Button title={web ? 'Pay on the Tenmina website' : 'Pay by card or mobile money'} icon="open-outline" disabled={!d.can_pay} loading={act.busy} onPress={() => void pay()} />
            {opened ? <Button title="I have paid: check again" variant="quiet" onPress={order.reload} /> : null}
          </>
        ) : (
          <Button title="Done" onPress={() => router.back()} />
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
              <T v="callout" style={{ flex: 1 }}>Paid. Your case starts now.</T>
            </Panel>
          ) : (
            <Panel style={{ gap: space[2] }}>
              <View style={{ flexDirection: 'row', gap: space[3] }}>
                <Ionicons name="information-circle-outline" size={20} color={brand.lime} />
                <T v="callout" style={{ flex: 1 }}>
                  {web
                    ? 'This pays Tenmina for the work. It opens the Tenmina website in your browser, then you come back here.'
                    : 'This pays Tenmina for the work, through the licensed payment provider.'}
                </T>
              </View>
              <T v="footnote" muted>Money for a purchase, a build or a family bill never goes through this screen. It goes to the partner bank.</T>
              {d.missing.length ? <T v="footnote" muted>{`Before you can pay: ${d.missing.join(', ')}`}</T> : null}
              {d.last_payment_message ? <T v="footnote" muted>{d.last_payment_message}</T> : null}
            </Panel>
          )}
          <ProblemBox problem={act.problem} />
        </>
      ) : null}
    </Screen>
  );
}
