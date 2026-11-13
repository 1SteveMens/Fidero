import { useState } from 'react';
import { View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import { brand, space } from '@tenmina/tokens';
import { Button, Chip, Label, Panel, Screen, T } from '@tenmina/ui';
import { Field, LoadState, ProblemBox, day, money, useAction, useGet, words, type ApiMoney } from '@tenmina/mobile';

interface Premium {
  id: string;
  policy: string;
  policy_number: string;
  insurer_name: string;
  due_on: string;
  amount: ApiMoney;
  route: string;
  release_instruction: string | null;
  client_reported_at: string | null;
  paid_at: string | null;
  status: string;
  pay_to: { bank_name: string; account_name: string; account_number: string; amount: ApiMoney; reference: string; note: string } | null;
}

/** A premium (FR-INS-005): paid straight to the insurer. Tenmina never receives premiums and moves no money across borders. */
export default function PremiumScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const p = useGet<Premium>(`/v1/insurance/premiums/${id}`);
  const act = useAction();
  const [ref, setRef] = useState('');
  const d = p.data;

  async function paid() {
    const r = await act.run('POST', `/v1/insurance/premiums/${id}/client-payment`, { reference: ref.trim() });
    if (r) p.reload();
  }

  return (
    <Screen ground="paper" back eyebrow={d ? `${d.policy_number} · due ${day(d.due_on)}` : 'Premium'} title={d ? `Premium to ${d.insurer_name.replace(/\s*\[TO VERIFY\]/, '')}` : undefined}>
      <LoadState loading={p.loading} problem={p.problem} onRetry={p.reload} hasData={!!d} />
      {d ? (
        <>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[2] }}>
            <T v="title" style={{ flex: 1 }}>{money(d.amount)}</T>
            <Chip label={words(d.status)} tone={d.paid_at ? 'lime' : 'paper'} />
          </View>
          {d.route === 'client_direct_to_insurer' && d.pay_to && !d.client_reported_at && !d.paid_at ? (
            <>
              <Panel tone="raised">
                <Label color="#A9A69E">Pay the insurer's own account</Label>
                {[
                  ['Bank', d.pay_to.bank_name],
                  ['Account name', d.pay_to.account_name],
                  ['Account number', d.pay_to.account_number],
                  ['Reference', d.pay_to.reference],
                ].map(([k, v]) => (
                  <View key={k} style={{ flexDirection: 'row', gap: space[3] }}>
                    <T v="footnote" color="#A9A69E" style={{ width: 110 }}>{k}</T>
                    <T v="mono" color={brand.lime} style={{ flex: 1, fontSize: 14 }}>{v}</T>
                  </View>
                ))}
                <T v="footnote" color="#A9A69E">{d.pay_to.note}</T>
              </Panel>
              <Panel tone="orange">
                <Label color={brand.ink}>Needs you</Label>
                <T v="headline" color={brand.ink}>Tell us when you have paid</T>
                <Field label="Your transfer reference" value={ref} onChange={setRef} />
                <Button title="I have paid the insurer" variant="dark" disabled={ref.trim().length < 3} loading={act.busy} onPress={() => void paid()} />
              </Panel>
            </>
          ) : null}
          {d.release_instruction && d.status === 'awaiting_client' ? <Button title="Approve the payment" onPress={() => router.push(`/release/${d.release_instruction}`)} /> : null}
          {d.client_reported_at ? <T v="callout" muted>{`You told us on ${day(d.client_reported_at)}. The insurer confirms it next.`}</T> : null}
          <ProblemBox problem={act.problem} />
          <Button title="Open the policy" variant="quiet" onPress={() => router.push(`/policy/${d.policy}`)} />
        </>
      ) : null}
    </Screen>
  );
}
