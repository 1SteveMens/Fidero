import { Text, View } from 'react-native';
import { useLocalSearchParams } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { formatDay } from '@fidero/shared';
import { radius, space, type } from '@fidero/tokens';
import { Button, Card, ErrorView, Loading, Muted, Screen, VerdictPill } from '../../components/ui';
import { useLoad } from '../../data';
import { usePalette } from '../../theme';

export default function ReportScreen() {
  const p = usePalette();
  const { id } = useLocalSearchParams<{ id: string }>();
  const { data: r, error, reload } = useLoad((api) => api.getReport(id), `report-${id}`);

  if (error) return <Screen topInset={false}><ErrorView message={error} onRetry={reload} /></Screen>;
  if (!r) return <Screen topInset={false}><Loading /></Screen>;

  const tone = { green: { bg: p.successSoft, fg: p.success, icon: 'checkmark-circle' as const }, amber: { bg: p.warningSoft, fg: p.warning, icon: 'alert-circle' as const }, red: { bg: p.dangerSoft, fg: p.danger, icon: 'close-circle' as const } }[r.verdict];

  return (
    <Screen topInset={false}>
      <View style={{ backgroundColor: tone.bg, borderRadius: radius.xl, padding: space[5], gap: space[3] }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[2] }}>
          <Ionicons name={tone.icon} size={34} color={tone.fg} />
          <Text style={[type.largeTitle, { color: tone.fg }]}>{r.verdict === 'green' ? 'Green' : r.verdict === 'amber' ? 'Amber' : 'Red'}</Text>
        </View>
        <Text style={[type.title, { color: p.text, fontSize: 20 }]}>{r.headline}</Text>
        <View style={{ gap: space[2] }}>
          {r.mustHappen.map((m, i) => (
            <View key={i} style={{ flexDirection: 'row', gap: space[2] }}>
              <Text style={[type.headline, { color: tone.fg, width: 20 }]}>{i + 1}</Text>
              <Text style={[type.body, { color: p.text, flex: 1 }]}>{m}</Text>
            </View>
          ))}
        </View>
        <Muted>Released {formatDay(r.releasedOn)} · version {r.version}</Muted>
      </View>

      <Card style={{ paddingVertical: space[2] }}>
        {r.sections.map((s, i) => (
          <View
            key={s.number}
            style={{ flexDirection: 'row', alignItems: 'center', gap: space[3], minHeight: 48, borderTopWidth: i === 0 ? 0 : 1, borderTopColor: p.separator }}
          >
            <Text style={[type.callout, { color: p.text, flex: 1 }]}>{s.title}</Text>
            <VerdictPill verdict={s.verdict} />
          </View>
        ))}
      </Card>

      <Muted>{r.signedBy}</Muted>

      <Card style={{ backgroundColor: p.surfaceAlt, shadowOpacity: 0, elevation: 0, gap: space[1] }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[2] }}>
          <Ionicons name="finger-print" size={20} color={p.primary} />
          <Text style={[type.headline, { color: p.text }]}>Fingerprint of this PDF</Text>
        </View>
        <Text style={[type.callout, { color: p.text, fontFamily: 'monospace' }]}>{r.fingerprint}</Text>
        <Muted>If anyone changes the file, the fingerprint will not match.</Muted>
      </Card>

      <Button title="Download the PDF" icon="download" variant="secondary" onPress={() => undefined} />
    </Screen>
  );
}
