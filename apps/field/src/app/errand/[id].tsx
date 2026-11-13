import { useState } from 'react';
import { View } from 'react-native';
import { useLocalSearchParams } from 'expo-router';
import { brand, space } from '@tenmina/tokens';
import { Button, Choice, Chip, Input, Label, Panel, Screen, T, Tick } from '@tenmina/ui';
import { Empty, day, money, words } from '@tenmina/mobile';
import { useField } from '../../store';
import { CaptureButton, OfflineBanner } from '../../screens/common';

/**
 * Errand steps and receipts (SCR-MOB-17; FR-TSK-003 to FR-TSK-005, FR-MOB-010):
 * start each step, photograph the agency's acknowledgement or receipt in the
 * app, mark it done, then the resulting document and the handover. Official
 * fees are paid by the bank straight to the agency: the agent never carries money.
 */
export default function ErrandScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { errands, queue, ops, capturesFor } = useField();
  const e = errands.find((x) => x.id === id);
  const [receiver, setReceiver] = useState('');
  const [method, setMethod] = useState<'client' | 'family_member' | 'representative'>('family_member');
  if (!e) {
    return (
      <Screen back>
        <Empty title="This errand is not on the phone" detail="Sync again from My jobs." />
      </Screen>
    );
  }
  const queued = (kind: string, seq?: number) => ops.some((o) => o.subjectId === (seq !== undefined ? e.steps.find((s) => s.seq === seq)?.id : e.id) && o.kind === kind && o.state !== 'failed');
  const allDone = e.steps.every((s) => s.status === 'done' || queued('errand_done', s.seq));
  const results = capturesFor('errand', e.id, 'result');
  const handoverPhotos = capturesFor('errand', e.id, 'handover');

  return (
    <Screen ground="paper" back title={e.name} eyebrow={`${e.reference}${e.due_on ? ` · due ${day(e.due_on)}` : ''}`}>
      <OfflineBanner />
      <Panel tone="raised" style={{ paddingVertical: space[3] }}>
        <T v="callout" color="#F7F6F2">Official fees are paid by the bank straight to the agency. Never carry or hand over money.</T>
      </Panel>
      {e.steps.map((s) => {
        const receipts = capturesFor('errand_step', s.id, 'receipt');
        const started = !!s.started_at || queued('errand_start', s.seq);
        const proof = s.has_receipt || s.has_acknowledgement || queued('errand_receipt', s.seq);
        const done = s.status === 'done' || queued('errand_done', s.seq);
        const base = { subjectType: 'errand_step', subjectId: s.id };
        return (
          <Panel key={s.id} style={{ gap: space[2] }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[3] }}>
              {done ? <Tick /> : <View style={{ width: 22, height: 22, borderRadius: 7, borderWidth: 2, borderColor: '#D6D3CB' }} />}
              <View style={{ flex: 1 }}>
                <T v="headline" style={{ fontSize: 15 }}>{`${s.seq}. ${s.description}`}</T>
                <Label>{`${s.plain}${Number(s.official_fee.amount) > 0 ? ` · fee ${money(s.official_fee)}, paid by the bank` : ''}`}</Label>
              </View>
              {!done ? <Chip label={words(s.status)} tone="paper" /> : null}
            </View>
            {!done ? (
              <>
                {!started ? (
                  <Button title="Start this step" variant="dark" onPress={() => queue({ kind: 'errand_start', label: `Step ${s.seq} started: ${e.name}`, ...base, path: `/v1/mobile/errands/${e.id}/steps/${s.seq}/start` })} />
                ) : !proof ? (
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[3] }}>
                    <T v="callout" style={{ flex: 1 }}>Photograph the receipt or acknowledgement</T>
                    <CaptureButton subjectType="errand_step" subjectId={s.id} reqKey="receipt" label={`Receipt, step ${s.seq}`} count={receipts.length} />
                  </View>
                ) : null}
                {started && !proof && receipts.length ? (
                  <Button
                    title="Send the receipt"
                    onPress={() =>
                      queue({ kind: 'errand_receipt', label: `Receipt, step ${s.seq}: ${e.name}`, ...base, path: `/v1/mobile/errands/${e.id}/steps/${s.seq}/receipts`, body: { kind: Number(s.official_fee.amount) > 0 ? 'receipt' : 'acknowledgement', evidence_id: null }, needs: [{ captureId: receipts[receipts.length - 1].id, at: 'evidence_id' }] })
                    }
                  />
                ) : null}
                {proof ? <Button title="Mark this step done" onPress={() => queue({ kind: 'errand_done', label: `Step ${s.seq} done: ${e.name}`, ...base, path: `/v1/mobile/errands/${e.id}/steps/${s.seq}/done` })} /> : null}
              </>
            ) : null}
          </Panel>
        );
      })}

      {allDone && !e.result_uploaded_at && !queued('errand_result') ? (
        <Panel style={{ gap: space[2] }}>
          <Label>The resulting document</Label>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[3] }}>
            <T v="callout" style={{ flex: 1 }}>Photograph it in the app. Tenmina checks it before the handover.</T>
            <CaptureButton subjectType="errand" subjectId={e.id} reqKey="result" label="Resulting document" count={results.length} />
          </View>
          <Button
            title="Send the document"
            disabled={!results.length}
            onPress={() => queue({ kind: 'errand_result', label: `Result: ${e.name}`, subjectType: 'errand', subjectId: e.id, path: `/v1/mobile/errands/${e.id}/results`, body: { evidence_id: null }, needs: [{ captureId: results[results.length - 1].id, at: 'evidence_id' }] })}
          />
        </Panel>
      ) : null}

      {(e.result_uploaded_at || queued('errand_result')) && !e.handover && !queued('errand_handover') ? (
        <Panel style={{ gap: space[2] }}>
          <Label>Hand over</Label>
          <Choice selected={method === 'family_member'} onPress={() => setMethod('family_member')} title="To the family member" />
          <Choice selected={method === 'client'} onPress={() => setMethod('client')} title="To the client" />
          <Choice selected={method === 'representative'} onPress={() => setMethod('representative')} title="To the client's representative" />
          <Input label="Name of the person who received it" value={receiver} onChange={setReceiver} />
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[3] }}>
            <T v="callout" style={{ flex: 1 }}>Photo of the handover</T>
            <CaptureButton subjectType="errand" subjectId={e.id} reqKey="handover" label="Handover photo" count={handoverPhotos.length} />
          </View>
          <Button
            title="Record the handover"
            disabled={!handoverPhotos.length || receiver.trim().length < 2}
            onPress={() => queue({ kind: 'errand_handover', label: `Handover: ${e.name}`, subjectType: 'errand', subjectId: e.id, path: `/v1/mobile/errands/${e.id}/handovers`, body: { method, proof_kind: 'photo', evidence_id: null, receiver_name: receiver.trim() }, needs: [{ captureId: handoverPhotos[handoverPhotos.length - 1].id, at: 'evidence_id' }] })}
          />
        </Panel>
      ) : null}
      {e.handover || queued('errand_handover') ? (
        <Panel style={{ flexDirection: 'row', alignItems: 'center' }}>
          <Tick />
          <T v="callout" color={brand.ink} style={{ flex: 1 }}>Handed over. The client confirms it in their app.</T>
        </Panel>
      ) : null}
    </Screen>
  );
}
