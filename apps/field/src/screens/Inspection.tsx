import { useState } from 'react';
import { Pressable, View } from 'react-native';
import { space } from '@tenmina/tokens';
import { Button, Choice, Input, Label, Panel, Rise, Screen, T, YesNo, haptic, usePalette } from '@tenmina/ui';
import { day, moneyOf } from '@tenmina/mobile';
import { jobKey, useField } from '../store';
import type { Job } from '../types';
import { CheckCard } from './CheckIn';
import { CaptureButton, ConflictStrip, OfflineBanner, Submitted, useDone } from './common';

type Result = 'pass' | 'pass_with_defects' | 'fail';
interface DefectDraft {
  n: number;
  itemKey: string;
  description: string;
  amount: string;
}

const CURRENCY: Record<string, string> = { GH: 'GHS', NG: 'NGN', KE: 'KES' };

/**
 * Inspection checklist, defects and result (W-18; SCR-MOB-09, 10, 11, 18;
 * FR-MOB-007, RUL-09, RUL-10): every item answered, a defect needs photos and
 * a value, a fail needs a reason. The inspector's pay is the same whatever
 * they find.
 */
export function InspectionScreen({ job }: { job: Job }) {
  const pal = usePalette('paper');
  const { capturesFor, queue, progress, setProgress } = useField();
  const key = jobKey(job.subject_type, job.subject_id);
  const saved = progress(key) as { answers?: Record<string, 'yes' | 'no' | 'na'>; defects?: DefectDraft[]; result?: Result; reason?: string; checkin?: string; checkinWhy?: string };
  const [answers, setAnswers] = useState<Record<string, 'yes' | 'no' | 'na'>>(saved.answers ?? {});
  const [defects, setDefects] = useState<DefectDraft[]>(saved.defects ?? []);
  const [result, setResult] = useState<Result | undefined>(saved.result);
  const [reason, setReason] = useState(saved.reason ?? '');
  const done = useDone(job, ['inspection']);
  const currency = CURRENCY[job.country ?? 'GH'] ?? 'GHS';
  const keep = (patch: Record<string, unknown>) => setProgress(key, patch);

  if (done) {
    return <Submitted ground="paper" title="Result saved." detail="It goes to Tenmina when you have signal. The client and the bank see it only after Tenmina checks it." />;
  }

  const photos = (k: string) => capturesFor(job.subject_type, job.subject_id, k).length;
  const answered = job.checklist.filter((c) => answers[c.key]).length;
  const blockers: string[] = [];
  if (answered < job.checklist.length) blockers.push(`${job.checklist.length - answered} checks to answer`);
  if (!result) blockers.push('choose a result');
  if (result === 'pass' && defects.length) blockers.push('a pass has no defects');
  if (result === 'pass_with_defects' && !defects.length) blockers.push('add a defect');
  if (result === 'fail' && reason.trim().length < 5) blockers.push('say why it failed');
  if (result === 'pass_with_defects') {
    for (const df of defects) {
      if (!df.description.trim() || !(Number(df.amount) > 0)) blockers.push(`defect ${df.n}: a description and a value`);
      else if (!photos(`defect_${df.n}`)) blockers.push(`defect ${df.n}: a photo`);
    }
  }
  const holdback = defects.reduce((s, d) => s + (Number(d.amount) || 0), 0);

  function answer(k: string, v: 'yes' | 'no' | 'na') {
    const next = { ...answers, [k]: v };
    setAnswers(next);
    keep({ answers: next });
  }
  function setDefect(n: number, patch: Partial<DefectDraft>) {
    const next = defects.map((d) => (d.n === n ? { ...d, ...patch } : d));
    setDefects(next);
    keep({ defects: next });
  }

  function submit() {
    const ds = result === 'pass_with_defects' ? defects : [];
    const needs: { captureId: string; at: string }[] = [];
    const body = {
      client_submission_id: '',
      subject_type: job.subject_type,
      subject_id: job.subject_id,
      outcome: result,
      checklist: job.checklist.map((c) => ({ key: c.key, result: answers[c.key] === 'yes' ? 'ok' : answers[c.key] === 'no' ? 'not_ok' : 'na' })),
      defects: ds.map((d, i) => {
        const caps = capturesFor(job.subject_type, job.subject_id, `defect_${d.n}`);
        caps.forEach((c, j) => needs.push({ captureId: c.id, at: `defects.${i}.evidence_ids.${j}` }));
        return { description: d.description.trim(), value: { amount: Number(d.amount).toFixed(2), currency }, evidence_ids: caps.map(() => null) };
      }),
      reason: result === 'fail' ? reason.trim() : '',
      note: saved.checkinWhy ? `Checked in away from the address: ${saved.checkinWhy}` : '',
    };
    queue({ kind: 'inspection', label: `Inspection result: ${job.title}`, subjectType: job.subject_type, subjectId: job.subject_id, path: '/v1/mobile/inspections', body, needs });
  }

  return (
    <Screen
      ground="paper"
      back
      title={job.title}
      eyebrow={`${answered} of ${job.checklist.length} checked${job.previous_pass_at ? ` · last pass ${day(job.previous_pass_at)}` : ''}`}
      footer={<Button title={blockers.length ? `Submit result · ${blockers[0]}` : 'Submit result'} disabled={blockers.length > 0 || !job.accepts_submissions} onPress={submit} />}
    >
      <OfflineBanner />
      <ConflictStrip who={(job.details.contractor as string | undefined) ?? 'the contractor or the client'} />
      <T v="callout" muted>{job.address}</T>
      {job.point ? <CheckCard job={job} kind="checkin" done={saved.checkin} onDone={(at, why) => keep({ checkin: at, checkinWhy: why })} /> : null}
      {!job.accepts_submissions ? (
        <Panel>
          <Label>Not open yet</Label>
          <T v="callout">{job.state_reason || 'The contractor has not submitted this milestone yet.'}</T>
        </Panel>
      ) : null}

      {job.checklist.map((item, i) => (
        <Rise key={item.key} delay={40 + i * 40}>
          <Panel style={{ gap: space[2] }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[2] }}>
              <T v="headline" style={{ flex: 1, fontSize: 15 }}>{item.label ?? item.key}</T>
              <CaptureButton subjectType={job.subject_type} subjectId={job.subject_id} reqKey={item.key} label={item.label ?? item.key} count={photos(item.key)} compact />
              <YesNo label={item.label ?? item.key} value={answers[item.key] === 'na' ? undefined : (answers[item.key] as 'yes' | 'no' | undefined)} onChange={(v) => answer(item.key, v)} />
            </View>
            <Pressable onPress={() => answer(item.key, 'na')} accessibilityRole="radio" accessibilityState={{ selected: answers[item.key] === 'na' }} style={{ alignSelf: 'flex-start', minHeight: 32, justifyContent: 'center' }}>
              <Label color={answers[item.key] === 'na' ? pal.text : undefined}>{answers[item.key] === 'na' ? '● Not applicable' : '○ Not applicable'}</Label>
            </Pressable>
            {answers[item.key] === 'no' && !defects.some((d) => d.itemKey === item.key) ? (
              <Button
                title="Add as a defect"
                variant="dark"
                icon="add"
                onPress={() => {
                  haptic('tap');
                  const n = (defects.reduce((m, d) => Math.max(m, d.n), 0) || 0) + 1;
                  const next = [...defects, { n, itemKey: item.key, description: item.label ?? '', amount: '' }];
                  setDefects(next);
                  keep({ defects: next });
                }}
              />
            ) : null}
          </Panel>
        </Rise>
      ))}

      {defects.length ? (
        <View style={{ gap: space[2] }}>
          <Label>{`Defects · ${moneyOf(holdback.toFixed(2), currency)} held back`}</Label>
          {defects.map((d) => (
            <Panel key={d.n} style={{ gap: space[2] }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[2] }}>
                <T v="headline" style={{ flex: 1, fontSize: 15 }}>{`Defect ${d.n}`}</T>
                <CaptureButton subjectType={job.subject_type} subjectId={job.subject_id} reqKey={`defect_${d.n}`} label={`Defect ${d.n}`} count={photos(`defect_${d.n}`)} />
              </View>
              <Input label="What is wrong?" value={d.description} onChange={(v) => setDefect(d.n, { description: v })} placeholder="For example: crumbling blocks, east wall" />
              <Input label={`Value to hold back (${currency})`} value={d.amount} onChange={(v) => setDefect(d.n, { amount: v.replace(/[^0-9.]/g, '') })} keyboardType="decimal-pad" />
              <Button
                title="Remove this defect"
                variant="quiet"
                onPress={() => {
                  const next = defects.filter((x) => x.n !== d.n);
                  setDefects(next);
                  keep({ defects: next });
                }}
              />
            </Panel>
          ))}
        </View>
      ) : null}

      <Panel style={{ gap: 0 }}>
        <Label>Result</Label>
        <Choice selected={result === 'pass'} onPress={() => (setResult('pass'), keep({ result: 'pass' }))} title="Pass" />
        <Choice selected={result === 'pass_with_defects'} onPress={() => (setResult('pass_with_defects'), keep({ result: 'pass_with_defects' }))} title="Pass with defects" detail="Each defect needs photos and a value, held back until fixed" />
        <Choice selected={result === 'fail'} onPress={() => (setResult('fail'), keep({ result: 'fail' }))} title="Fail" detail="The milestone is not paid until it passes" />
        {result === 'fail' ? (
          <Input
            label="Why did it fail?"
            value={reason}
            onChange={(v) => {
              setReason(v);
              keep({ reason: v });
            }}
            multiline
          />
        ) : null}
      </Panel>
      {blockers.length > 1 ? <T v="footnote" muted>{`Still needed: ${blockers.join(' · ')}`}</T> : null}
    </Screen>
  );
}
