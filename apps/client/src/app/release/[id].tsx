import { useLocalSearchParams } from 'expo-router';
import { Screen } from '@tenmina/ui';
import { LoadState, day, moneyOf, toProblem, useApi, useLoad, words } from '@tenmina/mobile';
import { ApprovalSheet } from '../../components/ApprovalSheet';
import type { Escrow, Instruction } from '../../lib';

const NOT_YOURS: Record<string, string> = {
  pending_approval: 'You have approved this. Two Tenmina staff are approving it now.',
  approved: 'Approved by you and two staff. The bank pays next.',
  sent: 'Sent to the bank. The receipt comes here when the bank pays.',
  confirmed: 'Paid by the bank.',
  declined: 'You declined this payment. Nothing was paid.',
  withdrawn: 'Tenmina withdrew this payment. Nothing was paid.',
};

/**
 * Approve a release (W-15 client step, SCR-PTL-17 and SCR-PTL-23): every money
 * movement from a held account, whether a purchase, a milestone, a carer's visit
 * or an errand fee. The client approves first; then two staff; then the bank pays.
 */
export default function ReleaseSheet() {
  const api = useApi();
  const { id } = useLocalSearchParams<{ id: string }>();
  const data = useLoad(async (a) => {
    const ins = await a.get<Instruction>(`/v1/release-instructions/${id}`);
    const escrow = await a.get<Escrow>(`/v1/escrows/${ins.escrow}`).catch(() => null);
    return { ins, escrow };
  }, `release-${id}`);

  if (!data.data) {
    return (
      <Screen ground="ink">
        <LoadState loading={data.loading} problem={data.problem} onRetry={data.reload} hasData={false} />
      </Screen>
    );
  }
  const { ins, escrow } = data.data;
  const conditions = (escrow?.conditions ?? []).filter((c) => c.status !== 'waived');
  const mismatch = ins.blocking_reasons.some((b) => /name/i.test(b.message) && /match/i.test(b.message));
  const blockers =
    ins.status !== 'awaiting_client'
      ? [NOT_YOURS[ins.status] ?? `This payment is ${words(ins.status).toLowerCase()}. Nothing for you to do now.`]
      : ins.blocking_reasons.map((b) => `${b.message} (${b.rule})`);

  return (
    <ApprovalSheet
      title="Approve this payment"
      source={`From ${ins.escrow_reference} · ${day(ins.created_at)}`}
      amount={ins.money}
      description={ins.subject_label || ins.reason}
      payee={{ name: ins.payee_name, last4: ins.payee_account_last4, matched: mismatch ? false : true }}
      checks={[
        { label: 'Payee checked by Tenmina and the bank', ok: !mismatch },
        ...conditions.map((c) => ({ label: c.text, ok: c.status === 'closed', detail: c.closed_at ? day(c.closed_at) : undefined })),
        ...(Number(ins.holdback_amount) > 0 ? [{ label: `${moneyOf(ins.holdback_amount, ins.currency)} held back for defects`, ok: true }] : []),
      ]}
      blockers={blockers}
      approvedMessage={`Two Tenmina staff check next, then the bank pays ${ins.payee_name}. The money stays at the bank until then.`}
      onApprove={async (code) => {
        try {
          await api.post(`/v1/release-instructions/${id}/client-approval`, { approve: true, code, gesture: 'press_and_hold' });
          return undefined;
        } catch (e) {
          return toProblem(e);
        }
      }}
      onDecline={async (reason) => {
        try {
          await api.post(`/v1/release-instructions/${id}/client-approval`, { approve: false, reason });
          return undefined;
        } catch (e) {
          return toProblem(e);
        }
      }}
    />
  );
}

