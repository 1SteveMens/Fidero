import { Pressable, View } from 'react-native';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, radius, space } from '@fidero/tokens';
import { Chip, DotStepper, ErrorView, IconButton, IconTile, Loading, Panel, Pulse, Rise, Screen, T, haptic, type IconName } from '../../components/ui';
import { useLoad } from '../../data';
import { usePalette } from '../../theme';

function Start({ icon, title, detail, tone, delay }: { icon: IconName; title: string; detail: string; tone: 'lime' | 'ink' | 'surface'; delay: number }) {
  const p = usePalette();
  const bg = tone === 'lime' ? brand.lime : tone === 'ink' ? brand.ink : p.surface;
  const fg = tone === 'ink' ? '#F7F6F2' : tone === 'lime' ? brand.ink : p.text;
  const sub = tone === 'ink' ? '#A9A69E' : tone === 'lime' ? '#3F5A1F' : p.textMuted;
  return (
    <Rise delay={delay} style={{ flex: 1 }}>
      <Pressable
        onPress={() => haptic('tap')}
        accessibilityRole="button"
        accessibilityLabel={`${title}. ${detail}`}
        style={({ pressed }) => ({ height: 140, borderRadius: radius.lg, backgroundColor: bg, padding: space[4], justifyContent: 'space-between', opacity: pressed ? 0.85 : 1 })}
      >
        <Ionicons name={icon} size={26} color={tone === 'ink' ? brand.lime : fg} />
        <View>
          <T v="headline" color={fg} style={{ lineHeight: 20 }}>{title}</T>
          <T v="footnote" color={sub}>{detail}</T>
        </View>
      </Pressable>
    </Rise>
  );
}

export default function Projects() {
  const { data, error, reload } = useLoad((api) => api.listErrands(), 'errands');

  return (
    <Screen ground="paper" tabs title="Projects" trailing={<IconButton icon="add" tone="lime" label="Start an errand or project" onPress={() => undefined} />}>
      {error ? <ErrorView message={error} onRetry={reload} /> : null}
      {!data && !error ? <Loading /> : null}
      {data?.map((e, i) => (
        <Rise key={e.id} delay={60 + i * 100}>
          <Panel style={{ gap: space[4] }} accessibilityLabel={`${e.title}. Step ${e.step} of ${e.steps}. ${e.status}`}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[3] }}>
              <IconTile name="document-text-outline" tone="ink" size={44} />
              <View style={{ flex: 1 }}>
                <T v="title" style={{ fontSize: 19, lineHeight: 23 }}>{e.title}</T>
                <T v="footnote" muted>{`Errand · ${e.agency}`}</T>
              </View>
              <Chip label={`${e.step} of ${e.steps}`} tone="paper" />
            </View>
            <DotStepper labels={e.stepLabels} done={e.step - 1} />
            <View style={{ flexDirection: 'row', gap: space[3], alignItems: 'center' }}>
              <Pulse size={10} radius={5} />
              <T v="callout" style={{ flex: 1 }}>{e.status}</T>
            </View>
          </Panel>
        </Rise>
      ))}
      <T v="headline" header style={{ fontSize: 18, marginTop: space[2] }}>Start something new</T>
      <View style={{ flexDirection: 'row', gap: space[2] }}>
        <Start icon="construct-outline" title="Build with milestones" detail="Pay the builder only after each inspection" tone="lime" delay={200} />
        <Start icon="document-text-outline" title="Paperwork and errands" detail="Cards, titles, permits" tone="ink" delay={260} />
      </View>
      <View style={{ flexDirection: 'row', gap: space[2] }}>
        <Start icon="cash-outline" title="Project funds" detail="Released against real invoices" tone="surface" delay={320} />
        <Start icon="calendar-outline" title="Events" detail="Funerals, weddings, outdoorings" tone="surface" delay={380} />
      </View>
    </Screen>
  );
}
