import { Pressable, View } from 'react-native';
import { router } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, font, radius, space } from '@tenmina/tokens';
import { ArrowBox, Chip, Label, Mark, Panel, Rise, Screen, T, haptic } from '@tenmina/ui';
import { Empty, ProblemBox, clock, day, useSession, when } from '@tenmina/mobile';
import { jobKey, useField } from '../../store';
import { KIND_LABEL, OnlineChip } from '../../screens/common';
import type { Job } from '../../types';

function JobCard({ job, next, sent, onPress }: { job: Job; next: boolean; sent: boolean; onPress: () => void }) {
  return (
    <Panel
      tone={next ? 'orange' : 'surface'}
      onPress={onPress}
      accessibilityLabel={`${job.title}. ${job.address}. ${sent ? 'Sent' : next ? 'Next' : ''}`}
      style={{ flexDirection: 'row', alignItems: 'center', gap: space[3] }}
    >
      <View style={{ width: 64, gap: 2 }}>
        <Label color={next ? brand.ink : undefined}>{job.due_at ? clock(job.due_at) : 'Any time'}</Label>
        {next ? <T v="footnote" color={brand.ink}>Next</T> : sent ? <Chip tone="lime" label="Sent" /> : null}
      </View>
      <View style={{ flex: 1 }}>
        <T v="headline" color={next ? brand.ink : undefined} style={{ fontSize: 16 }}>{job.title}</T>
        <T v="footnote" color={next ? '#3A1408' : undefined} muted={!next}>{`${KIND_LABEL[job.kind] ?? job.kind} · ${job.address || '—'}`}</T>
        {!job.accepts_submissions && job.state_reason ? <T v="footnote" color={next ? '#3A1408' : undefined} muted={!next}>{job.state_reason}</T> : null}
      </View>
      <ArrowBox arrow={next ? brand.orange : brand.lime} />
    </Panel>
  );
}

/** My jobs (SCR-MOB-02; FR-MOB-001): everything assigned, from the last sync, readable offline. */
export default function Jobs() {
  const { me } = useSession();
  const { jobs, errands, ops, lastSyncAt, syncNow, syncProblem, online } = useField();
  const waiting = ops.filter((o) => o.state !== 'sent').length;
  const doneKeys = new Set(ops.filter((o) => ['submission', 'inspection', 'checkout'].includes(o.kind) && o.state !== 'failed').map((o) => jobKey(o.subjectType, o.subjectId)));
  // Steps of an errand open the errand screen, which drives them through /v1/mobile/errands.
  const sorted = [...jobs].filter((j) => !(j.details as { errand_id?: string }).errand_id || !errands.some((e) => e.id === (j.details as { errand_id?: string }).errand_id)).sort((a, b) => (a.due_at ?? '9999').localeCompare(b.due_at ?? '9999'));
  const nextJob = sorted.find((j) => j.accepts_submissions && !doneKeys.has(jobKey(j.subject_type, j.subject_id)));
  const today = new Date().toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' }).toUpperCase();

  return (
    <Screen ground="paper" tabs>
      <Rise style={{ flexDirection: 'row', alignItems: 'center', gap: space[2] }}>
        <Mark size={30} />
        <View style={{ flex: 1, flexDirection: 'row', alignItems: 'baseline', gap: space[2] }}>
          <T v="title" style={{ fontFamily: font.heavy, letterSpacing: -1 }}>tenmina</T>
          <Label>Field</Label>
        </View>
        <OnlineChip />
      </Rise>
      <Rise delay={60}>
        <T v="largeTitle" header>My jobs</T>
        <Label>{`${today} · ${me?.full_name ?? ''}`}</Label>
      </Rise>
      {waiting > 0 ? (
        <Pressable
          onPress={() => {
            haptic('tap');
            router.push('/queue');
          }}
          accessibilityRole="button"
          style={({ pressed }) => ({ flexDirection: 'row', alignItems: 'center', gap: space[3], backgroundColor: brand.ink, borderRadius: radius.md + 2, padding: space[3], minHeight: 44, opacity: pressed ? 0.85 : 1 })}
        >
          <Ionicons name="cloud-upload-outline" size={20} color={brand.lime} />
          <T v="callout" color="#F7F6F2" style={{ flex: 1 }}>{`${waiting} ${waiting === 1 ? 'item' : 'items'} saved on this phone. ${online ? 'Sending now.' : 'They upload when you have signal.'}`}</T>
          <Ionicons name="chevron-forward" size={18} color="#A9A69E" />
        </Pressable>
      ) : null}
      {syncProblem && syncProblem.code !== 'offline' ? <ProblemBox problem={syncProblem} onRetry={() => void syncNow()} /> : null}
      {!lastSyncAt && !jobs.length ? <Empty icon="sync-outline" title="Getting your jobs" detail="The first sync needs signal. After that, your jobs stay on this phone." /> : null}
      {lastSyncAt && !jobs.length && !errands.length ? <Empty title="No jobs right now" detail="Tenmina assigns work here. The app checks every minute, or tap sync below." /> : null}
      {sorted.map((j, i) => (
        <Rise key={jobKey(j.subject_type, j.subject_id)} delay={100 + i * 50}>
          <JobCard
            job={j}
            next={j === nextJob}
            sent={doneKeys.has(jobKey(j.subject_type, j.subject_id))}
            onPress={() => router.push({ pathname: '/job/[type]/[id]', params: { type: j.subject_type, id: j.subject_id } })}
          />
        </Rise>
      ))}
      {errands.length ? (
        <View style={{ gap: space[2] }}>
          <Label>Errands</Label>
          {errands.map((e) => (
            <Panel key={e.id} onPress={() => router.push({ pathname: '/errand/[id]', params: { id: e.id } })} style={{ flexDirection: 'row', alignItems: 'center', gap: space[3] }}>
              <View style={{ flex: 1 }}>
                <T v="headline" style={{ fontSize: 16 }}>{e.name}</T>
                <T v="footnote" muted>{`${e.reference} · ${e.steps.filter((s) => s.status === 'done').length} of ${e.steps.length} steps${e.due_on ? ` · due ${day(e.due_on)}` : ''}`}</T>
              </View>
              <ArrowBox />
            </Panel>
          ))}
        </View>
      ) : null}
      <Pressable onPress={() => void syncNow()} accessibilityRole="button" style={{ minHeight: 44, justifyContent: 'center' }}>
        <Label style={{ textAlign: 'center' }}>{lastSyncAt ? `Last sync ${when(lastSyncAt)} · tap to sync now` : 'Tap to sync now'}</Label>
      </Pressable>
    </Screen>
  );
}
