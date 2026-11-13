import { useState } from 'react';
import { View } from 'react-native';
import { useLocalSearchParams } from 'expo-router';
import { space } from '@tenmina/tokens';
import { Button, Chip, Label, Panel, Screen, T } from '@tenmina/ui';
import { Field, KV, LoadState, ProblemBox, Section, day, useAction, useGet, words } from '@tenmina/mobile';

interface Dispute {
  id: string;
  reference: string;
  status: string;
  category: string;
  subject_label: string;
  reason: string;
  response_due: string | null;
  evidence_due: string | null;
  decision_due: string | null;
  decision: string;
  decision_outcome: string;
  my_side: string;
  parties: { id: string; side: string; name: string; evidence_complete_at: string | null }[];
  statements: { id: string; kind: string; party_name: string; text: string; created_at: string }[];
}

/**
 * A dispute (SCR-PTL-29, W-23; FR-DSP-001 to FR-DSP-004): what it is about, the
 * dates, each side's statements, and the decision. The money stays frozen at
 * the bank until it is decided.
 */
export default function DisputeScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const dsp = useGet<Dispute>(`/v1/disputes/${id}`);
  const act = useAction();
  const [text, setText] = useState('');
  const d = dsp.data;
  const me = d?.parties.find((p) => p.side === d.my_side);
  const open = d && ['open', 'response', 'evidence'].includes(d.status);

  async function send() {
    const r = await act.run('POST', `/v1/disputes/${id}/statements`, { text: text.trim() });
    if (r) {
      setText('');
      dsp.reload();
    }
  }
  async function complete() {
    const r = await act.run('POST', `/v1/disputes/${id}/evidence-complete`);
    if (r) dsp.reload();
  }

  return (
    <Screen ground="paper" back eyebrow={d?.reference} title={d ? words(d.category) : 'Dispute'}>
      <LoadState loading={dsp.loading} problem={dsp.problem} onRetry={dsp.reload} hasData={!!d} />
      {d ? (
        <>
          <Chip label={words(d.status)} tone="paper" />
          <T v="callout">{d.reason}</T>
          <KV
            rows={[
              ['About', d.subject_label],
              ['Response due', day(d.response_due)],
              ['Evidence due', day(d.evidence_due)],
              ['Decision due', day(d.decision_due)],
            ]}
          />
          {d.decision ? (
            <Panel tone="raised">
              <T v="headline" color="#F7F6F2">{`Decision: ${words(d.decision_outcome)}`}</T>
              <T v="callout" color="#A9A69E">{d.decision}</T>
            </Panel>
          ) : null}
          <Section title="Statements">
            <Panel style={{ gap: space[3] }}>
              {d.statements.map((s) => (
                <View key={s.id} style={{ gap: 2 }}>
                  <Label>{`${s.party_name} · ${words(s.kind)} · ${day(s.created_at)}`}</Label>
                  <T v="callout">{s.text}</T>
                </View>
              ))}
              {!d.statements.length ? <T v="callout" muted>No statements yet.</T> : null}
            </Panel>
          </Section>
          {open && me ? (
            <>
              <Field label="Add to your statement" value={text} onChange={setText} multiline hint="Say what happened, with dates. Attach documents on the website." />
              <Button title="Send" variant="dark" disabled={text.trim().length < 10} loading={act.busy} onPress={() => void send()} />
              {!me.evidence_complete_at ? <Button title="My evidence is complete" variant="quiet" onPress={() => void complete()} /> : null}
            </>
          ) : null}
          <ProblemBox problem={act.problem} />
        </>
      ) : null}
    </Screen>
  );
}
