import { View } from 'react-native';
import Ionicons from '@expo/vector-icons/Ionicons';
import { distanceWarning, missingEvidence, type FieldJob } from '@tenmina/shared';
import { brand, space } from '@tenmina/tokens';
import { Button, ErrorView, Label, Loading, Panel, Rise, Screen, T, Tick } from '@tenmina/ui';
import { useField, useFieldLoad } from '../store';
import { CaptureButton, OfflineBanner, Submitted } from './common';

/** Contractor milestone evidence and submission, offline first (W-17, SCR-MOB-03 to 07; FR-MOB-005, FR-MOB-006). */
export function MilestoneScreen({ job }: { job: FieldJob }) {
  const { capturesFor, submitJob, submitted, online } = useField();
  const { data: ms, error, reload } = useFieldLoad((api) => api.getMilestone(job.id), `ms-${job.id}`);

  if (submitted[job.id]) {
    return <Submitted title="Milestone submitted." detail={online ? 'It is on its way to Tenmina. An inspector checks it next.' : 'Saved on this phone. It is sent by itself when you have signal. Keep the app installed.'} />;
  }
  if (error) return <Screen ground="ink" back><ErrorView message={error} onRetry={reload} /></Screen>;
  if (!ms) return <Screen ground="ink" back><Loading /></Screen>;

  const counts = Object.fromEntries(ms.evidence.map((e) => [e.id, capturesFor(job.id, e.id).length]));
  const missing = missingEvidence(ms.evidence, counts);
  const all = capturesFor(job.id);
  const far = all.filter((c) => distanceWarning(c.distanceM, job.site)).length;

  return (
    <Screen
      ground="ink"
      back
      title={ms.name}
      eyebrow={`${ms.project} · milestone ${ms.number} of ${ms.count}`}
      footer={
        <>
          <Button
            title={missing.length ? `Submit · ${missing.length} still needed` : 'Submit milestone'}
            icon="cloud-upload-outline"
            disabled={missing.length > 0}
            onPress={() => submitJob(job.id, `Milestone ${ms.number}: ${ms.name}, ${ms.project}`)}
          />
          <T v="footnote" muted style={{ textAlign: 'center' }}>Submitted offline, it is sent by itself when you have signal.</T>
        </>
      }
    >
      {!online ? <OfflineBanner /> : null}
      <Rise style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-end' }}>
        <T v="headline" header style={{ fontSize: 18 }}>Evidence</T>
        <T v="title">
          {String(ms.evidence.length - missing.length)}
          <T v="title" color="#55534D">{`/${ms.evidence.length}`}</T>
        </T>
      </Rise>
      <Rise delay={80}>
        <Panel style={{ gap: 0, paddingVertical: space[1] }}>
          {ms.evidence.map((e, i) => {
            const n = counts[e.id];
            const ok = n >= e.min;
            return (
              <View key={e.id} style={{ flexDirection: 'row', alignItems: 'center', gap: space[3], paddingVertical: space[3], borderBottomWidth: i < ms.evidence.length - 1 ? 1 : 0, borderBottomColor: '#2C2C2C' }}>
                {ok ? <Tick /> : <View style={{ width: 22, height: 22, borderRadius: 7, borderWidth: 2, borderColor: '#3A3A3A' }} />}
                <View style={{ flex: 1 }}>
                  <T v="callout">{e.label}</T>
                  <Label>{`${n} of ${e.min} ${e.kind === 'video' ? (e.min === 1 ? 'video' : 'videos') : e.min === 1 ? 'photo' : 'photos'}`}</Label>
                </View>
                <CaptureButton jobId={job.id} itemId={e.id} label={e.label} kind={e.kind} count={n} />
              </View>
            );
          })}
        </Panel>
      </Rise>
      {all.length > 0 ? (
        <Rise delay={160} style={{ flexDirection: 'row', gap: space[3], alignItems: 'flex-start' }}>
          <Ionicons name={far ? 'alert-circle' : 'locate'} size={20} color={far ? brand.orange : brand.lime} />
          <T v="callout" muted style={{ flex: 1 }}>
            {far ? `${far} ${far === 1 ? 'capture was' : 'captures were'} taken away from the site, with your reason. Tenmina checks them.` : 'All taken with this app. Position checked: on the site.'}
          </T>
        </Rise>
      ) : null}
    </Screen>
  );
}
