import { useEffect } from 'react';
import { View } from 'react-native';
import { router } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, space } from '@tenmina/tokens';
import { Button, Chip, IconTile, Label, Panel, Rise, Screen, T } from '@tenmina/ui';
import { day, itemsOf, money, toProblem, useApi, useSession, when, words, type ApiMoney, type Problem } from '@tenmina/mobile';
import { useField } from '../../store';

export interface Payable {
  id: string;
  work_kind: string;
  work_period: string | null;
  case_reference: string | null;
  accepted_at: string | null;
  unit_rate: ApiMoney;
  quantity: string;
  gross: ApiMoney;
  withholding: ApiMoney;
  other_deductions: ApiMoney;
  net: ApiMoney;
  due_by: string | null;
  status: string;
  paid_at?: string | null;
  hold_reason?: string;
}

export interface PayCache {
  at: string;
  payables: Payable[];
  claims: { id: string; kind: string; description: string; amount: ApiMoney; status: string; incurred_on: string }[];
  statements: { id: string; kind: string; line_reference: string | null; tax_year: number | null; net: ApiMoney; issued_at: string }[];
  agreement: { reference: string; destination: { bank_name: string; account_last4: string } | null } | null;
}

/** Loads My pay and keeps it on the phone, so it reads offline, marked with its time (SCR-MOB-19). */
export function usePay(): { pay?: PayCache; problem?: Problem; refresh: () => Promise<void> } {
  const api = useApi();
  const { progress, setProgress, online } = useField();
  const cached = progress('pay') as { data?: PayCache; problem?: Problem };
  const refresh = async () => {
    try {
      const [payables, claims, statements, agreements] = await Promise.all([
        api.get<{ items: Payable[] }>('/v1/me/pro/payables'),
        api.get<{ items: PayCache['claims'] }>('/v1/me/pro/expense-claims'),
        api.get<{ items: PayCache['statements'] }>('/v1/me/pro/statements'),
        api.get<PayCache['agreement'][]>('/v1/me/pro/agreement'),
      ]);
      setProgress('pay', { data: { at: new Date().toISOString(), payables: itemsOf(payables), claims: itemsOf(claims), statements: itemsOf(statements), agreement: agreements[0] ?? null }, problem: undefined });
    } catch (e) {
      const p = toProblem(e);
      if (p.code !== 'offline') setProgress('pay', { problem: p });
    }
  };
  useEffect(() => {
    if (online) void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [online]);
  return { pay: cached.data, problem: cached.problem, refresh };
}

function sum(list: ApiMoney[]): ApiMoney | null {
  if (!list.length) return null;
  return { amount: list.reduce((n, m) => n + Number(m.amount), 0).toFixed(2), currency: list[0].currency };
}

/**
 * My pay (W-40; SCR-MOB-19 to 22; FR-PRO-002, FR-PRO-008, RUL-26). Black,
 * white and lime only: no yellow, red or orange next to an amount, so nothing
 * hints that pay depends on a verdict or a result.
 */
export default function Pay() {
  const { hasRole } = useSession();
  const { pay, problem, refresh } = usePay();
  const professional = hasRole('RN', 'SV', 'IN', 'QS', 'LW');

  if (!professional || problem?.status === 403) {
    return (
      <Screen ground="paper" tabs title="Pay">
        <Panel style={{ flexDirection: 'row', alignItems: 'flex-start' }}>
          <Ionicons name="information-circle-outline" size={22} color={brand.ink} />
          <T v="callout" style={{ flex: 1 }}>
            {hasRole('CT')
              ? 'Contractors are paid by the bank for each milestone that passes inspection, after the client and two Tenmina staff approve.'
              : 'Carers and errand agents are paid from the money the family holds at the bank, for each visit or step that is confirmed.'}
          </T>
        </Panel>
      </Screen>
    );
  }

  const unpaid = (pay?.payables ?? []).filter((p) => p.status !== 'paid' && p.status !== 'cancelled');
  const thisMonth = (pay?.payables ?? []).filter((p) => p.status === 'paid' && (p.paid_at ?? '').slice(0, 7) === new Date().toISOString().slice(0, 7));
  return (
    <Screen ground="paper" tabs title="My pay" trailing={pay ? <Label>{`As of ${when(pay.at)}`}</Label> : undefined}>
      {!pay ? (
        <Panel>
          <T v="callout">{problem ? problem.detail : 'Loading your pay. It needs signal the first time.'}</T>
          <Button title="Try again" variant="dark" onPress={() => void refresh()} />
        </Panel>
      ) : (
        <>
          <Rise style={{ flexDirection: 'row', gap: space[2] }}>
            <Panel style={{ flex: 1, gap: space[1] }}>
              <T v="footnote" muted>Accepted, not yet paid</T>
              <T v="title" style={{ fontSize: 20 }}>{money(sum(unpaid.map((p) => p.net)) ?? { amount: '0', currency: pay.payables[0]?.net.currency ?? 'GHS' })}</T>
            </Panel>
            <Panel style={{ flex: 1, gap: space[1] }}>
              <T v="footnote" muted>Paid this month</T>
              <T v="title" style={{ fontSize: 20 }}>{money(sum(thisMonth.map((p) => p.net)) ?? { amount: '0', currency: pay.payables[0]?.net.currency ?? 'GHS' })}</T>
            </Panel>
          </Rise>
          <Panel tone="raised" style={{ flexDirection: 'row', alignItems: 'center' }}>
            <IconTile name="business-outline" tone="lime" size={44} />
            <View style={{ flex: 1 }}>
              <T v="headline" color="#F7F6F2">{pay.agreement ? `Agreement ${pay.agreement.reference}` : 'Your agreement'}</T>
              <T v="footnote" color="#A9A69E">{pay.agreement?.destination ? `Paid by Tenmina from its own account, to ${pay.agreement.destination.bank_name.replace(/\s*\[TO VERIFY\]/, '')} ••${pay.agreement.destination.account_last4}` : 'Paid by Tenmina from its own account'}</T>
            </View>
          </Panel>
          <View style={{ flexDirection: 'row', gap: space[2] }}>
            <View style={{ flex: 1 }}>
              <Button title="Claim an expense" variant="dark" icon="receipt-outline" onPress={() => router.push('/pay/claim')} />
            </View>
            <View style={{ flex: 1 }}>
              <Button title="Statements" variant="dark" icon="document-text-outline" onPress={() => router.push('/pay/statements')} />
            </View>
          </View>
          <Rise delay={120}>
            <T v="headline" header style={{ fontSize: 18, marginBottom: space[1] }}>Jobs and pay</T>
            {pay.payables.length ? (
              pay.payables.map((p, i) => (
                <Panel key={p.id} tone="ground" onPress={() => router.push({ pathname: '/pay/[id]', params: { id: p.id } })} style={{ paddingHorizontal: 0, paddingVertical: space[3], borderRadius: 0, borderBottomWidth: i < pay.payables.length - 1 ? 1 : 0, borderBottomColor: '#ECEAE4', gap: 2 }}>
                  <View style={{ flexDirection: 'row', justifyContent: 'space-between', gap: space[2] }}>
                    <T v="headline" style={{ fontSize: 15, flex: 1 }}>{`${words(p.work_kind)}${p.case_reference ? ` · ${p.case_reference}` : ''}`}</T>
                    <T v="headline" style={{ fontSize: 15 }}>{money(p.net)}</T>
                  </View>
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[2] }}>
                    <Label style={{ flex: 1 }}>{`${p.accepted_at ? `Accepted ${day(p.accepted_at)}` : 'Not accepted yet'}${p.due_by ? ` · due by ${day(p.due_by)}` : ''}`}</Label>
                    <Chip label={words(p.status)} tone={p.status === 'paid' ? 'lime' : 'paper'} />
                  </View>
                </Panel>
              ))
            ) : (
              <T v="callout" muted>No pay yet. Accepted work shows here.</T>
            )}
          </Rise>
          <T v="footnote" muted>Your pay is the same whatever a report or an inspection finds.</T>
        </>
      )}
    </Screen>
  );
}
