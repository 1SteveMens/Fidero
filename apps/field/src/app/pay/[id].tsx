import { useLocalSearchParams } from 'expo-router';
import { Chip, Label, Panel, Screen, T } from '@tenmina/ui';
import { KV, LoadState, day, money, useGet, words } from '@tenmina/mobile';
import type { Payable } from '../(tabs)/pay';

/** Payable detail (SCR-MOB-20, as SCR-BO-34; FR-PRO-002, FR-PRO-007): the rate, the deductions and the net. Black, white and lime only. */
export default function PayableScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const p = useGet<Payable>(`/v1/me/pro/payables/${id}`);
  const d = p.data;
  return (
    <Screen ground="paper" back title={d ? words(d.work_kind) : 'Payable'} eyebrow={d?.case_reference ?? undefined}>
      <LoadState loading={p.loading} problem={p.problem} onRetry={p.reload} hasData={!!d} />
      {d ? (
        <>
          <Panel>
            <Label>Net to you</Label>
            <T v="amount" style={{ fontSize: 34, lineHeight: 40 }}>{money(d.net)}</T>
            <Chip label={words(d.status)} tone={d.status === 'paid' ? 'lime' : 'paper'} />
          </Panel>
          <KV
            rows={[
              ['Rate', `${money(d.unit_rate)} × ${Number(d.quantity)}`],
              ['Gross', money(d.gross)],
              ['Tax withheld', money(d.withholding)],
              ['Other deductions', money(d.other_deductions)],
              ['Accepted', day(d.accepted_at)],
              ['Due by', day(d.due_by)],
              ...(d.work_period ? ([['Period', day(d.work_period)]] as [string, string][]) : []),
            ]}
          />
          {d.hold_reason ? (
            <Panel>
              <Label>On hold</Label>
              <T v="callout">{d.hold_reason}</T>
            </Panel>
          ) : null}
          <T v="footnote" muted>Tenmina pays from its own account in the monthly payment run. The amount never depends on what a report or an inspection found.</T>
        </>
      ) : null}
    </Screen>
  );
}
