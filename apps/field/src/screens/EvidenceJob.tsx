import { useState } from 'react';
import { View } from 'react-native';
import { space } from '@tenmina/tokens';
import { Button, Input, Label, Panel, Rise, Screen, T, Tick } from '@tenmina/ui';
import { day } from '@tenmina/mobile';
import { jobKey, useField } from '../store';
import type { Job } from '../types';
import { CheckCard } from './CheckIn';
import { CaptureButton, KIND_LABEL, OfflineBanner, SearchStrip, Submitted, useDone } from './common';

const isMedia = (m?: string) => m === 'photo' || m === 'video' || m === undefined;

/**
 * Evidence for a milestone, a case task, an errand step or a bill to collect
 * (SCR-MOB-03, 04, 07, 12; FR-MOB-006, FR-MOB-010): each required item from the
 * schedule, taken in this app, then one submission. Offline, it waits on the
 * phone and is sent by itself (FR-MOB-005).
 */
export function EvidenceJobScreen({ job }: { job: Job }) {
  const { capturesFor, queue, progress, setProgress } = useField();
  const key = jobKey(job.subject_type, job.subject_id);
  const saved = progress(key) as { values?: Record<string, string>; note?: string; checkin?: string; checkinWhy?: string };
  const [values, setValues] = useState<Record<string, string>>(saved.values ?? {});
  const [note, setNote] = useState(saved.note ?? '');
  const done = useDone(job, ['submission']);
  const d = job.details as { case_ref?: string; step_key?: string; notice?: string; instructions?: string; note?: string; institution?: string };
  const search = !!d.notice || /search/i.test(d.step_key ?? '') || /search/i.test(job.title);
  const needsCheckIn = job.subject_type === 'errand_step' && !!job.point;

  if (done) {
    return <Submitted ground="paper" title="Sent." detail="It is saved on this phone and goes to Tenmina when you have signal. A reviewer checks it before anything is paid." />;
  }

  const counts = Object.fromEntries(job.required_evidence.map((r) => [r.key, capturesFor(job.subject_type, job.subject_id, r.key).length]));
  const missing = job.required_evidence.filter((r) => r.required !== false && (isMedia(r.media) ? !counts[r.key] : !(values[r.key] ?? '').trim()));
  const keep = (patch: Record<string, unknown>) => setProgress(key, patch);

  function submit() {
    const items: Record<string, unknown>[] = [];
    const needs: { captureId: string; at: string }[] = [];
    for (const r of job.required_evidence) {
      if (isMedia(r.media)) {
        for (const c of capturesFor(job.subject_type, job.subject_id, r.key)) {
          needs.push({ captureId: c.id, at: `items.${items.length}.evidence_id` });
          items.push({ requirement_key: r.key, evidence_id: null });
        }
      } else if ((values[r.key] ?? '').trim()) {
        items.push({ requirement_key: r.key, value: values[r.key].trim() });
      }
    }
    const why = saved.checkinWhy ? `Checked in away from the address: ${saved.checkinWhy}. ` : '';
    queue({
      kind: 'submission',
      label: `${KIND_LABEL[job.kind] ?? 'Job'}: ${job.title}`,
      subjectType: job.subject_type,
      subjectId: job.subject_id,
      path: '/v1/mobile/submissions',
      body: { client_submission_id: '', subject_type: job.subject_type, subject_id: job.subject_id, items, note: `${why}${note.trim()}`.trim() },
      needs,
    });
  }

  return (
    <Screen
      ground="paper"
      back
      title={job.title}
      eyebrow={`${KIND_LABEL[job.kind] ?? job.kind}${d.case_ref ? ` · ${d.case_ref}` : ''}${job.due_at ? ` · by ${day(job.due_at)}` : ''}`}
      footer={
        <>
          <Button
            title={missing.length ? `Submit · ${missing.length} still needed` : 'Submit'}
            icon="cloud-upload-outline"
            disabled={missing.length > 0 || !job.accepts_submissions || (needsCheckIn && !saved.checkin)}
            onPress={submit}
          />
          <T v="footnote" muted style={{ textAlign: 'center' }}>Submitted offline, it is sent by itself when you have signal.</T>
        </>
      }
    >
      <OfflineBanner />
      <T v="callout" muted>{job.address}</T>
      {search ? <SearchStrip /> : null}
      {d.instructions || d.note ? (
        <Panel>
          {d.institution ? <Label>{d.institution}</Label> : null}
          {d.instructions ? <T v="callout">{d.instructions}</T> : null}
          {d.note ? <T v="footnote" muted>{d.note}</T> : null}
        </Panel>
      ) : null}
      {!job.accepts_submissions ? (
        <Panel>
          <Label>Not open for submission</Label>
          <T v="callout">{job.state_reason || 'Tenmina will tell you when to send it.'}</T>
        </Panel>
      ) : null}
      {needsCheckIn ? (
        <CheckCard job={job} kind="checkin" done={saved.checkin} onDone={(at, why) => keep({ checkin: at, checkinWhy: why })} />
      ) : null}

      {job.required_evidence.length ? (
        <Rise>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: space[2] }}>
            <T v="headline" header style={{ fontSize: 18 }}>What to send</T>
            <T v="title">{`${job.required_evidence.length - missing.length}/${job.required_evidence.length}`}</T>
          </View>
          <Panel style={{ gap: 0, paddingVertical: space[1] }}>
            {job.required_evidence.map((r, i) => {
              const media = isMedia(r.media);
              const n = counts[r.key] ?? 0;
              const ok = media ? n > 0 : !!(values[r.key] ?? '').trim();
              return (
                <View key={r.key} style={{ paddingVertical: space[3], borderTopWidth: i ? 1 : 0, borderTopColor: '#ECEAE4', gap: space[2] }}>
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[3] }}>
                    {ok ? <Tick /> : <View style={{ width: 22, height: 22, borderRadius: 7, borderWidth: 2, borderColor: '#D6D3CB' }} />}
                    <View style={{ flex: 1 }}>
                      <T v="callout">{r.label ?? r.key}</T>
                      <Label>{media ? `${n} ${r.media === 'video' ? (n === 1 ? 'video' : 'videos') : n === 1 ? 'photo' : 'photos'}${r.required === false ? ' · optional' : ''}` : r.required === false ? 'Optional' : 'Needed'}</Label>
                    </View>
                    {media ? <CaptureButton subjectType={job.subject_type} subjectId={job.subject_id} reqKey={r.key} label={r.label ?? r.key} kind={r.media === 'video' ? 'video' : 'photo'} count={n} /> : null}
                  </View>
                  {!media ? (
                    <Input
                      label={r.label ?? r.key}
                      value={values[r.key] ?? ''}
                      onChange={(v) => {
                        const next = { ...values, [r.key]: v };
                        setValues(next);
                        keep({ values: next });
                      }}
                    />
                  ) : null}
                </View>
              );
            })}
          </Panel>
        </Rise>
      ) : (
        <Panel>
          <T v="callout">Nothing to photograph for this job. Add a note and submit when it is done.</T>
        </Panel>
      )}
      <Input
        label="Note for Tenmina (optional)"
        value={note}
        onChange={(v) => {
          setNote(v);
          keep({ note: v });
        }}
        multiline
      />
    </Screen>
  );
}
