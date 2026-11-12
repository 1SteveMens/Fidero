import { Pressable, View } from 'react-native';
import { router, type Href } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, font, radius, space } from '@fidero/tokens';
import { AccountCards } from '../../components/money';
import { Mark } from '../../components/Mark';
import { ErrorView, IconButton, Label, ListRow, Loading, NeedsYou, Panel, Rise, Screen, T, VerdictChip, haptic, type IconName } from '../../components/ui';
import { useLoad } from '../../data';
import { usePalette } from '../../theme';

function Quick({ icon, label, tone, href, delay }: { icon: IconName; label: string; tone: 'lime' | 'ink' | 'surface'; href: Href; delay: number }) {
  const p = usePalette();
  const bg = tone === 'lime' ? brand.lime : tone === 'ink' ? brand.ink : p.surface;
  const fg = tone === 'lime' ? brand.ink : tone === 'ink' ? brand.lime : p.text;
  return (
    <Rise delay={delay} style={{ flex: 1 }}>
      <Pressable
        onPress={() => {
          haptic('tap');
          router.push(href);
        }}
        accessibilityRole="button"
        accessibilityLabel={label}
        style={({ pressed }) => ({ alignItems: 'center', gap: 6, opacity: pressed ? 0.8 : 1, transform: [{ scale: pressed ? 0.96 : 1 }] })}
      >
        <View style={{ width: 66, height: 66, borderRadius: radius.lg, backgroundColor: bg, alignItems: 'center', justifyContent: 'center' }}>
          <Ionicons name={icon} size={26} color={fg} />
        </View>
        <T v="footnote" style={{ fontFamily: font.semibold }}>{label}</T>
      </Pressable>
    </Rise>
  );
}

export default function Home() {
  const p = usePalette('paper');
  const { data, error, reload } = useLoad((api) => api.getDashboard(), 'dashboard');
  const bill = data?.needsYou.find((n) => n.href.startsWith('/invoice'));
  const latest = data ? [...data.property, ...data.family, ...data.projects] : [];

  return (
    <Screen ground="paper" tabs>
      <Rise>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[3] }}>
          <Mark />
          <T v="title" header style={{ flex: 1 }}>{data ? `Akwaaba, ${data.firstName}` : 'Akwaaba'}</T>
          <View>
            <IconButton icon="notifications-outline" label={data?.needsYou.length ? `Notifications, ${data.needsYou.length} new` : 'Notifications'} onPress={() => undefined} />
            {data?.needsYou.length ? <View style={{ position: 'absolute', top: 10, right: 11, width: 10, height: 10, borderRadius: 5, backgroundColor: brand.orange, borderWidth: 2, borderColor: p.surface }} /> : null}
          </View>
        </View>
      </Rise>

      {error ? <ErrorView message={error} onRetry={reload} /> : null}
      {!data && !error ? <Loading /> : null}
      {data ? (
        <>
          <AccountCards accounts={data.accounts} holder={data.fullName} total={data.held} />

          <View style={{ flexDirection: 'row', gap: space[2] }}>
            <Quick icon="location-outline" label="Check land" tone="lime" href="/property" delay={300} />
            <Quick icon="receipt-outline" label="Pay a bill" tone="ink" href={(bill?.href ?? '/family') as Href} delay={360} />
            <Quick icon="construct-outline" label="Build" tone="surface" href="/projects" delay={420} />
            <Quick icon="heart-outline" label="Care visit" tone="surface" href="/family" delay={480} />
          </View>

          {data.needsYou.length > 0 ? (
            <Rise delay={540} style={{ gap: space[3] }}>
              <NeedsYou title={data.needsYou[0].title} detail={data.needsYou[0].detail} count={data.needsYou.length} onPress={() => router.push(data.needsYou[0].href as Href)} />
              {data.needsYou.length > 1 ? (
                <Panel style={{ paddingVertical: space[1], gap: 0 }}>
                  {data.needsYou.slice(1).map((n, i, all) => (
                    <ListRow key={n.id} icon="hand-left-outline" iconTone="orange" title={n.title} detail={n.detail} onPress={() => router.push(n.href as Href)} last={i === all.length - 1} />
                  ))}
                </Panel>
              ) : null}
            </Rise>
          ) : (
            <Panel tone="lime" style={{ flexDirection: 'row', alignItems: 'center' }}>
              <Ionicons name="checkmark-circle" size={22} color={brand.ink} />
              <T v="headline" color={brand.ink}>Nothing needs you right now</T>
            </Panel>
          )}

          <Rise delay={620} style={{ gap: space[2] }}>
            <T v="headline" header style={{ fontSize: 18 }}>Your cases and family</T>
            <View>
              {latest.map((r, i) => (
                <ListRow
                  key={r.id}
                  icon={r.id.startsWith('p') ? 'business-outline' : r.id.startsWith('f') ? 'heart-outline' : 'document-text-outline'}
                  iconTone="surface"
                  title={r.title}
                  detail={r.detail}
                  onPress={r.href ? () => router.push(r.href as Href) : undefined}
                  trailing={r.badge?.verdict ? <VerdictChip verdict={r.badge.verdict} /> : undefined}
                  last={i === latest.length - 1}
                />
              ))}
            </View>
          </Rise>
          <Label style={{ textAlign: 'center' }}>Sample data for the demo build</Label>
        </>
      ) : null}
    </Screen>
  );
}
