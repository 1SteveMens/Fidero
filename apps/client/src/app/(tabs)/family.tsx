import { View } from 'react-native';
import { router } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, space } from '@tenmina/tokens';
import { IconButton, Panel, Rise, Screen, T } from '@tenmina/ui';
import { LoadState, Section, initials, words } from '@tenmina/mobile';
import { ItemList, NeedsYouList, StartTile, useHome } from '../../components/rows';
import type { HomeItem } from '../../lib';

const LINES = ['fee', 'care', 'errands', 'ins', 'evt', 'family'];

/**
 * Family (03 2.3a): each family member with their bills, care and errands, then
 * insurance and events. We pay institutions, carers and vendors directly. Never
 * cash to a person (RUL-22).
 */
export default function Family() {
  const home = useHome();
  const d = home.data;
  const items = (d?.items ?? []).filter((i) => LINES.includes(i.line) || !!i.family_member_id);
  const forMember = (id: string) => items.filter((i) => i.family_member_id === id);
  const general = items.filter((i) => !i.family_member_id);
  const group = (lines: string[]): HomeItem[] => general.filter((i) => lines.includes(i.line));

  return (
    <Screen ground="paper" tabs title="Family" trailing={<IconButton icon="person-add-outline" tone="lime" label="Add a family member" onPress={() => router.push('/member/new')} />}>
      <Rise delay={40}>
        <Panel tone="raised" style={{ flexDirection: 'row', alignItems: 'center', paddingVertical: space[3] }}>
          <Ionicons name="shield-checkmark-outline" size={22} color={brand.lime} />
          <T v="callout" color="#F7F6F2" style={{ flex: 1 }}>We pay hospitals, schools, carers and vendors directly. Never cash to a person.</T>
        </Panel>
      </Rise>
      <LoadState loading={home.loading} problem={home.problem} onRetry={home.reload} hasData={!!d} />
      {d ? <NeedsYouList items={items.filter((i) => i.needs_action)} limit={0} /> : null}
      {d?.family_members.map((m, i) => {
        const rows = forMember(m.id);
        return (
          <Rise key={m.id} delay={100 + i * 80}>
            <Panel>
              <Panel tone="ground" onPress={() => router.push(`/member/${m.id}`)} accessibilityLabel={`${m.full_name}, ${m.relationship}. Open the statement.`} style={{ flexDirection: 'row', alignItems: 'center', gap: space[3], padding: 0, backgroundColor: 'transparent' }}>
                <View style={{ width: 48, height: 48, borderRadius: 16, backgroundColor: i % 2 === 0 ? brand.ink : brand.lime, alignItems: 'center', justifyContent: 'center' }}>
                  <T v="headline" color={i % 2 === 0 ? '#F7F6F2' : brand.ink}>{initials(m.full_name)}</T>
                </View>
                <View style={{ flex: 1 }}>
                  <T v="title" style={{ fontSize: 19, lineHeight: 23 }}>{m.full_name}</T>
                  <T v="footnote" muted>{`${words(m.relationship)} · ${m.address}`}</T>
                </View>
                <Ionicons name="chevron-forward" size={18} color="#6A675F" />
              </Panel>
              {rows.length ? <ItemList items={[...rows.filter((r) => r.needs_action), ...rows.filter((r) => !r.needs_action).slice(0, 4)]} /> : null}
              {!rows.length ? <T v="footnote" muted>Nothing open for them right now.</T> : null}
            </Panel>
          </Rise>
        );
      })}
      {d ? (
        <>
          {group(['fee']).length ? (
            <Section title="Bills, institutions and fee schedules">
              <ItemList items={group(['fee'])} />
            </Section>
          ) : null}
          <Section title="Care">
            <ItemList items={group(['care'])} empty="No care plans yet." />
          </Section>
          <Section title="Paperwork and errands">
            <ItemList items={group(['errands'])} empty="No errands yet." />
          </Section>
          <Section title="Insurance: your policy wallet">
            <ItemList items={group(['ins'])} empty="No policies. Cover is sold only as a licensed insurer's product." />
          </Section>
          <Section title="Events">
            <ItemList items={group(['evt'])} empty="No events." />
          </Section>
          <T v="headline" header style={{ fontSize: 18, marginTop: space[2] }}>Start something new</T>
          <View style={{ flexDirection: 'row', gap: space[2] }}>
            <StartTile icon="person-add-outline" title="Add family" detail="Who we pay for" tone="lime" href="/member/new" />
            <StartTile icon="briefcase-outline" title="An errand" detail="Cards, certificates" tone="ink" href="/errand/new" />
          </View>
        </>
      ) : null}
    </Screen>
  );
}
