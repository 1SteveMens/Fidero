import { View } from 'react-native';
import { router, useLocalSearchParams, type Href } from 'expo-router';
import { space } from '@tenmina/tokens';
import { Button, ErrorView, IconButton, Label, Loading, NeedsYou, Panel, Rise, Screen, StepTrail, T } from '@tenmina/ui';
import { useLoad } from '../../data';
import { usePalette } from '@tenmina/ui';

export default function CaseScreen() {
  const p = usePalette('paper');
  const { id } = useLocalSearchParams<{ id: string }>();
  const { data, error, reload } = useLoad(async (api) => {
    const [c, dash] = await Promise.all([api.getCase(id), api.getDashboard()]);
    return { c, needsYou: dash.needsYou };
  }, `case-${id}`);

  if (error) return <Screen back><ErrorView message={error} onRetry={reload} /></Screen>;
  if (!data) return <Screen back><Loading /></Screen>;

  const { c } = data;
  const done = c.steps.filter((s) => s.state === 'done').length;
  const ask = data.needsYou.find((n) => n.href === `/escrow/${c.escrowId}`);

  return (
    <Screen
      ground="paper"
      back
      eyebrow={c.ref}
      trailing={c.reportId ? <IconButton icon="document-text-outline" label="Read the report" onPress={() => router.push(`/report/${c.reportId}`)} /> : undefined}
    >
      <Rise delay={60} style={{ flexDirection: 'row', alignItems: 'flex-end', gap: space[3] }}>
        <View style={{ flex: 1 }}>
          <T v="largeTitle" header>{c.title}</T>
          <T v="callout" muted>{c.line === 'land' ? 'Land check' : 'Building check'}</T>
        </View>
        <View style={{ alignItems: 'flex-end' }}>
          <T v="display" style={{ fontSize: 44, lineHeight: 46 }}>
            {done}
            <T v="display" color={p.lineStrong} style={{ fontSize: 44, lineHeight: 46 }}>/{c.steps.length}</T>
          </T>
          <Label>Steps done</Label>
        </View>
      </Rise>

      <StepTrail
        steps={c.steps}
        onStep={(s) => (c.reportId && /report/i.test(s.title) && s.state === 'done' ? () => router.push(`/report/${c.reportId}`) : undefined)}
      />

      {ask ? (
        <NeedsYou title={ask.title} detail={ask.detail} onPress={() => router.push(ask.href as Href)} />
      ) : c.next ? (
        <Panel>
          <Label>What happens next</Label>
          <T v="headline">{c.next.title}</T>
          <T v="callout" muted>{c.next.detail}</T>
        </Panel>
      ) : null}

      <View style={{ gap: space[2] }}>
        {c.reportId ? <Button title="Read the report" icon="document-text" variant="dark" onPress={() => router.push(`/report/${c.reportId}`)} /> : null}
        {c.escrowId && !ask ? <Button title="Open the escrow" icon="lock-closed" variant="quiet" onPress={() => router.push(`/escrow/${c.escrowId}`)} /> : null}
      </View>
    </Screen>
  );
}
