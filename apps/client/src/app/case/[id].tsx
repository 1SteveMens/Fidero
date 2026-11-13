import { View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import type { CaseStep } from '@tenmina/shared';
import { space } from '@tenmina/tokens';
import { Button, Chip, Label, Panel, Rise, Screen, StepTrail, T, VerdictChip, usePalette } from '@tenmina/ui';
import { LoadState, Section, day, useGet, words } from '@tenmina/mobile';

interface CaseDetail {
  id: string;
  reference: string;
  country: string;
  title: string;
  product_line: string;
  status: string;
  hold_reason: string;
  outcome: string;
  latest_status: { text: string; message_date: string; next_expected_date: string | null } | null;
  status_messages: { id: string; text: string; message_date: string; next_expected_date: string | null }[];
  steps: { step_key: string; title: string; status: string; due_at: string | null; completed_at: string | null }[];
  reports: { id: string; reference: string; version: number; status: string; released_at: string | null }[];
  document_requests: { id: string; title?: string; description?: string; status: string; due_on?: string }[];
}

const LINES: Record<string, string> = { land: 'Land check', building: 'Building check', offplan: 'Off-plan check', institution: 'Institution check' };

/** Case tracker (SCR-PTL-12, W-07): every step, the latest message with its next date, reports and requests. */
export default function CaseScreen() {
  const pal = usePalette('paper');
  const { id } = useLocalSearchParams<{ id: string }>();
  const c = useGet<CaseDetail>(`/v1/cases/${id}`);
  const d = c.data;
  const firstOpen = d?.steps.findIndex((s) => s.status !== 'done' && s.status !== 'skipped') ?? -1;
  const steps: CaseStep[] = (d?.steps ?? []).map((s, i) => ({
    id: s.step_key,
    title: s.title,
    detail: s.completed_at ? `Done ${day(s.completed_at)}` : s.due_at ? `Expected by ${day(s.due_at)}` : undefined,
    state: s.status === 'done' || s.status === 'skipped' ? 'done' : i === firstOpen ? 'current' : 'upcoming',
  }));
  const done = steps.filter((s) => s.state === 'done').length;
  const report = d?.reports.find((r) => r.status === 'released');

  return (
    <Screen ground="paper" back eyebrow={d ? `${d.reference} · ${d.country}` : 'Case'}>
      <LoadState loading={c.loading} problem={c.problem} onRetry={c.reload} hasData={!!d} />
      {d ? (
        <>
          <Rise delay={40} style={{ flexDirection: 'row', alignItems: 'flex-end', gap: space[3] }}>
            <View style={{ flex: 1 }}>
              <T v="title" header>{d.title}</T>
              <T v="callout" muted>{LINES[d.product_line] ?? words(d.product_line)}</T>
            </View>
            {steps.length ? (
              <View style={{ alignItems: 'flex-end' }}>
                <T v="display" style={{ fontSize: 40, lineHeight: 42 }}>
                  {done}
                  <T v="display" color={pal.lineStrong} style={{ fontSize: 40, lineHeight: 42 }}>{`/${steps.length}`}</T>
                </T>
                <Label>Steps done</Label>
              </View>
            ) : null}
          </Rise>

          {d.latest_status ? (
            <Panel tone="raised">
              <Label color="#A9A69E">{`Latest · ${day(d.latest_status.message_date)}`}</Label>
              <T v="headline" color="#F7F6F2">{d.latest_status.text}</T>
              {d.latest_status.next_expected_date ? <T v="footnote" color="#A9A69E">{`Next update by ${day(d.latest_status.next_expected_date)}`}</T> : null}
            </Panel>
          ) : null}
          {d.status === 'on_hold' && d.hold_reason ? (
            <Panel>
              <Chip label="On hold" tone="paper" />
              <T v="callout">{d.hold_reason}</T>
            </Panel>
          ) : null}

          {report ? <Button title="Read the report" icon="document-text" variant="dark" onPress={() => router.push(`/report/${report.id}`)} /> : null}

          {steps.length ? <StepTrail steps={steps} /> : null}

          {d.document_requests.length ? (
            <Section title="Documents we asked for">
              {d.document_requests.map((r) => (
                <Panel key={r.id}>
                  <T v="headline">{r.title ?? r.description ?? 'Document'}</T>
                  <Label>{`${words(r.status)}${r.due_on ? ` · by ${day(r.due_on)}` : ''}`}</Label>
                  <T v="footnote" muted>Send documents on the Tenmina website, where you can attach files.</T>
                </Panel>
              ))}
            </Section>
          ) : null}

          {d.reports.length > 1 ? (
            <Section title="Report versions">
              {d.reports.map((r) => (
                <Panel key={r.id} onPress={() => router.push(`/report/${r.id}`)} style={{ flexDirection: 'row', alignItems: 'center' }}>
                  <T v="headline" style={{ flex: 1 }}>{`${r.reference} · version ${r.version}`}</T>
                  <Chip label={words(r.status)} />
                </Panel>
              ))}
            </Section>
          ) : null}

          {d.status_messages.length > 1 ? (
            <Section title="Messages">
              <Panel style={{ gap: space[3] }}>
                {[...d.status_messages].reverse().map((m) => (
                  <View key={m.id} style={{ gap: 2 }}>
                    <Label>{day(m.message_date)}</Label>
                    <T v="callout">{m.text}</T>
                  </View>
                ))}
              </Panel>
            </Section>
          ) : null}
          {d.outcome ? <VerdictChipMaybe outcome={d.outcome} /> : null}
        </>
      ) : null}
    </Screen>
  );
}

function VerdictChipMaybe({ outcome }: { outcome: string }) {
  if (outcome === 'green' || outcome === 'amber' || outcome === 'red') return <VerdictChip verdict={outcome} suffix="outcome" />;
  return <Label>{`Outcome: ${words(outcome)}`}</Label>;
}
