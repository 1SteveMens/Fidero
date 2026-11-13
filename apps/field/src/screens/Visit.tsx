import { useEffect, useState } from 'react';
import { Pressable, View } from 'react-native';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, space } from '@tenmina/tokens';
import { Button, Input, Label, Panel, Screen, T, Tick, haptic } from '@tenmina/ui';
import { clock } from '@tenmina/mobile';
import { jobKey, useField } from '../store';
import type { Job, PlanItem } from '../types';
import { CheckCard } from './CheckIn';
import { CaptureButton, OfflineBanner } from './common';

type Outcome = 'done' | 'not_done' | 'not_applicable';
interface ItemState {
  outcome?: Outcome;
  reason?: string;
  reading?: Record<string, string>;
}

const READING_FIELDS: Record<string, { key: string; label: string; unit: string }[]> = {
  blood_pressure: [
    { key: 'systolic', label: 'Systolic (top)', unit: 'mmHg' },
    { key: 'diastolic', label: 'Diastolic (bottom)', unit: 'mmHg' },
  ],
  blood_sugar: [{ key: 'value', label: 'Blood sugar', unit: 'mmol/L' }],
  temperature: [{ key: 'value', label: 'Temperature', unit: '°C' }],
  weight: [{ key: 'value', label: 'Weight', unit: 'kg' }],
  pulse: [{ key: 'value', label: 'Pulse', unit: 'bpm' }],
};
const KINDS = ['health', 'safety', 'welfare'] as const;

function needsOf(i: PlanItem): string[] {
  return Array.isArray(i.needs) ? i.needs : i.needs ? [i.needs] : [];
}

/**
 * Care visit on Tenmina Field (W-30; SCR-MOB-14, 15, 16; FR-MOB-012,
 * FR-CARE-003, FR-CARE-006, RUL-23): check in at the address, each plan item
 * with its agreed photo or reading, raise a concern, check out. Tenmina then
 * sends the family their own code; the carer never sees it.
 */
export function VisitScreen({ job }: { job: Job }) {
  const { capturesFor, queue, progress, setProgress } = useField();
  const key = jobKey(job.subject_type, job.subject_id);
  const saved = progress(key) as { checkin?: string; checkinWhy?: string; checkout?: string; items?: Record<string, ItemState>; sentItems?: string[]; concern?: string };
  const [items, setItems] = useState<Record<string, ItemState>>(saved.items ?? {});
  const [concernKind, setConcernKind] = useState<(typeof KINDS)[number]>();
  const [concernText, setConcernText] = useState('');
  const careVisit = job.source.startsWith('care');
  const family = (job.details.family_first_name as string | undefined) ?? 'the family';
  const photoKeys = new Set(job.required_evidence.filter((r) => r.media === 'photo').map((r) => r.key));
  const plan: PlanItem[] = job.plan_items.length ? job.plan_items : job.required_evidence.map((r) => ({ key: r.key, label: r.label ?? r.key, needs: 'photo' }));
  const keep = (patch: Record<string, unknown>) => setProgress(key, patch);

  const photoNeeded = (i: PlanItem) => photoKeys.has(i.key) || needsOf(i).includes('photo');
  const photoAllowed = (i: PlanItem) => photoNeeded(i) || !!i.photo_allowed;
  const readingKind = (i: PlanItem) => i.reading_kind || (needsOf(i).includes('reading') ? 'value' : '');
  const fields = (i: PlanItem) => READING_FIELDS[readingKind(i)] ?? [{ key: 'value', label: 'Reading', unit: '' }];
  const photos = (i: PlanItem) => capturesFor(job.subject_type, job.subject_id, i.key);
  const ready = (i: PlanItem) => {
    const s = items[i.key];
    if (!s?.outcome) return false;
    if (s.outcome === 'not_done') return (s.reason ?? '').trim().length >= 3;
    if (s.outcome === 'done') {
      if (photoNeeded(i) && !photos(i).length) return false;
      if (readingKind(i)) return fields(i).every((f) => (s.reading?.[f.key] ?? '').trim() !== '');
    }
    return true;
  };
  const left = plan.filter((i) => !ready(i)).length;

  function setItem(k: string, patch: ItemState) {
    setItems((prev) => ({ ...prev, [k]: { ...prev[k], ...patch } }));
  }
  useEffect(() => {
    keep({ items });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items]);

  /** Each item goes to the server on its own once the carer is checked in (care visits), or with the check-out (other visits). */
  function checkOut(at: string) {
    if (careVisit) {
      for (const i of plan) {
        const s = items[i.key];
        if (!s?.outcome) continue;
        const caps = photos(i);
        const reading = readingKind(i) && s.outcome === 'done' ? { ...Object.fromEntries(fields(i).map((f) => [f.key, Number(s.reading?.[f.key])])), unit: fields(i)[0]?.unit || undefined } : null;
        queue({
          kind: 'visit_item',
          label: `${i.label}: ${s.outcome === 'done' ? 'done' : s.outcome === 'not_done' ? 'not done' : 'not applicable'}`,
          subjectType: job.subject_type,
          subjectId: job.subject_id,
          method: 'PUT',
          path: `/v1/mobile/visits/${job.subject_id}/items/${i.key}`,
          body: { outcome: s.outcome, reason: s.reason ?? '', reading, evidence_id: null },
          needs: caps.length && s.outcome === 'done' ? [{ captureId: caps[caps.length - 1].id, at: 'evidence_id' }] : [],
        });
      }
    } else {
      const its: Record<string, unknown>[] = [];
      const needs: { captureId: string; at: string }[] = [];
      for (const i of plan) {
        const s = items[i.key];
        for (const c of photos(i)) {
          needs.push({ captureId: c.id, at: `items.${its.length}.evidence_id` });
          its.push({ requirement_key: i.key, evidence_id: null });
        }
        if (s?.outcome && !photoNeeded(i)) its.push({ requirement_key: i.key, value: { outcome: s.outcome, reason: s.reason ?? '', reading: s.reading ?? null } });
      }
      queue({ kind: 'submission', label: `Care visit: ${job.title}`, subjectType: job.subject_type, subjectId: job.subject_id, path: '/v1/mobile/submissions', body: { client_submission_id: '', subject_type: job.subject_type, subject_id: job.subject_id, items: its, note: saved.checkinWhy ? `Checked in away from the address: ${saved.checkinWhy}` : '' }, needs });
    }
    keep({ checkout: at, items });
  }

  function sendConcern() {
    if (!concernKind) return;
    queue({ kind: 'concern', label: `${concernKind} concern`, subjectType: job.subject_type, subjectId: job.subject_id, path: `/v1/mobile/visits/${job.subject_id}/concerns`, body: { kind: concernKind, severity: 'medium', narrative: concernText.trim() } });
    keep({ concern: new Date().toISOString() });
    setConcernText('');
  }

  const concern = careVisit ? (
    <Panel style={{ gap: space[2], borderWidth: 2, borderColor: '#3A3A3A', backgroundColor: 'transparent' }}>
      <Label color={brand.orange}>Raise a concern</Label>
      {saved.concern ? (
        <T v="callout">{`Sent at ${clock(saved.concern)}. The family and a Tenmina reviewer hear about it today.`}</T>
      ) : (
        <>
          <View style={{ flexDirection: 'row', gap: space[2] }}>
            {KINDS.map((c) => (
              <Pressable
                key={c}
                onPress={() => {
                  haptic('tap');
                  setConcernKind(c);
                }}
                accessibilityRole="radio"
                accessibilityState={{ selected: concernKind === c }}
                style={{ flex: 1, height: 44, borderRadius: 12, alignItems: 'center', justifyContent: 'center', backgroundColor: concernKind === c ? brand.orange : '#242424' }}
              >
                <T v="headline" color={concernKind === c ? brand.ink : '#F7F6F2'} style={{ fontSize: 14 }}>{c.charAt(0).toUpperCase() + c.slice(1)}</T>
              </Pressable>
            ))}
          </View>
          {concernKind ? (
            <>
              <Input label="What happened?" value={concernText} onChange={setConcernText} multiline />
              <Button title="Send the concern" variant="dark" disabled={concernText.trim().length < 5} onPress={sendConcern} />
            </>
          ) : null}
        </>
      )}
    </Panel>
  ) : null;

  if (saved.checkout) {
    return (
      <Screen ground="ink" back title="Visit finished">
        <View style={{ alignItems: 'center', paddingTop: space[6], gap: space[4] }}>
          <View style={{ width: 96, height: 96, borderRadius: 48, backgroundColor: brand.lime, alignItems: 'center', justifyContent: 'center' }}>
            <Ionicons name="checkmark" size={52} color={brand.ink} />
          </View>
          <T v="display" header style={{ textAlign: 'center' }}>{`Checked out at ${clock(saved.checkout)}.`}</T>
        </View>
        <Panel style={{ gap: space[3] }}>
          <Label color={brand.lime}>Next: the family confirms</Label>
          <T v="callout">{`Tenmina sends ${family} a link and a code on their own phone. You never see the code, and nobody should ask you for it.`}</T>
          <T v="callout" muted>You are paid for this visit after the family confirms it.</T>
        </Panel>
        <OfflineBanner />
        {concern}
      </Screen>
    );
  }

  if (!saved.checkin) {
    return (
      <Screen ground="ink" back title={job.title} eyebrow={`Care visit${job.due_at ? ` · from ${clock(job.due_at)}` : ''}`}>
        <OfflineBanner />
        <T v="callout" muted>{job.address}</T>
        <CheckCard job={job} kind="checkin" onDone={(at, why) => keep({ checkin: at, checkinWhy: why })} />
        <Panel style={{ gap: 0, paddingVertical: space[1] }}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', paddingVertical: space[3] }}>
            <T v="callout" muted>Plan</T>
            <T v="callout">{`${plan.length} items · ${plan.filter(photoNeeded).length} with photos`}</T>
          </View>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', paddingVertical: space[3], borderTopWidth: 1, borderTopColor: '#2C2C2C' }}>
            <T v="callout" muted>After the visit</T>
            <T v="callout">{`${family} confirms`}</T>
          </View>
        </Panel>
        {concern}
      </Screen>
    );
  }

  return (
    <Screen ground="ink" back title={job.title} eyebrow={`Checked in ${clock(saved.checkin)}${saved.checkinWhy ? ' · away from the address' : ' · at the address'}`}>
      <OfflineBanner />
      <Label>{`Plan · ${plan.length - left} of ${plan.length} recorded`}</Label>
      {plan.map((i) => {
        const s = items[i.key] ?? {};
        const n = photos(i).length;
        return (
          <Panel key={i.key} style={{ gap: space[2] }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[3] }}>
              {ready(i) ? <Tick size={24} /> : <View style={{ width: 24, height: 24, borderRadius: 8, borderWidth: 2, borderColor: '#3A3A3A' }} />}
              <T v="headline" style={{ flex: 1, fontSize: 15 }}>{i.label}</T>
              {photoAllowed(i) ? <CaptureButton subjectType={job.subject_type} subjectId={job.subject_id} reqKey={i.key} label={i.label} count={n} compact /> : null}
            </View>
            <View style={{ flexDirection: 'row', gap: space[2] }}>
              {(['done', 'not_done', 'not_applicable'] as Outcome[]).map((o) => (
                <Pressable
                  key={o}
                  onPress={() => {
                    haptic('tap');
                    setItem(i.key, { outcome: o });
                  }}
                  accessibilityRole="radio"
                  accessibilityState={{ selected: s.outcome === o }}
                  style={{ flex: 1, height: 44, borderRadius: 12, alignItems: 'center', justifyContent: 'center', backgroundColor: s.outcome === o ? (o === 'done' ? brand.lime : '#F7F6F2') : '#242424' }}
                >
                  <T v="headline" color={s.outcome === o ? brand.ink : '#F7F6F2'} style={{ fontSize: 13 }}>{o === 'done' ? 'Done' : o === 'not_done' ? 'Not done' : 'N/A'}</T>
                </Pressable>
              ))}
            </View>
            {s.outcome === 'done' && photoNeeded(i) && !n ? <Label>Photo first</Label> : null}
            {s.outcome === 'done' && readingKind(i)
              ? fields(i).map((f) => (
                  <Input
                    key={f.key}
                    label={`${f.label}${f.unit ? ` (${f.unit})` : ''}`}
                    value={s.reading?.[f.key] ?? ''}
                    keyboardType="decimal-pad"
                    onChange={(v) => setItem(i.key, { reading: { ...(s.reading ?? {}), [f.key]: v.replace(/[^0-9.]/g, '') } })}
                  />
                ))
              : null}
            {s.outcome === 'not_done' ? <Input label="Why not?" value={s.reason ?? ''} onChange={(v) => setItem(i.key, { reason: v })} placeholder="For example: she was asleep" hint={`${family} sees this.`} /> : null}
          </Panel>
        );
      })}
      {left === 0 ? (
        <CheckCard job={job} kind="checkout" onDone={(at) => checkOut(at)} />
      ) : (
        <Panel>
          <Label>Check out</Label>
          <T v="callout" muted>{`Record every item first: ${left} left. Mark one "Not done" with a reason if it could not be done.`}</T>
        </Panel>
      )}
      {concern}
    </Screen>
  );
}
