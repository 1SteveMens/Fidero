import { View } from 'react-native';
import { router } from 'expo-router';
import { brand, space } from '@tenmina/tokens';
import { Button, Label, Panel, Rise, Screen, T, TenminaAccountCard } from '@tenmina/ui';
import { LoadState, Section, money, toMinor, useGet } from '@tenmina/mobile';
import { COMMITMENT_KIND, commitmentState, type TenminaAccount } from '../lib';

/**
 * The client's one Tenmina account (SCR-PTL-57, W-45, decision 2026-11-17, FR-ESC-025 to 028): one card with the
 * balance, the free balance and the commitments inside it, then the one set of pay-in details. The bank holds the
 * money and releases it only on proof (RUL-01).
 */
export default function MoneyScreen() {
  const q = useGet<TenminaAccount>('/v1/account');
  const acc = q.data;
  const fundable = acc?.commitments.filter((c) => c.can_fund) ?? [];
  const pi = acc?.pay_in;
  return (
    <Screen ground="paper" back eyebrow="Held at the bank · released on proof">
      <T v="title" header>Your Tenmina account</T>
      <LoadState loading={q.loading} problem={q.problem?.status === 404 ? undefined : q.problem} onRetry={q.reload} hasData={!!acc} />
      {q.problem?.status === 404 ? (
        <Panel>
          <T v="headline">No account yet</T>
          <T v="callout" muted>Your Tenmina account is opened at the partner bank. Open it from the portal or ask your case manager.</T>
        </Panel>
      ) : null}
      {acc ? (
        <>
          <Rise>
            <TenminaAccountCard
              max={50}
              holder={acc.client_name.toUpperCase()}
              account={{
                reference: pi?.reference ?? acc.reference,
                heldAt: (pi?.bank_name ?? acc.bank_name).replace(/\s*\[TO VERIFY\]/, ''),
                href: '/money',
                balances: acc.balances.map((b) => ({ held: toMinor(b.held_at_bank), free: toMinor(b.free_balance), setAside: toMinor(b.set_aside) })),
                commitments: acc.commitments.filter((c) => !['released', 'cancelled'].includes(c.status) || Number(c.set_aside.amount) > 0).map((c) => ({
                  id: c.id, label: c.title, kind: COMMITMENT_KIND[c.kind] ?? c.kind, state: commitmentState(c), href: `/escrow/${c.id}`, needsYou: c.needs_you,
                  amount: toMinor(Number(c.set_aside.amount) > 0 ? c.set_aside : c.agreed), amountNote: Number(c.set_aside.amount) > 0 ? 'set aside' : 'agreed',
                })),
              }}
            />
          </Rise>
          {fundable.map((c) => (
            <Panel key={c.id} tone="orange">
              <Label color={brand.ink}>Needs you</Label>
              <T v="headline" color={brand.ink}>{`Set aside money for ${c.title}`}</T>
              <T v="footnote" color="#3A1408">{`Still to set aside: ${money(c.still_to_set_aside)}.`}</T>
              <Button title="Set aside from my balance" variant="dark" onPress={() => router.push(`/set-aside/${c.id}`)} />
            </Panel>
          ))}
          <Section title="Pay in: one set of details">
            {pi?.available ? (
              <Panel tone="raised">
                <Label>Pay the bank, never Tenmina</Label>
                <T v="headline" style={{ fontSize: 15 }}>{pi.bank_name}</T>
                <View style={{ flexDirection: 'row', gap: space[3] }}>
                  <T v="footnote" muted style={{ width: 110 }}>Your reference</T>
                  <T v="mono" color={brand.lime} style={{ flex: 1, fontSize: 14 }}>{pi.reference}</T>
                </View>
                {pi.lines.map((l) => (
                  <View key={`${l.currency}-${l.account_number}`} style={{ flexDirection: 'row', gap: space[3] }}>
                    <T v="footnote" muted style={{ width: 110 }}>{`${l.currency} account`}</T>
                    <T v="mono" style={{ flex: 1, fontSize: 14 }}>{`${l.account_name}\n${l.account_number}`}</T>
                  </View>
                ))}
                <T v="footnote" muted>{pi.note}</T>
              </Panel>
            ) : <T v="callout" muted>{pi?.message ?? 'The bank is opening your account.'}</T>}
          </Section>
        </>
      ) : null}
    </Screen>
  );
}
