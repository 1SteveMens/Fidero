import { View } from 'react-native';
import { useLocalSearchParams } from 'expo-router';
import { brand, space } from '@tenmina/tokens';
import { Label, Panel, Screen, T } from '@tenmina/ui';
import { LoadState, toProblem, useApi, useLoad, when, words } from '@tenmina/mobile';
import { ApprovalSheet } from '../../components/ApprovalSheet';
import type { Escrow } from '../../lib';

interface PayeeChange {
  id: string;
  kind: string;
  escrow: string | null;
  reason: string;
  request_source: string;
  bank_name: string;
  account_name: string;
  account_last4: string;
  account_name_source: string;
  account_checked_by: string | null;
  previous_last4: string;
  previous_account_name: string;
  national_id_check: string | null;
  client_approved_at: string | null;
  cooling_off_until: string | null;
  requested_at: string;
  status: string;
}

const SOURCE: Record<string, string> = {
  payee_signed_in: 'The payee asked, signed in to Tenmina',
  staff_on_call: 'The payee asked by phone; Tenmina called back on the number we hold',
  client: 'You asked',
};

/**
 * Approve a payee change (SCR-MOB-23, the app's SCR-PTL-55; W-42; FR-ESC-016,
 * RUL-28): who asked, the old and new account (masked), the checks done, and
 * the cooling-off end. A push opens it; only the code and press and hold approve it.
 */
export default function PayeeChangeSheet() {
  const api = useApi();
  const { id } = useLocalSearchParams<{ id: string }>();
  const data = useLoad(async (a) => {
    const ch = await a.get<PayeeChange>(`/v1/payee-changes/${id}`);
    const escrow = ch.escrow ? await a.get<Escrow>(`/v1/escrows/${ch.escrow}`).catch(() => null) : null;
    return { ch, escrow };
  }, `payee-change-${id}`);

  if (!data.data) {
    return (
      <Screen ground="ink">
        <LoadState loading={data.loading} problem={data.problem} onRetry={data.reload} hasData={false} />
      </Screen>
    );
  }
  const { ch, escrow } = data.data;
  const waiting = ['requested', 'checks_passed'].includes(ch.status) && !ch.client_approved_at;
  return (
    <ApprovalSheet
      title="Approve a new bank account"
      source={escrow ? `For ${escrow.reference} · ${escrow.title}` : 'Payee change'}
      amount={escrow?.agreed_price ?? { amount: '0', currency: 'GHS' }}
      description="Future payments from this escrow go to the new account below."
      payee={{ name: ch.account_name, bank: ch.bank_name.replace(/\s*\[TO VERIFY\]/, ''), last4: ch.account_last4, matched: ch.account_name_source === 'bank_name_check' ? true : null }}
      checks={[
        { label: 'Bank confirms the account name', ok: ch.account_name_source === 'bank_name_check' },
        { label: 'Identity of the person who asked checked', ok: !!ch.national_id_check },
        { label: SOURCE[ch.request_source] ?? words(ch.request_source), ok: true },
      ]}
      blockers={waiting ? [] : [ch.client_approved_at ? `You approved this on ${when(ch.client_approved_at)}. ${words(ch.status)}.` : `This change is ${words(ch.status).toLowerCase()}.`]}
      chain={['You', 'Staff 1', 'Staff 2', 'Cooling-off']}
      approvedMessage="Two Tenmina staff approve it next. Then a cooling-off period starts before any payment goes to the new account."
      onApprove={async (code) => {
        try {
          await api.post(`/v1/payee-changes/${id}/client-approval`, { approve: true, code, gesture: 'press_and_hold' });
          return undefined;
        } catch (e) {
          return toProblem(e);
        }
      }}
      onDecline={async (reason) => {
        try {
          await api.post(`/v1/payee-changes/${id}/client-approval`, { approve: false, reason });
          return undefined;
        } catch (e) {
          return toProblem(e);
        }
      }}
    >
      <Panel>
        <Label>Old account</Label>
        <T v="callout">{`${ch.previous_account_name || '—'} ••${ch.previous_last4 || '—'}`}</T>
        <Label color={brand.orange}>New account</Label>
        <T v="headline">{`${ch.account_name} ••${ch.account_last4}`}</T>
        <View style={{ gap: space[1] }}>
          <T v="footnote" muted>{`Reason given: ${ch.reason || '—'}`}</T>
          <T v="footnote" muted>{`Asked ${when(ch.requested_at)}${ch.cooling_off_until ? ` · cooling-off ends ${when(ch.cooling_off_until)}` : ''}`}</T>
        </View>
      </Panel>
    </ApprovalSheet>
  );
}
