import { Pressable, View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import { space } from '@tenmina/tokens';
import { Label, Panel, Screen, T } from '@tenmina/ui';
import { LoadState, Section, day, money, words, useGet, type ApiMoney } from '@tenmina/mobile';
import { Figures } from '../../components/rows';

interface Statement {
  family_member: { id: string; full_name: string; relationship: string };
  lines: { at: string; type: string; id: string; institution: string; reference: string; description: string; amount: ApiMoney | null; status: string; route?: string }[];
  totals: Record<string, ApiMoney | string | number> | null;
  held_at_bank: ApiMoney | null;
  note: string;
}

/** Family-member statement (SCR-PTL-42, W-28; FR-FEE-007): every bill, payment and receipt for one person. */
export default function MemberStatement() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const s = useGet<Statement>(`/v1/family-members/${id}/statement`);
  const d = s.data;
  const totals = Object.entries(d?.totals ?? {}).filter(([, v]) => v && typeof v === 'object' && 'amount' in (v as object)) as [string, ApiMoney][];
  return (
    <Screen ground="paper" back eyebrow={d ? words(d.family_member.relationship) : 'Statement'} title={d?.family_member.full_name}>
      <LoadState loading={s.loading} problem={s.problem} onRetry={s.reload} hasData={!!d} />
      {d ? (
        <>
          {totals.length || d.held_at_bank ? <Figures items={[...totals.slice(0, 3).map(([k, v]) => [words(k), v] as [string, ApiMoney]), ...(d.held_at_bank ? ([['Held at the bank', d.held_at_bank]] as [string, ApiMoney][]) : [])]} /> : null}
          <Section title={`Statement · ${d.lines.length} lines`}>
            <Panel style={{ gap: 0, paddingVertical: space[1] }}>
              {[...d.lines].reverse().map((l, i) => (
                <Pressable
                  key={`${l.type}-${l.id}-${i}`}
                  disabled={l.type !== 'invoice'}
                  accessibilityRole={l.type === 'invoice' ? 'button' : undefined}
                  style={{ paddingVertical: space[3], borderTopWidth: i ? 1 : 0, borderTopColor: '#ECEAE4', gap: 2 }}
                  onPress={() => router.push(`/invoice/${l.id}`)}
                >
                  <View style={{ flexDirection: 'row', gap: space[2] }}>
                    <T v="callout" style={{ flex: 1 }}>{`${l.description} · ${l.institution}`}</T>
                    {l.amount ? <T v="headline" style={{ fontSize: 15 }}>{money(l.amount)}</T> : null}
                  </View>
                  <Label>{`${day(l.at)} · ${words(l.type)} · ${words(l.status)}${l.route ? ` · ${l.route === 'held_funds' ? 'paid by the bank' : 'paid by you'}` : ''}`}</Label>
                </Pressable>
              ))}
            </Panel>
          </Section>
          {d.note ? <T v="footnote" muted>{d.note}</T> : null}
        </>
      ) : null}
    </Screen>
  );
}
