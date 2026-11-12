import { Pressable, View } from 'react-native';
import { router, type Href } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, radius, space } from '@tenmina/tokens';
import { ArrowBox, Chip, ErrorView, IconButton, Label, Loading, Panel, Rise, Screen, SegBar, T, VerdictChip, haptic, type IconName } from '@tenmina/ui';
import { useLoad } from '../../data';
import { usePalette } from '@tenmina/ui';

function Start({ icon, title, detail, tone, delay }: { icon: IconName; title: string; detail: string; tone: 'lime' | 'ink' | 'surface'; delay: number }) {
  const p = usePalette();
  const bg = tone === 'lime' ? brand.lime : tone === 'ink' ? brand.ink : p.surface;
  const fg = tone === 'ink' ? '#F7F6F2' : tone === 'lime' ? brand.ink : p.text;
  return (
    <Rise delay={delay} style={{ flex: 1 }}>
      <Pressable
        onPress={() => haptic('tap')}
        accessibilityRole="button"
        accessibilityLabel={`${title}. ${detail}`}
        style={({ pressed }) => ({ height: 124, borderRadius: radius.lg, backgroundColor: bg, padding: space[3], justifyContent: 'space-between', opacity: pressed ? 0.85 : 1 })}
      >
        <Ionicons name={icon} size={24} color={tone === 'ink' ? brand.lime : fg} />
        <View>
          <T v="headline" color={fg} style={{ fontSize: 15, lineHeight: 18 }}>{title}</T>
          <T v="footnote" color={tone === 'ink' ? '#A9A69E' : tone === 'lime' ? '#3F5A1F' : p.textMuted} style={{ fontSize: 12 }}>{detail}</T>
        </View>
      </Pressable>
    </Rise>
  );
}

export default function Property() {
  const { data, error, reload } = useLoad(async (api) => {
    const [cases, dash] = await Promise.all([api.listCases(), api.getDashboard()]);
    return { cases, needsYou: dash.needsYou };
  }, 'cases');
  const waiting = data ? data.cases.filter((c) => data.needsYou.some((n) => n.href === `/escrow/${c.escrowId}`)).length : 0;

  return (
    <Screen ground="paper" tabs title="Property" trailing={<IconButton icon="add" tone="lime" label="Check a plot or a house" onPress={() => undefined} />}>
      {error ? <ErrorView message={error} onRetry={reload} /> : null}
      {!data && !error ? <Loading /> : null}
      {data ? (
        <>
          <Label>{`${data.cases.length} cases${waiting ? ` · ${waiting} needs you` : ''}`}</Label>
          {data.cases.map((c, i) => {
            const done = c.steps.filter((s) => s.state === 'done').length;
            const current = c.steps.find((s) => s.state === 'current');
            const ask = data.needsYou.find((n) => n.href === `/escrow/${c.escrowId}`);
            const tone = ask ? 'raised' : 'surface';
            return (
              <Rise key={c.id} delay={80 + i * 120}>
                <Panel tone={tone} onPress={() => router.push(`/case/${c.id}`)} accessibilityLabel={`${c.title}. ${done} of ${c.steps.length} steps. ${current?.title ?? ''}`}>
                  <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
                    <Label>{c.ref}</Label>
                    {c.verdict ? <VerdictChip verdict={c.verdict} suffix="report" /> : <Chip label="In progress" tone="paper" />}
                  </View>
                  <View>
                    <PanelText tone={tone} v="title">{c.title}</PanelText>
                    <PanelText tone={tone} muted>{`${c.line === 'land' ? 'Land check' : 'Building check'} · ${done} of ${c.steps.length} steps`}</PanelText>
                  </View>
                  <SegBar done={done} total={c.steps.length} current={!!ask} onDark={tone === 'raised'} />
                  {ask ? (
                    <Pressable
                      onPress={() => {
                        haptic('tap');
                        router.push(ask.href as Href);
                      }}
                      accessibilityRole="button"
                      accessibilityLabel={`Needs you. ${ask.title}`}
                      style={({ pressed }) => ({ flexDirection: 'row', alignItems: 'center', gap: space[3], backgroundColor: brand.orange, borderRadius: radius.md + 2, paddingLeft: space[4], padding: space[2], opacity: pressed ? 0.85 : 1 })}
                    >
                      <T v="headline" color={brand.ink} style={{ flex: 1, fontSize: 15 }}>Needs you: approve the release</T>
                      <ArrowBox arrow={brand.orange} />
                    </Pressable>
                  ) : current ? (
                    <PanelText tone={tone}>{`Now: ${current.title}${current.detail ? `. ${current.detail}` : ''}`}</PanelText>
                  ) : null}
                </Panel>
              </Rise>
            );
          })}

          <T v="headline" header style={{ fontSize: 18, marginTop: space[2] }}>Start something new</T>
          <View style={{ flexDirection: 'row', gap: space[2] }}>
            <Start icon="location-outline" title="Check a plot" detail="Searches, survey, legal" tone="lime" delay={300} />
            <Start icon="home-outline" title="Check a house" detail="Structure, title, rates" tone="ink" delay={360} />
            <Start icon="list-outline" title="Verified listings" detail="Already checked" tone="surface" delay={420} />
          </View>
        </>
      ) : null}
    </Screen>
  );
}

/** Text that follows the panel it sits on. */
function PanelText({ tone, v = 'callout', muted, children }: { tone: 'raised' | 'surface'; v?: 'title' | 'callout'; muted?: boolean; children: string }) {
  const p = usePalette();
  const color = tone === 'raised' ? (muted ? '#A9A69E' : p.onRaised) : muted ? p.textMuted : p.text;
  return <T v={v} color={color}>{children}</T>;
}
