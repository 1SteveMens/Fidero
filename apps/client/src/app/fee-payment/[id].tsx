import { useState } from 'react';
import { View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import { brand, space } from '@tenmina/tokens';
import { Button, Chip, Label, Panel, Screen, StepTrail, T } from '@tenmina/ui';
import type { CaseStep } from '@tenmina/shared';
import { Field, LoadState, ProblemBox, day, money, useAction, useGet, words, type ApiMoney } from '@tenmina/mobile';

interface FeePayment {
  id: string;
  invoice: { id: string; institution: string; reference: string };
  route: 'client_direct' | 'held_funds';
  amount: ApiMoney;
  status: string;
  release_instruction: string | null;
  release_status: string | null;
  client_paid_on: string | null;
  client_transfer_reference: string;
  client_reported_at: string | null;
  institution_confirmed_at: string | null;
  paid_at: string | null;
  receipt_due_at: string | null;
  receipt_received_at: string | null;
  pay_to: { bank_name: string; account_name: string; account_number: string; currency: string; amount: ApiMoney; reference: string; note: string } | null;
}

/** A bill payment by either route (SCR-PTL-40, FR-FEE-004, FR-FEE-005): what is paid, to whom, and the receipt. */
export default function FeePaymentScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const p = useGet<FeePayment>(`/v1/fee-payments/${id}`);
  const act = useAction();
  const [ref, setRef] = useState('');
  const today = new Date().toISOString().slice(0, 10);
  const d = p.data;

  async function reportPaid() {
    const r = await act.run('POST', `/v1/fee-payments/${id}/client-payment`, { paid_on: today, reference: ref.trim() });
    if (r) p.reload();
  }

  const direct = d?.route === 'client_direct';
  const steps: CaseStep[] = d
    ? direct
      ? [
          { id: 'a', title: 'You approved the bill', state: 'done' },
          { id: 'b', title: 'You pay the institution', detail: d.client_reported_at ? `Reported ${day(d.client_reported_at)}` : 'From your own bank, to its verified account', state: d.client_reported_at ? 'done' : 'current' },
          { id: 'c', title: 'The institution confirms', detail: d.institution_confirmed_at ? day(d.institution_confirmed_at) : undefined, state: d.institution_confirmed_at ? 'done' : d.client_reported_at ? 'current' : 'upcoming' },
          { id: 'd', title: 'Receipt', detail: d.receipt_received_at ? day(d.receipt_received_at) : d.receipt_due_at ? `Expected by ${day(d.receipt_due_at)}` : undefined, state: d.receipt_received_at ? 'done' : 'upcoming' },
        ]
      : [
          { id: 'a', title: 'You approved the bill', state: 'done' },
          { id: 'b', title: 'Two Tenmina staff approve', state: d.release_status && ['approved', 'sent', 'confirmed'].includes(d.release_status) ? 'done' : 'current' },
          { id: 'c', title: 'The bank pays the institution', detail: d.paid_at ? day(d.paid_at) : undefined, state: d.paid_at ? 'done' : 'upcoming' },
          { id: 'd', title: 'Receipt', detail: d.receipt_received_at ? day(d.receipt_received_at) : undefined, state: d.receipt_received_at ? 'done' : 'upcoming' },
        ]
    : [];

  return (
    <Screen ground="paper" back eyebrow={d ? `${d.invoice.reference}` : 'Payment'} title={d ? d.invoice.institution : undefined}>
      <LoadState loading={p.loading} problem={p.problem} onRetry={p.reload} hasData={!!d} />
      {d ? (
        <>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[2] }}>
            <T v="title" style={{ flex: 1 }}>{money(d.amount)}</T>
            <Chip label={words(d.status)} tone={d.receipt_received_at ? 'lime' : 'paper'} />
          </View>
          <T v="callout" muted>{direct ? 'You pay the institution directly.' : 'Paid by the partner bank from your held money.'}</T>
          <StepTrail steps={steps} />

          {direct && d.pay_to && !d.client_reported_at ? (
            <>
              <Panel tone="raised">
                <Label color="#A9A69E">Pay this account, from your own bank</Label>
                {[
                  ['Bank', d.pay_to.bank_name],
                  ['Account name', d.pay_to.account_name],
                  ['Account number', d.pay_to.account_number],
                  ['Amount', money(d.pay_to.amount)],
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
                <Field label="Your transfer reference (optional)" value={ref} onChange={setRef} />
                <Button title="I have paid" variant="dark" loading={act.busy} onPress={() => void reportPaid()} />
              </Panel>
            </>
          ) : null}
          {!direct && d.release_instruction && d.release_status === 'awaiting_client' ? (
            <Button title="Approve the payment" icon="arrow-forward" onPress={() => router.push(`/release/${d.release_instruction}`)} />
          ) : null}
          <ProblemBox problem={act.problem} />
          <Button title="Open the bill" variant="quiet" onPress={() => router.push(`/invoice/${d.invoice.id}`)} />
        </>
      ) : null}
    </Screen>
  );
}
