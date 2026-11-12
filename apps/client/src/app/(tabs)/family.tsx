import { Pressable, View } from 'react-native';
import { router, type Href } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import type { HomeRow } from '@fidero/shared';
import { brand, radius, space } from '@fidero/tokens';
import { ArrowBox, ErrorView, IconButton, IconTile, Loading, Panel, Rise, Screen, T, haptic, type IconName } from '../../components/ui';
import { useLoad } from '../../data';
import { usePalette } from '../../theme';

function rowIcon(title: string): IconName {
  if (/hospital|bill/i.test(title)) return 'receipt-outline';
  if (/care/i.test(title)) return 'heart-outline';
  if (/fees|school|term/i.test(title)) return 'school-outline';
  return 'document-text-outline';
}

function FamilyRow({ row }: { row: HomeRow }) {
  const p = usePalette();
  if (row.href) {
    // Something waiting for the client: orange, and it opens.
    return (
      <Pressable
        onPress={() => {
          haptic('tap');
          router.push(row.href as Href);
        }}
        accessibilityRole="button"
        accessibilityLabel={`${row.title}. ${row.detail}`}
        style={({ pressed }) => ({ flexDirection: 'row', alignItems: 'center', gap: space[3], backgroundColor: brand.orange, borderRadius: radius.lg - 4, padding: space[3], opacity: pressed ? 0.85 : 1 })}
      >
        <IconTile name={rowIcon(row.title)} tone="ink" size={38} />
        <View style={{ flex: 1 }}>
          <T v="headline" color={brand.ink} style={{ fontSize: 15 }}>{row.title}</T>
          <T v="footnote" color="#3A1408">{row.detail}</T>
        </View>
        <ArrowBox arrow={brand.orange} />
      </Pressable>
    );
  }
  return (
    <View accessible accessibilityLabel={`${row.title}. ${row.detail}`} style={{ flexDirection: 'row', alignItems: 'center', gap: space[3], backgroundColor: p.ground, borderRadius: radius.lg - 4, padding: space[3] }}>
      <IconTile name={rowIcon(row.title)} tone="ink" size={38} />
      <View style={{ flex: 1 }}>
        <T v="headline" style={{ fontSize: 15 }}>{row.title}</T>
        <T v="footnote" muted>{row.detail}</T>
      </View>
    </View>
  );
}

export default function Family() {
  const { data, error, reload } = useLoad((api) => api.listFamily(), 'family');

  return (
    <Screen ground="paper" tabs title="Family" trailing={<IconButton icon="add" tone="lime" label="Add a family member" onPress={() => undefined} />}>
      <Rise delay={40}>
        <Panel tone="raised" style={{ flexDirection: 'row', alignItems: 'center', paddingVertical: space[3] }}>
          <Ionicons name="shield-checkmark-outline" size={22} color={brand.lime} />
          <T v="callout" color="#F7F6F2" style={{ flex: 1 }}>We pay hospitals, schools and carers directly. Never cash to a person.</T>
        </Panel>
      </Rise>
      {error ? <ErrorView message={error} onRetry={reload} /> : null}
      {!data && !error ? <Loading /> : null}
      {data?.map((m, i) => (
        <Rise key={m.id} delay={120 + i * 120}>
          <Panel>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[3] }}>
              <View style={{ width: 48, height: 48, borderRadius: 16, backgroundColor: i % 2 === 0 ? brand.ink : brand.lime, alignItems: 'center', justifyContent: 'center' }}>
                <T v="headline" color={i % 2 === 0 ? '#F7F6F2' : brand.ink}>{m.name.split(' ').map((w) => w[0]).join('')}</T>
              </View>
              <View style={{ flex: 1 }}>
                <T v="title" style={{ fontSize: 19, lineHeight: 23 }}>{m.name}</T>
                <T v="footnote" muted>{`${m.relationship} · ${m.place}`}</T>
              </View>
            </View>
            {m.rows.map((r) => (
              <FamilyRow key={r.id} row={r} />
            ))}
          </Panel>
        </Rise>
      ))}
    </Screen>
  );
}
