import { Pressable, View } from 'react-native';
import { router } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, radius, space } from '@tenmina/tokens';
import { Button, Chip, Panel, Screen, T, haptic, usePalette } from '@tenmina/ui';
import { useField } from '../store';
import type { Job } from '../types';

/** Opens the app's own camera for one evidence item. There is no gallery or file button anywhere (RUL-08). */
export function CaptureButton({ subjectType, subjectId, reqKey, label, kind = 'photo', count, compact }: { subjectType: string; subjectId: string; reqKey: string; label: string; kind?: 'photo' | 'video'; count: number; compact?: boolean }) {
  const p = usePalette();
  const icon = kind === 'video' ? 'videocam-outline' : 'camera-outline';
  return (
    <Pressable
      onPress={() => {
        haptic('tap');
        router.push({ pathname: '/capture', params: { subjectType, subjectId, reqKey, label, kind } });
      }}
      accessibilityRole="button"
      accessibilityLabel={`${kind === 'video' ? 'Record a video' : 'Take a photo'} for ${label}. ${count} taken.`}
      style={({ pressed }) => ({
        height: 44,
        minWidth: 44,
        paddingHorizontal: compact ? 0 : space[3],
        borderRadius: 12,
        backgroundColor: count > 0 ? brand.ink : p.ground,
        borderWidth: count > 0 ? 0 : 2,
        borderColor: p.lineStrong,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 6,
        opacity: pressed ? 0.8 : 1,
      })}
    >
      <Ionicons name={icon} size={18} color={count > 0 ? brand.lime : p.text} />
      {count > 0 ? <T v="headline" color={brand.lime} style={{ fontSize: 14 }}>{String(count)}</T> : null}
    </Pressable>
  );
}

/** Shown after a job is submitted: saved on the phone, sent when there is signal. */
export function Submitted({ title, detail, ground = 'ink' }: { title: string; detail: string; ground?: 'ink' | 'paper' }) {
  return (
    <Screen ground={ground} footer={<Button title="Back to my jobs" onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))} />}>
      <View style={{ alignItems: 'center', paddingTop: space[8], gap: space[4] }}>
        <View style={{ width: 96, height: 96, borderRadius: 48, backgroundColor: brand.lime, alignItems: 'center', justifyContent: 'center' }}>
          <Ionicons name="checkmark" size={52} color={brand.ink} />
        </View>
        <T v="display" header style={{ textAlign: 'center' }}>{title}</T>
        <T v="callout" muted style={{ textAlign: 'center' }}>{detail}</T>
      </View>
    </Screen>
  );
}

/** The offline banner (CMP-13): on every work screen while there is no signal. */
export function OfflineBanner() {
  const { online, ops } = useField();
  if (online) return null;
  const n = ops.filter((o) => o.state !== 'sent').length;
  return (
    <Panel tone="orange" style={{ flexDirection: 'row', alignItems: 'center', borderRadius: radius.md + 2, paddingVertical: space[3] }}>
      <Ionicons name="cloud-offline" size={20} color={brand.ink} />
      <T v="callout" color={brand.ink} style={{ flex: 1 }}>{`Offline. ${n ? `${n} ${n === 1 ? 'item is' : 'items are'} saved on this phone and upload` : 'Everything you do is saved on this phone and uploads'} when you have signal.`}</T>
    </Panel>
  );
}

export function OnlineChip() {
  const { online } = useField();
  return online ? <Chip tone="lime" label="Online" /> : <Chip tone="orange" icon="cloud-offline" label="Offline" />;
}

/**
 * RUL-30 on search tasks: the search result comes from Tenmina's office
 * through the registry's own channel, never from the runner or surveyor.
 */
export function SearchStrip() {
  return (
    <Panel tone="raised" style={{ flexDirection: 'row', alignItems: 'flex-start', paddingVertical: space[3] }}>
      <Ionicons name="document-lock-outline" size={20} color={brand.lime} />
      <T v="callout" color="#F7F6F2" style={{ flex: 1 }}>
        Search results come from Tenmina's office through the registry's own channel, not from you. Do not collect or photograph one for us.
      </T>
    </Panel>
  );
}

/** RUL-10 for inspectors: no link to the contractor or the client. */
export function ConflictStrip({ who }: { who?: string }) {
  return (
    <Panel tone="raised" style={{ flexDirection: 'row', alignItems: 'flex-start', paddingVertical: space[3] }}>
      <Ionicons name="shield-checkmark-outline" size={20} color={brand.lime} />
      <T v="callout" color="#F7F6F2" style={{ flex: 1 }}>
        {`You have no link to ${who ?? 'the contractor or the client'}. If that changes, tell Tenmina before you start. Your pay is the same whatever you find.`}
      </T>
    </Panel>
  );
}

/** Whether a job was finished on this phone (its submission is queued or sent). */
export function useDone(job: Job | undefined, kinds: string[]): string | undefined {
  const { ops } = useField();
  if (!job) return undefined;
  return ops.find((o) => o.subjectType === job.subject_type && o.subjectId === job.subject_id && kinds.includes(o.kind) && o.state !== 'failed')?.createdAt;
}

export const KIND_LABEL: Record<string, string> = {
  inspection: 'Inspection',
  milestone: 'Milestone evidence',
  care_visit: 'Care visit',
  case_task: 'Case task',
  task: 'Task',
  fee_runner_task: 'Collect a bill',
  errand_step: 'Errand step',
  property_inspection: 'Property inspection',
};
