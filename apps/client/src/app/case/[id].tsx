import { Text, View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { radius, space, type } from '@fidero/tokens';
import { Button, Card, ErrorView, Loading, Pill, ProgressBar, Screen } from '../../components/ui';
import { useLoad } from '../../data';
import { usePalette } from '../../theme';

export default function CaseScreen() {
  const p = usePalette();
  const { id } = useLocalSearchParams<{ id: string }>();
  const { data: c, error, reload } = useLoad((api) => api.getCase(id), `case-${id}`);

  if (error) return <Screen topInset={false}><ErrorView message={error} onRetry={reload} /></Screen>;
  if (!c) return <Screen topInset={false}><Loading /></Screen>;

  const done = c.steps.filter((s) => s.state === 'done').length;

  return (
    <Screen topInset={false} subtitle={c.ref} title={c.title}>
      <View style={{ gap: space[2] }}>
        <ProgressBar value={done / c.steps.length} />
        <Text style={[type.footnote, { color: p.textMuted }]}>
          {done} of {c.steps.length} steps done
        </Text>
      </View>

      {c.next ? (
        <Card style={{ backgroundColor: p.primarySoft }}>
          <Text style={[type.caption, { color: p.primary, textTransform: 'uppercase', letterSpacing: 0.6 }]}>What happens next</Text>
          <Text style={[type.headline, { color: p.text, marginTop: space[1] }]}>{c.next.title}</Text>
          <Text style={[type.callout, { color: p.textMuted, marginTop: 2 }]}>{c.next.detail}</Text>
        </Card>
      ) : null}

      <View style={{ gap: space[3] }}>
        {c.reportId ? <Button title="Read the report" icon="document-text" onPress={() => router.push(`/report/${c.reportId}`)} /> : null}
        {c.escrowId ? <Button title="Open the escrow" icon="lock-closed" variant="secondary" onPress={() => router.push(`/escrow/${c.escrowId}`)} /> : null}
      </View>

      <Card>
        {c.steps.map((s, i) => {
          const last = i === c.steps.length - 1;
          const dot =
            s.state === 'done' ? (
              <View style={{ width: 24, height: 24, borderRadius: 12, backgroundColor: p.success, alignItems: 'center', justifyContent: 'center' }}>
                <Ionicons name="checkmark" size={16} color="#FFFFFF" />
              </View>
            ) : s.state === 'current' ? (
              <View style={{ width: 24, height: 24, borderRadius: 12, borderWidth: 3, borderColor: p.primary, backgroundColor: p.surface }} />
            ) : (
              <View style={{ width: 24, height: 24, borderRadius: 12, borderWidth: 2, borderColor: p.separator }} />
            );
          return (
            <View key={s.id} style={{ flexDirection: 'row', gap: space[3] }} accessible accessibilityLabel={`${s.title}. ${s.state === 'done' ? 'Done' : s.state === 'current' ? 'Now' : 'Later'}. ${s.detail ?? ''}`}>
              <View style={{ alignItems: 'center' }}>
                {dot}
                {!last ? <View style={{ width: 2, flex: 1, minHeight: 20, backgroundColor: s.state === 'done' ? p.success : p.separator, borderRadius: radius.sm }} /> : null}
              </View>
              <View style={{ flex: 1, paddingBottom: last ? 0 : space[4], gap: 2 }}>
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[2] }}>
                  <Text style={[type.headline, { color: s.state === 'upcoming' ? p.textMuted : p.text, flexShrink: 1 }]}>{s.title}</Text>
                  {s.state === 'current' ? <Pill label="Now" tone="primary" inline /> : null}
                </View>
                {s.detail ? <Text style={[type.callout, { color: p.textMuted }]}>{s.detail}</Text> : null}
              </View>
            </View>
          );
        })}
      </Card>
    </Screen>
  );
}
