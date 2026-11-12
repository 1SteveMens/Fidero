import { Text, View } from 'react-native';
import { space, type } from '@fidero/tokens';
import { Button, Card, ErrorView, IconBadge, Loading, ProgressBar, Screen } from '../../components/ui';
import { useLoad } from '../../data';
import { usePalette } from '../../theme';

export default function Projects() {
  const p = usePalette();
  const { data, error, reload } = useLoad((api) => api.listErrands(), 'errands');

  return (
    <Screen title="Projects">
      {error ? <ErrorView message={error} onRetry={reload} /> : null}
      {!data && !error ? <Loading /> : null}
      {data?.map((e) => (
        <Card key={e.id}>
          <View style={{ flexDirection: 'row', gap: space[3], alignItems: 'center' }}>
            <IconBadge name="id-card" />
            <View style={{ flex: 1 }}>
              <Text style={[type.headline, { color: p.text }]}>{e.title}</Text>
              <Text style={[type.footnote, { color: p.textMuted }]}>{e.agency}</Text>
            </View>
          </View>
          <View style={{ marginTop: space[4], gap: space[2] }}>
            <ProgressBar value={e.step / e.steps} />
            <Text style={[type.callout, { color: p.text }]}>
              Step {e.step} of {e.steps}. {e.status}
            </Text>
          </View>
        </Card>
      ))}
      <Button title="Start an errand or project" icon="add-circle" variant="secondary" onPress={() => undefined} />
    </Screen>
  );
}
