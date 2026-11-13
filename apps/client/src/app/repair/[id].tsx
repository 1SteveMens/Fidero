import { useState } from 'react';
import { View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import { space } from '@tenmina/tokens';
import { Button, Chip, Choice, Label, Panel, Screen, T } from '@tenmina/ui';
import { LoadState, day, money, useApi, useGet, words, type ApiMoney } from '@tenmina/mobile';
import { InlineApproval } from '../../components/InlineApproval';

interface Repair {
  id: string;
  property: string;
  property_title: string;
  title: string;
  description: string;
  urgent: boolean;
  status: string;
  quotes: { id: string; contractor: { name: string }; payee: { name: string; status: string; account_last4: string }; amount: ApiMoney; valid_until: string; status: string; track_record: { completed: number; disputes: number } }[];
  quotes_needed: number;
  approval_blockers: { message: string }[] | string[];
  approved_quote: string | null;
  escrow: string | null;
  release_instruction: string | null;
  paid_at: string | null;
}

/**
 * Repair quote approval (SCR-PTL-48, W-33; FR-PMG-005): compare the quotes, pick
 * one, approve with the code and press and hold. The money is then held at the
 * bank and paid only after Tenmina inspects the work.
 */
export default function RepairScreen() {
  const api = useApi();
  const { id } = useLocalSearchParams<{ id: string }>();
  const r = useGet<Repair>(`/v1/repairs/${id}`);
  const [pick, setPick] = useState<string>();
  const d = r.data;
  const quote = d?.quotes.find((q) => q.id === pick);
  const blockers = (d?.approval_blockers ?? []).map((b) => (typeof b === 'string' ? b : b.message));

  return (
    <Screen ground="paper" back eyebrow={d?.property_title} title={d?.title}>
      <LoadState loading={r.loading} problem={r.problem} onRetry={r.reload} hasData={!!d} />
      {d ? (
        <>
          <View style={{ flexDirection: 'row', gap: space[2] }}>
            <Chip label={words(d.status)} tone={d.paid_at ? 'lime' : 'paper'} />
            {d.urgent ? <Chip label="Urgent" tone="paper" /> : null}
          </View>
          {d.description ? <T v="callout">{d.description}</T> : null}
          <Panel style={{ gap: 0 }}>
            <Label>{`Quotes · ${d.quotes.length} of ${d.quotes_needed} needed`}</Label>
            {d.quotes.map((q) => (
              <Choice
                key={q.id}
                selected={pick === q.id}
                onPress={() => d.status === 'quotes_ready' && setPick(q.id)}
                title={`${money(q.amount)} · ${q.contractor.name}`}
                detail={`Paid to ${q.payee.name} ••${q.payee.account_last4} · ${q.track_record.completed} jobs done · valid to ${day(q.valid_until)}`}
              />
            ))}
          </Panel>
          {blockers.map((b) => (
            <T key={b} v="footnote" muted>{b}</T>
          ))}
          {d.status === 'quotes_ready' && quote ? (
            <InlineApproval
              title={`Repair: ${d.title}`}
              amount={quote.amount}
              payee={quote.payee.name}
              note="Paid only after Tenmina inspects the work."
              onApprove={() => api.post(`/v1/repairs/${id}/quote-approvals`, { quote_id: quote.id, confirm_amount: quote.amount })}
              onDone={r.reload}
            />
          ) : null}
          {d.release_instruction && d.status !== 'paid' ? <Button title="Open the payment" onPress={() => router.push(`/release/${d.release_instruction}`)} /> : null}
          <Button title="Back to the property" variant="quiet" onPress={() => router.push(`/managed/${d.property}`)} />
        </>
      ) : null}
    </Screen>
  );
}
