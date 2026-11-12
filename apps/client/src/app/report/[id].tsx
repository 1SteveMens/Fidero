import { View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { formatDay, verdictWord } from '@tenmina/shared';
import { brand, font, radius, space } from '@tenmina/tokens';
import { Button, ErrorView, Label, Loading, Panel, Rise, Screen, T, VerdictChip } from '@tenmina/ui';
import { useLoad } from '../../data';

export default function ReportScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { data: r, error, reload } = useLoad((api) => api.getReport(id), `report-${id}`);

  if (error) return <Screen ground="ink" back><ErrorView message={error} onRetry={reload} /></Screen>;
  if (!r) return <Screen ground="ink" back><Loading /></Screen>;

  const tone = r.verdict === 'green' ? 'lime' : r.verdict === 'amber' ? 'amber' : 'red';
  const mark = r.verdict === 'green' ? 'checkmark' : r.verdict === 'amber' ? 'alert' : 'close';

  return (
    <Screen
      ground="ink"
      back
      title="Land report"
      trailing={<Label>{`V${r.version} · ${formatDay(r.releasedOn)}`}</Label>}
      footer={<Button title="Download the PDF" icon="download-outline" variant="dark" onPress={() => undefined} />}
    >
      <Rise delay={60}>
        <Panel tone={tone}>
          <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
            <T v="display" color={brand.ink} style={{ fontSize: 48, lineHeight: 50 }}>{verdictWord(r.verdict)}</T>
            <View style={{ width: 46, height: 46, borderRadius: 23, backgroundColor: brand.ink, alignItems: 'center', justifyContent: 'center' }}>
              <Ionicons name={mark} size={26} color={tone === 'lime' ? brand.lime : tone === 'amber' ? brand.amber : brand.red} />
            </View>
          </View>
          <T v="headline" color={brand.ink} style={{ fontSize: 18, lineHeight: 23 }}>{r.headline}</T>
        </Panel>
      </Rise>

      {r.mustHappen.length > 0 ? (
        <Rise delay={160}>
          <Panel style={{ gap: 0, paddingVertical: space[2] }}>
            <Label style={{ paddingVertical: space[2] }}>Must happen before you pay</Label>
            {r.mustHappen.map((m, i) => (
              <View key={i} style={{ flexDirection: 'row', gap: space[3], paddingVertical: space[3], borderTopWidth: 1, borderTopColor: '#2C2C2C' }}>
                <View style={{ width: 22, height: 22, borderRadius: 7, backgroundColor: brand.amber, alignItems: 'center', justifyContent: 'center' }}>
                  <T v="footnote" color={brand.ink} style={{ fontFamily: font.heavy }}>{i + 1}</T>
                </View>
                <T v="callout" style={{ flex: 1 }}>{m}</T>
              </View>
            ))}
          </Panel>
        </Rise>
      ) : null}

      <Rise delay={260} style={{ gap: space[2] }}>
        <T v="headline" header style={{ fontSize: 18 }}>What we checked</T>
        <View>
          {r.sections.map((s) => (
            <View key={s.number} style={{ flexDirection: 'row', alignItems: 'center', gap: space[3], minHeight: 46, borderBottomWidth: 1, borderBottomColor: '#2C2C2C' }}>
              <Label>{String(s.number).padStart(2, '0')}</Label>
              <T v="callout" style={{ flex: 1 }}>{s.title}</T>
              <VerdictChip verdict={s.verdict} />
            </View>
          ))}
        </View>
      </Rise>

      <Rise delay={360}>
        <View style={{ flexDirection: 'row', gap: space[3], borderRadius: radius.lg, borderWidth: 1, borderColor: '#2C2C2C', padding: space[4] }}>
          <Ionicons name="lock-closed" size={18} color={brand.lime} />
          <View style={{ flex: 1, gap: space[2] }}>
            <T v="footnote" muted>{r.signedBy}</T>
            <T v="mono">{`Sealed · ${r.fingerprint}`}</T>
            <T v="footnote" muted>If anyone changes the file, this fingerprint will not match.</T>
          </View>
        </View>
      </Rise>
      <Button title="Back to the case" variant="quiet" onPress={() => router.back()} />
    </Screen>
  );
}
