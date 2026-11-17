import { useState } from 'react';
import { View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import type { CaseStep } from '@tenmina/shared';
import { brand, space } from '@tenmina/tokens';
import { Button, Chip, Label, Panel, Rise, Screen, StepTrail, T, VerdictChip, usePalette } from '@tenmina/ui';
import { LoadState, Section, day, useApi, useGet, useSession, words } from '@tenmina/mobile';
import { AddFile, EvidenceFiles, FileRow } from '../../components/files';

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
  document_requests: { id: string; title?: string; description?: string; status: string; due_on?: string; received_evidence?: string | null; received_at?: string | null }[];
}

const LINES: Record<string, string> = { land: 'Land check', building: 'Building check', offplan: 'Off-plan check', institution: 'Institution check' };

/** Case tracker (SCR-PTL-12, W-07): every step, the latest message with its next date, reports and requests. */
export default function CaseScreen() {
  const pal = usePalette('paper');
  const { id } = useLocalSearchParams<{ id: string }>();
  const api = useApi();
  const { me } = useSession();
  const c = useGet<CaseDetail>(`/v1/cases/${id}`);
  const [filesTick, setFilesTick] = useState(0);
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
                  <T v="display" color={pal.textMuted} style={{ fontSize: 40, lineHeight: 42 }}>{`/${steps.length}`}</T>
                </T>
                <Label>Steps done</Label>
              </View>
            ) : null}
          </Rise>

          {d.latest_status ? (
            <Panel tone="raised">
              <Label>{`Latest · ${day(d.latest_status.message_date)}`}</Label>
              <T v="headline">{d.latest_status.text}</T>
              {d.latest_status.next_expected_date ? <T v="footnote" muted>{`Next update by ${day(d.latest_status.next_expected_date)}`}</T> : null}
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
              {d.document_requests.map((r) =>
                r.status === 'open' ? (
                  <Panel key={r.id} tone="orange">
                    <Label color={brand.ink}>Needs you</Label>
                    <T v="headline" color={brand.ink}>{r.title || r.description || 'Document'}</T>
                    {r.description && r.title ? <T v="callout" color={brand.ink}>{r.description}</T> : null}
                    {r.due_on ? <T v="footnote" color="#3A1408">{`Send it by ${day(r.due_on)}`}</T> : null}
                    <AddFile
                      label="Send it from"
                      subject={{ type: 'case', id: d.id, role: 'client_document', description: r.title || 'Requested document' }}
                      then={(ev) => api.post(`/v1/document-requests/${r.id}/responses`, { evidence_id: ev.id }, { idempotencyKey: `docreq-${r.id}-${ev.id}` })}
                      onDone={() => {
                        c.reload();
                        setFilesTick((t) => t + 1);
                      }}
                    />
                  </Panel>
                ) : (
                  <Panel key={r.id}>
                    <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[2] }}>
                      <T v="headline" style={{ flex: 1 }}>{r.title || r.description || 'Document'}</T>
                      <Chip label={r.status === 'received' ? 'Received' : words(r.status)} tone={r.status === 'received' ? 'lime' : 'paper'} icon={r.status === 'received' ? 'checkmark' : undefined} />
                    </View>
                    {r.received_evidence ? <FileRow id={r.received_evidence} name="The file you sent" type="" detail={r.received_at ? `Sent ${day(r.received_at)}` : undefined} last /> : null}
                  </Panel>
                ),
              )}
            </Section>
          ) : null}

          <Section title="Files on this case">
            <EvidenceFiles subjectType="case" subjectId={d.id} tick={filesTick} empty="No files on this case yet." />
            {me && d.status !== 'cancelled' ? (
              <AddFile label="Send a document from" subject={{ type: 'case', id: d.id, role: 'client_document', description: 'Sent by the client' }} onDone={() => setFilesTick((t) => t + 1)} />
            ) : null}
          </Section>

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
