import { Text, View } from 'react-native';
import Ionicons from '@expo/vector-icons/Ionicons';
import { space, type } from '@fidero/tokens';
import { Button, Card, ErrorView, Loading, Muted, Screen } from '../../components/ui';
import { useLoad } from '../../data';
import { usePalette } from '../../theme';

/** In-app account deletion (FR-APP-004), saying plainly what is kept and why. */
export default function DeleteAccount() {
  const p = usePalette();
  const { data, error, reload } = useLoad((api) => api.previewAccountDeletion(), 'deletion');

  return (
    <Screen topInset={false}>
      {error ? <ErrorView message={error} onRetry={reload} /> : null}
      {!data && !error ? <Loading /> : null}
      {data ? (
        <>
          <Card style={{ gap: space[2] }}>
            <Text style={[type.headline, { color: p.text }]}>Deleted straight away</Text>
            {data.deletedNow.map((d) => (
              <View key={d} style={{ flexDirection: 'row', gap: space[2] }}>
                <Ionicons name="trash-outline" size={18} color={p.textMuted} />
                <Text style={[type.callout, { color: p.text, flex: 1 }]}>{d}</Text>
              </View>
            ))}
          </Card>
          <Card style={{ gap: space[3] }}>
            <Text style={[type.headline, { color: p.text }]}>Kept, and why</Text>
            {data.keptAndWhy.map((k) => (
              <View key={k.item} style={{ gap: 2 }}>
                <Text style={[type.callout, { color: p.text, fontWeight: '600' }]}>{k.item}</Text>
                <Muted>{k.why}</Muted>
              </View>
            ))}
          </Card>
          {data.blockedBy.length > 0 ? (
            <Card style={{ backgroundColor: p.warningSoft, gap: space[2] }}>
              <Text style={[type.headline, { color: p.text }]}>Not yet</Text>
              {data.blockedBy.map((b) => (
                <Text key={b} style={[type.callout, { color: p.text }]}>{b}</Text>
              ))}
            </Card>
          ) : null}
          <Button title="Delete my account" variant="danger" icon="trash" disabled={data.blockedBy.length > 0} onPress={() => undefined} />
        </>
      ) : null}
    </Screen>
  );
}
