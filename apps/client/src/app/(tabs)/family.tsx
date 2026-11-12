import { Pressable, Text, View } from 'react-native';
import { router } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { radius, space, type } from '@fidero/tokens';
import { Card, ErrorView, Loading, Screen } from '../../components/ui';
import { useLoad } from '../../data';
import { usePalette } from '../../theme';

export default function Family() {
  const p = usePalette();
  const { data, error, reload } = useLoad((api) => api.listFamily(), 'family');

  return (
    <Screen title="Family">
      <Text style={[type.callout, { color: p.textMuted }]}>
        Pay schools and hospitals directly and see every receipt. Money never goes to a relative in cash.
      </Text>
      {error ? <ErrorView message={error} onRetry={reload} /> : null}
      {!data && !error ? <Loading /> : null}
      {data?.map((m) => (
        <Card key={m.id}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[3], marginBottom: space[3] }}>
            <View style={{ width: 44, height: 44, borderRadius: 22, backgroundColor: p.primarySoft, alignItems: 'center', justifyContent: 'center' }}>
              <Text style={[type.headline, { color: p.primary }]}>{m.name.split(' ').map((w) => w[0]).join('')}</Text>
            </View>
            <View style={{ flex: 1 }}>
              <Text style={[type.headline, { color: p.text }]}>{m.name}</Text>
              <Text style={[type.footnote, { color: p.textMuted }]}>
                {m.relationship} · {m.place}
              </Text>
            </View>
          </View>
          <View style={{ gap: space[2] }}>
            {m.rows.map((r) => (
              <Pressable
                key={r.id}
                disabled={!r.href}
                onPress={r.href ? () => router.push(r.href as never) : undefined}
                accessibilityRole={r.href ? 'button' : 'text'}
                accessibilityLabel={`${r.title}. ${r.detail}`}
                style={({ pressed }) => ({ flexDirection: 'row', alignItems: 'center', gap: space[3], backgroundColor: p.surfaceAlt, borderRadius: radius.md, padding: space[3], minHeight: 52, opacity: pressed ? 0.8 : 1 })}
              >
                <View style={{ flex: 1 }}>
                  <Text style={[type.callout, { color: p.text, fontWeight: '600' }]}>{r.title}</Text>
                  <Text style={[type.footnote, { color: p.textMuted }]}>{r.detail}</Text>
                </View>
                {r.href ? <Ionicons name="chevron-forward" size={18} color={p.textMuted} /> : null}
              </Pressable>
            ))}
          </View>
        </Card>
      ))}
    </Screen>
  );
}
