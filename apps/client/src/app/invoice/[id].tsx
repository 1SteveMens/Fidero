import { View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, space } from '@tenmina/tokens';
import { Button, Label, Panel, Screen, T } from '@tenmina/ui';
import { KV, LoadState, day, money, toProblem, useApi, useLoad, words, type ApiMoney } from '@tenmina/mobile';
import { ApprovalSheet } from '../../components/ApprovalSheet';

interface Invoice {
  id: string;
  institution: string;
  family_member: string | null;
  institution_reference: string;
  description: string;
  amount: ApiMoney;
  due_on: string | null;
  name_on_invoice: string;
  institution_name_on_invoice: string;
  check_status: string;
  check_flags: string[];
  checked_by_name: string;
  checked_at: string | null;
  contact_confirmed: boolean;
  route: 'client_direct' | 'held_funds';
  status: string;
  status_text: string;
  payment: { id: string } | string | null;
  created_at: string;
}

interface Preview {
  route: 'client_direct' | 'held_funds';
  institution: { id: string; name: string; payee_status: string; name_match: string; account_name: string; account_last4: string };
  family_member: { id: string; relationship: string } | null;
  amount: ApiMoney;
}

/**
 * Pay an invoice (SCR-PTL-40, W-27; FR-FEE-003): the institution's bill,
 * checked by Tenmina, paid by either route. On "you pay directly" the client
 * pays the institution's verified account; on "from your held money" the bank
 * pays it after two staff approve. There is no cash route (FR-FEE-006).
 */
export default function InvoiceSheet() {
  const api = useApi();
  const { id } = useLocalSearchParams<{ id: string }>();
  const data = useLoad(async (a) => {
    const inv = await a.get<Invoice>(`/v1/invoices/${id}`);
    const preview = inv.status === 'checked' ? await a.get<Preview>(`/v1/invoices/${id}/approval-preview`).catch(() => null) : null;
    return { inv, preview };
  }, `invoice-${id}`);

  if (!data.data) {
    return (
      <Screen ground="ink" back>
        <LoadState loading={data.loading} problem={data.problem} onRetry={data.reload} hasData={false} />
      </Screen>
    );
  }
  const { inv, preview } = data.data;
  const paymentId = typeof inv.payment === 'string' ? inv.payment : inv.payment?.id;

  if (inv.status !== 'checked' || !preview) {
    return (
      <Screen ground="ink" back title={inv.description} eyebrow={`${inv.institution_reference} · ${inv.institution_name_on_invoice || ''}`}>
        <Panel>
          <Label>{words(inv.status)}</Label>
          <T v="title">{money(inv.amount)}</T>
          <T v="callout">{inv.status_text}</T>
        </Panel>
        <KV
          rows={[
            ['Route', inv.route === 'client_direct' ? 'You pay the institution directly' : 'From your money held at the bank'],
            ['Due', day(inv.due_on)],
            ['Checked', inv.checked_at ? `${day(inv.checked_at)}${inv.checked_by_name ? ` by ${inv.checked_by_name}` : ''}` : 'Not yet'],
            ['Name on bill', inv.name_on_invoice || '—'],
          ]}
        />
        {paymentId ? <Button title="Open the payment" icon="arrow-forward" onPress={() => router.push(`/fee-payment/${paymentId}`)} /> : null}
      </Screen>
    );
  }

  const inst = preview.institution;
  const direct = preview.route === 'client_direct';
  return (
    <ApprovalSheet
      title={`Pay ${inst.name}`}
      source={`${inv.institution_reference} · due ${day(inv.due_on)}`}
      amount={preview.amount}
      description={inv.description}
      payee={{ name: inst.account_name, last4: inst.account_last4, matched: inst.name_match === 'matched' ? true : inst.name_match ? false : null, place: inv.name_on_invoice || undefined }}
      checks={[
        { label: 'Institution verified by Tenmina', ok: inst.payee_status === 'verified' },
        { label: `Bill checked${inv.checked_by_name ? ` by ${inv.checked_by_name}` : ''}`, ok: inv.check_status === 'checked', detail: inv.checked_at ? day(inv.checked_at) : undefined },
        { label: 'Confirmed with the institution', ok: inv.contact_confirmed },
      ]}
      chain={direct ? ['You', 'You pay', 'Receipt'] : undefined}
      after={
        direct
          ? [
              { title: 'You pay the institution', detail: `From your own bank, to ${inst.account_name} ••${inst.account_last4}` },
              { title: 'The institution confirms', detail: 'Tenmina checks it with the institution' },
              { title: 'The receipt comes here', detail: 'With the institution’s confirmation' },
            ]
          : undefined
      }
      blockers={inst.payee_status !== 'verified' ? ['The institution is not verified yet. We pay only verified institutions (RUL-22).'] : []}
      approvedMessage={
        direct
          ? `Next, pay ${inst.account_name} from your own bank. The account details are on the payment screen. Never pay Tenmina or a relative.`
          : `Two Tenmina staff check next, then the bank pays ${inst.account_name} from your held money. Its receipt comes back here.`
      }
      onApprove={async (code) => {
        try {
          await api.post(`/v1/invoices/${id}/client-approval`, { code, confirm_amount: preview.amount, confirm_payee_account_name: inst.account_name });
          return undefined;
        } catch (e) {
          return toProblem(e);
        }
      }}
      onDecline={async (reason) => {
        try {
          await api.post(`/v1/invoices/${id}/client-decline`, { reason });
          return undefined;
        } catch (e) {
          return toProblem(e);
        }
      }}
    >
      <View style={{ flexDirection: 'row', gap: space[3], alignItems: 'flex-start' }}>
        <Ionicons name={direct ? 'swap-horizontal-outline' : 'business-outline'} size={20} color={brand.lime} />
        <T v="callout" muted style={{ flex: 1 }}>
          {direct
            ? `Route: you pay ${inst.name} directly, into its verified account. Tenmina confirms it with the institution.`
            : `Route: the partner bank pays ${inst.name} from your held money. Never to a person.`}
        </T>
      </View>
    </ApprovalSheet>
  );
}
