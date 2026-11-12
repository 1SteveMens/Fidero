import { useState } from 'react';
import { View } from 'react-native';
import Ionicons from '@expo/vector-icons/Ionicons';
import { defectHoldback, formatMoney, inspectionBlockers, type Answer, type Defect, type FieldJob, type InspectionResult } from '@fidero/shared';
import { brand, space } from '@fidero/tokens';
import { Button, Choice, ErrorView, Input, Label, Loading, Panel, Rise, Screen, T, YesNo } from '@fidero/ui';
import { newId, useField, useFieldLoad } from '../store';
import { CaptureButton, OfflineBanner, Submitted } from './common';

/** Inspection checklist and result (W-18, SCR-MOB-09 to 11; FR-MOB-007, RUL-09, RUL-10). */
export function InspectionScreen({ job }: { job: FieldJob }) {
  const { capturesFor, submitJob, submitted, online } = useField();
  const { data: insp, error, reload } = useFieldLoad((api) => api.getInspection(job.id), `insp-${job.id}`);
  const [answers, setAnswers] = useState<Record<string, Answer>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [values, setValues] = useState<Record<string, string>>({});
  const [defects, setDefects] = useState<Defect[]>([]);
  const [result, setResult] = useState<InspectionResult>();
  const [failReason, setFailReason] = useState('');

  if (submitted[job.id]) {
    return <Submitted title="Result saved." detail="It is sent to Fidero when you have signal. The client and the bank see it only after Fidero checks it." />;
  }
  if (error) return <Screen back><ErrorView message={error} onRetry={reload} /></Screen>;
  if (!insp) return <Screen back><Loading /></Screen>;

  const photos = Object.fromEntries(insp.items.map((i) => [i.id, capturesFor(job.id, i.id).length]));
  const blockers = inspectionBlockers(insp.items, answers, photos, result, defects, failReason);
  const holdback = defectHoldback(defects);
  const done = insp.items.filter((i) => answers[i.id]).length;

  return (
    <Screen
      ground="paper"
      back
      title={job.title}
      eyebrow={`${insp.project} · ${done} of ${insp.items.length} checked`}
      footer={
        <>
          <Button
            title={blockers.length ? `Submit result · ${blockers[0]}` : 'Submit result'}
            disabled={blockers.length > 0}
            onPress={() => submitJob(job.id, `Inspection result: ${job.title}, ${insp.project}`)}
          />
        </>
      }
    >
      {!online ? <OfflineBanner /> : null}
      {insp.conflictChecked ? (
        <Rise>
          <Panel tone="raised" style={{ flexDirection: 'row', alignItems: 'center', paddingVertical: space[3] }}>
            <Ionicons name="shield-checkmark-outline" size={20} color={brand.lime} />
            <T v="callout" color="#F7F6F2" style={{ flex: 1 }}>{`You have no link to this contractor (${insp.contractor}).`}</T>
          </Panel>
        </Rise>
      ) : null}

      {insp.items.map((item, i) => {
        const defect = defects.find((d) => d.itemId === item.id);
        return (
          <Rise key={item.id} delay={60 + i * 50}>
            <Panel style={{ gap: space[2] }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[2] }}>
                <T v="headline" style={{ flex: 1, fontSize: 15 }}>{item.text}</T>
                {item.needsPhoto ? <CaptureButton jobId={job.id} itemId={item.id} label={item.text} count={photos[item.id]} compact /> : null}
                <YesNo label={item.text} value={answers[item.id]} onChange={(v) => setAnswers((a) => ({ ...a, [item.id]: v }))} />
              </View>
              {answers[item.id] === 'no' ? (
                defect ? (
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[2] }}>
                    <T v="footnote" style={{ flex: 1 }}>{`Defect: ${defect.note}`}</T>
                    <T v="headline" style={{ fontSize: 14 }}>{formatMoney(defect.value)}</T>
                  </View>
                ) : (
                  <View style={{ gap: space[2] }}>
                    <Input label="What is wrong?" value={notes[item.id] ?? ''} onChange={(v) => setNotes((n) => ({ ...n, [item.id]: v }))} placeholder="For example: crumbling blocks, east wall" />
                    <Input label="Value to hold back (GHS)" value={values[item.id] ?? ''} onChange={(v) => setValues((n) => ({ ...n, [item.id]: v.replace(/[^0-9.]/g, '') }))} keyboardType="decimal-pad" placeholder="2400" />
                    <Button
                      title="Add as defect"
                      variant="dark"
                      disabled={!(notes[item.id] ?? '').trim() || !(Number(values[item.id]) > 0)}
                      onPress={() =>
                        setDefects((d) => [...d, { id: newId('def'), itemId: item.id, note: (notes[item.id] ?? '').trim(), value: { amountMinor: Math.round(Number(values[item.id]) * 100), currency: 'GHS' } }])
                      }
                    />
                  </View>
                )
              ) : null}
            </Panel>
          </Rise>
        );
      })}

      <Rise delay={400}>
        <Panel style={{ gap: 0 }}>
          <Label>Result</Label>
          <Choice selected={result === 'pass'} onPress={() => setResult('pass')} title="Pass" />
          <Choice
            selected={result === 'pass_with_defects'}
            onPress={() => setResult('pass_with_defects')}
            title="Pass with defects"
            detail={holdback ? `${defects.length} ${defects.length === 1 ? 'defect' : 'defects'} · ${formatMoney(holdback)} held back from this milestone` : 'Each defect needs photos and a value'}
          />
          <Choice selected={result === 'fail'} onPress={() => setResult('fail')} title="Fail" detail="The milestone is not paid until it passes" />
          {result === 'fail' ? <Input label="Why did it fail?" value={failReason} onChange={setFailReason} multiline /> : null}
        </Panel>
      </Rise>
      {blockers.length > 1 ? <T v="footnote" muted>{`Still needed: ${blockers.join(' · ')}`}</T> : null}
    </Screen>
  );
}
