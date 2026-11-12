import { Text, View } from 'react-native';
import { router } from 'expo-router';
import { space, type } from '@fidero/tokens';
import { Button, Card, ErrorView, IconBadge, Loading, Pill, ProgressBar, Screen } from '../../components/ui';
import { useLoad } from '../../data';
import { usePalette } from '../../theme';

export default function Property() {
  const p = usePalette();
  const { data, error, reload } = useLoad((api) => api.listCases(), 'cases');

  return (
    <Screen title="Property">
      {error ? <ErrorView message={error} onRetry={reload} /> : null}
      {!data && !error ? <Loading /> : null}
      {data?.map((c) => {
        const done = c.steps.filter((s) => s.state === 'done').length;
        const current = c.steps.find((s) => s.state === 'current');
        return (
          <Card key={c.id} onPress={() => router.push(`/case/${c.id}`)} accessibilityLabel={`${c.title}. ${current?.title ?? ''}`}>
            <View style={{ flexDirection: 'row', gap: space[3], alignItems: 'center' }}>
              <IconBadge name={c.line === 'land' ? 'map' : 'business'} />
              <View style={{ flex: 1 }}>
                <Text style={[type.headline, { color: p.text }]}>{c.title}</Text>
                <Text style={[type.footnote, { color: p.textMuted }]}>{c.line === 'land' ? 'Land check' : 'Building check'} · {c.ref}</Text>
              </View>
            </View>
            <View style={{ marginTop: space[4], gap: space[2] }}>
              <ProgressBar value={done / c.steps.length} />
              <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
                <Text style={[type.callout, { color: p.text, flex: 1 }]}>{current?.title ?? 'Complete'}</Text>
                <Pill label={`${done} of ${c.steps.length}`} tone="neutral" />
              </View>
            </View>
          </Card>
        );
      })}
      <Button title="Check a plot or a house" icon="add-circle" variant="secondary" onPress={() => undefined} />
    </Screen>
  );
}
