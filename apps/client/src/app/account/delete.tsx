import { View } from 'react-native';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, space } from '@fidero/tokens';
import { Button, ErrorView, Label, Loading, Panel, Rise, Screen, T } from '@fidero/ui';
import { useLoad } from '../../data';
import { usePalette } from '@fidero/ui';

/** In-app account deletion (FR-APP-004), saying plainly what is kept and why. */
export default function DeleteAccount() {
  const p = usePalette('paper');
  const { data, error, reload } = useLoad((api) => api.previewAccountDeletion(), 'deletion');

  return (
    <Screen
      ground="paper"
      back
      title="Delete account"
      footer={data ? <Button title="Delete my account" variant="danger" icon="trash-outline" disabled={data.blockedBy.length > 0} onPress={() => undefined} /> : undefined}
    >
      {error ? <ErrorView message={error} onRetry={reload} /> : null}
      {!data && !error ? <Loading /> : null}
      {data ? (
        <>
          {data.blockedBy.length > 0 ? (
            <Rise>
              <Panel tone="orange">
                <Label color={brand.ink}>Not yet</Label>
                {data.blockedBy.map((b) => (
                  <T key={b} v="callout" color={brand.ink}>{b}</T>
                ))}
              </Panel>
            </Rise>
          ) : null}
          <Rise delay={100}>
            <Panel>
              <Label>Deleted straight away</Label>
              {data.deletedNow.map((d) => (
                <View key={d} style={{ flexDirection: 'row', gap: space[3] }}>
                  <Ionicons name="trash-outline" size={18} color={p.text} />
                  <T v="callout" style={{ flex: 1 }}>{d}</T>
                </View>
              ))}
            </Panel>
          </Rise>
          <Rise delay={180}>
            <Panel>
              <Label>Kept, and why</Label>
              {data.keptAndWhy.map((k) => (
                <View key={k.item} style={{ gap: 2 }}>
                  <T v="headline" style={{ fontSize: 15 }}>{k.item}</T>
                  <T v="footnote" muted>{k.why}</T>
                </View>
              ))}
            </Panel>
          </Rise>
        </>
      ) : null}
    </Screen>
  );
}
