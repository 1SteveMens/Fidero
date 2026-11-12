import { Pressable, View } from 'react-native';
import { router } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, radius, space } from '@fidero/tokens';
import { Button, Panel, Screen, T, haptic, usePalette } from '@fidero/ui';

/** Opens the app's camera for one evidence item. */
export function CaptureButton({ jobId, itemId, label, kind = 'photo', count, compact }: { jobId: string; itemId: string; label: string; kind?: 'photo' | 'video'; count: number; compact?: boolean }) {
  const p = usePalette();
  const icon = kind === 'video' ? 'videocam-outline' : 'camera-outline';
  return (
    <Pressable
      onPress={() => {
        haptic('tap');
        router.push({ pathname: '/capture', params: { jobId, itemId, label, kind } });
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
    <Screen ground={ground} footer={<Button title="Back to my jobs" onPress={() => router.back()} />}>
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

export function OfflineBanner() {
  return (
    <Panel tone="orange" style={{ flexDirection: 'row', alignItems: 'center', borderRadius: radius.md + 2, paddingVertical: space[3] }}>
      <Ionicons name="cloud-offline" size={20} color={brand.ink} />
      <T v="callout" color={brand.ink} style={{ flex: 1 }}>Offline. Everything is saved on this phone and uploads when you have signal.</T>
    </Panel>
  );
}
