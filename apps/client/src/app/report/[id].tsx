import { Linking, View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, font, radius, space } from '@tenmina/tokens';
import { Button, Label, Panel, Rise, Screen, T } from '@tenmina/ui';
import { LoadState, ProblemBox, apiBaseUrl, day, shortHash, useAction, useGet, words } from '@tenmina/mobile';

interface Report {
  id: string;
  reference: string;
  case: string;
  case_reference: string;
  version: number;
  status: string;
  overall_verdict: 'green' | 'amber' | 'red' | null;
  released_at: string | null;
  pdf_sha256: string;
  supersedes: string | null;
  correction_reason: string;
  conditions: { id: string; position: number; text: string; responsible: string; closing_evidence: string }[];
}

const WORD = { green: 'Green', amber: 'Amber', red: 'Red' } as const;
const HEAD = {
  green: 'Nothing found that should stop you.',
  amber: 'You can go ahead only after the conditions below are met.',
  red: 'Do not pay. We found something serious.',
} as const;

/** Report viewer (SCR-PTL-14, W-08): the verdict with icon and word, what must happen first, and the sealed PDF. */
export default function ReportScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const r = useGet<Report>(`/v1/reports/${id}`);
  const pdf = useAction();
  const d = r.data;
  const v = d?.overall_verdict ?? null;
  const tone = v === 'green' ? 'lime' : v === 'amber' ? 'amber' : 'red';
  const mark = v === 'green' ? 'checkmark' : v === 'amber' ? 'alert' : 'close';

  async function openPdf() {
    const out = await pdf.run<{ url: string }>('GET', `/v1/reports/${id}/pdf`);
    if (out) void Linking.openURL(out.url.startsWith('http') ? out.url : `${apiBaseUrl()}${out.url}`);
  }

  return (
    <Screen
      ground="ink"
      back
      title={d ? `Report ${d.reference}` : 'Report'}
      trailing={d ? <Label>{`V${d.version}`}</Label> : undefined}
      footer={d ? <Button title="Open the PDF" icon="document-outline" variant="dark" loading={pdf.busy} onPress={() => void openPdf()} /> : undefined}
    >
      <LoadState loading={r.loading} problem={r.problem} onRetry={r.reload} hasData={!!d} />
      {d && v ? (
        <>
          <Rise delay={60}>
            <Panel tone={tone}>
              <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
                <T v="display" color={brand.ink} style={{ fontSize: 46, lineHeight: 50 }}>{WORD[v]}</T>
                <View style={{ width: 46, height: 46, borderRadius: 23, backgroundColor: brand.ink, alignItems: 'center', justifyContent: 'center' }}>
                  <Ionicons name={mark} size={26} color={tone === 'lime' ? brand.lime : tone === 'amber' ? brand.amber : brand.red} />
                </View>
              </View>
              <T v="headline" color={brand.ink} style={{ fontSize: 18, lineHeight: 23 }}>{HEAD[v]}</T>
              <Label color={brand.ink}>{`Released ${day(d.released_at)} · case ${d.case_reference}`}</Label>
            </Panel>
          </Rise>
          {d.correction_reason ? (
            <Panel>
              <Label>Corrected version</Label>
              <T v="callout">{d.correction_reason}</T>
            </Panel>
          ) : null}
          {d.conditions.length ? (
            <Rise delay={140}>
              <Panel style={{ gap: 0, paddingVertical: space[2] }}>
                <Label style={{ paddingVertical: space[2] }}>Must happen before you pay</Label>
                {d.conditions.map((c, i) => (
                  <View key={c.id} style={{ flexDirection: 'row', gap: space[3], paddingVertical: space[3], borderTopWidth: 1, borderTopColor: '#2C2C2C' }}>
                    <View style={{ width: 22, height: 22, borderRadius: 7, backgroundColor: brand.paper, alignItems: 'center', justifyContent: 'center' }}>
                      <T v="footnote" color={brand.ink} style={{ fontFamily: font.heavy }}>{String(i + 1)}</T>
                    </View>
                    <View style={{ flex: 1 }}>
                      <T v="callout">{c.text}</T>
                      <T v="footnote" muted>{`${words(c.responsible)} · closed by: ${c.closing_evidence}`}</T>
                    </View>
                  </View>
                ))}
              </Panel>
            </Rise>
          ) : null}
          <Rise delay={220}>
            <View style={{ flexDirection: 'row', gap: space[3], borderRadius: radius.lg, borderWidth: 1, borderColor: '#2C2C2C', padding: space[4] }}>
              <Ionicons name="lock-closed" size={18} color={brand.lime} />
              <View style={{ flex: 1, gap: space[2] }}>
                <T v="mono">{`Sealed · ${shortHash(d.pdf_sha256)}`}</T>
                <T v="footnote" muted>If anyone changes the PDF, this fingerprint will not match. Anyone you share it with can check it on the Tenmina website.</T>
              </View>
            </View>
          </Rise>
          <ProblemBox problem={pdf.problem} />
          <Button title="Back to the case" variant="quiet" onPress={() => router.push(`/case/${d.case}`)} />
        </>
      ) : null}
    </Screen>
  );
}
