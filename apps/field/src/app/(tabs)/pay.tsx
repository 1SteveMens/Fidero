import { View } from 'react-native';
import Ionicons from '@expo/vector-icons/Ionicons';
import { formatMoney } from '@tenmina/shared';
import { brand, space } from '@tenmina/tokens';
import { ErrorView, IconTile, Label, Loading, Panel, Rise, Screen, T } from '@tenmina/ui';
import { useField, useFieldLoad } from '../../store';

/**
 * My pay (W-40, SCR-MOB-19). Only black, white and lime here: no yellow, red or orange,
 * so nothing next to an amount hints at a verdict or result (03 section 5.6b, RUL-26).
 */
export default function Pay() {
  const { role } = useField();
  const { data, error, reload } = useFieldLoad((api) => api.getEarnings(), 'earnings');

  if (role !== 'inspector') {
    return (
      <Screen ground="paper" tabs title="Pay">
        <Panel style={{ flexDirection: 'row', alignItems: 'flex-start' }}>
          <Ionicons name="information-circle-outline" size={22} color={brand.ink} />
          <T v="callout" style={{ flex: 1 }}>
            {role === 'carer'
              ? 'Carers are paid for each visit the family confirms, from the money the family holds at the bank. Your confirmed visits will show here.'
              : 'Contractors are paid by the bank for each milestone that passes inspection. Your milestone payments will show here.'}
          </T>
        </Panel>
      </Screen>
    );
  }

  return (
    <Screen ground="paper" tabs title="My pay" trailing={data ? <Label>{data.monthLabel}</Label> : undefined}>
      {error ? <ErrorView message={error} onRetry={reload} /> : null}
      {!data && !error ? <Loading /> : null}
      {data ? (
        <>
          <Rise style={{ flexDirection: 'row', gap: space[2] }}>
            <Panel style={{ flex: 1, gap: space[1] }}>
              <T v="footnote" muted>Accepted, not yet paid</T>
              <T v="title" style={{ fontSize: 20 }}>{formatMoney(data.acceptedNotPaid)}</T>
            </Panel>
            <Panel style={{ flex: 1, gap: space[1] }}>
              <T v="footnote" muted>Paid this month</T>
              <T v="title" style={{ fontSize: 20 }}>{formatMoney(data.paidThisMonth)}</T>
            </Panel>
          </Rise>
          <Rise delay={80}>
            <Panel tone="raised" style={{ flexDirection: 'row', alignItems: 'center' }}>
              <IconTile name="calendar-outline" tone="lime" size={44} />
              <View style={{ flex: 1 }}>
                <T v="headline" color="#F7F6F2">{`Next payment run: ${data.nextRunOn}`}</T>
                <T v="footnote" color="#A9A69E">{`Paid by Tenmina, from its own account, to your account ••${data.payToLast4}`}</T>
              </View>
            </Panel>
          </Rise>
          <Rise delay={160}>
            <T v="headline" header style={{ fontSize: 18, marginBottom: space[1] }}>Jobs</T>
            {data.payables.map((p, i) => (
              <View key={p.id} style={{ paddingVertical: space[3], borderBottomWidth: i < data.payables.length - 1 ? 1 : 0, borderBottomColor: '#ECEAE4', gap: 2 }}>
                <View style={{ flexDirection: 'row', justifyContent: 'space-between', gap: space[2] }}>
                  <T v="headline" style={{ fontSize: 15, flex: 1 }}>{p.workType}</T>
                  <T v="headline" style={{ fontSize: 15 }}>{formatMoney(p.amount)}</T>
                </View>
                <Label>{`${p.ref} · accepted ${p.acceptedOn}`}</Label>
                <T v="footnote">{p.note}</T>
              </View>
            ))}
          </Rise>
          <T v="footnote" muted>Your pay is the same whatever a report or an inspection finds.</T>
        </>
      ) : null}
    </Screen>
  );
}
