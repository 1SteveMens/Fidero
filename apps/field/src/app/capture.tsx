import { useRef, useState, type ComponentRef } from 'react';
import { ActivityIndicator, Image, Pressable, View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import { CameraView, useCameraPermissions } from 'expo-camera';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Ionicons from '@expo/vector-icons/Ionicons';
import { distanceWarning, type Capture as CaptureT, type FieldJob } from '@fidero/shared';
import { brand, radius, space } from '@fidero/tokens';
import { Button, GroundContext, Input, Label, Panel, Screen, Seal, T, Tick, haptic } from '@fidero/ui';
import { makeCapture, shortHash, timeOfDay } from '../capture';
import { useField, useFieldLoad } from '../store';

/**
 * The app's own camera (SCR-MOB-05), then "Check this photo" (SCR-MOB-06) on the same screen. There is no gallery or file button anywhere:
 * evidence comes only from this camera (RUL-08, FR-MOB-002).
 */
export default function Capture() {
  const params = useLocalSearchParams<{ jobId: string; itemId: string; label: string; kind?: 'photo' | 'video' }>();
  const kind = params.kind === 'video' ? 'video' : 'photo';
  const insets = useSafeAreaInsets();
  const { keepCapture } = useField();
  const [draft, setDraft] = useState<CaptureT | null>(null);
  const { data: job } = useFieldLoad((api) => api.getJob(params.jobId), `job-${params.jobId}`);
  const [perm, requestPerm] = useCameraPermissions();
  const cam = useRef<ComponentRef<typeof CameraView>>(null);
  const [busy, setBusy] = useState(false);
  const [recording, setRecording] = useState(false);
  const [problem, setProblem] = useState<string>();

  async function finish(uri: string) {
    if (!job) return;
    setBusy(true);
    try {
      const c = await makeCapture({ uri, kind, jobId: params.jobId, itemId: params.itemId, site: job.site });
      setDraft(c);
    } catch {
      setProblem('The capture could not be saved. Try again.');
    }
    setBusy(false);
  }

  async function shoot() {
    if (!cam.current || busy || !job) return;
    haptic('tap');
    if (kind === 'photo') {
      const pic = await cam.current.takePictureAsync({ quality: 0.7 });
      if (pic?.uri) await finish(pic.uri);
      return;
    }
    if (recording) {
      cam.current.stopRecording();
      return;
    }
    setRecording(true);
    // Videos are capped so they upload on a weak signal (FR-MOB-008); the cap is a working assumption.
    const video = await cam.current.recordAsync({ maxDuration: 30 });
    setRecording(false);
    if (video?.uri) await finish(video.uri);
  }

  if (draft && job) {
    return (
      <Review
        draft={draft}
        job={job}
        label={params.label}
        onRetake={() => setDraft(null)}
        onUse={(note) => {
          keepCapture({ ...draft, note }, `${params.label} · ${draft.kind}`);
          router.back();
        }}
      />
    );
  }

  return (
    <GroundContext.Provider value="ink">
      <View style={{ flex: 1, backgroundColor: brand.ink }}>
        {perm?.granted ? (
          <CameraView ref={cam} style={{ flex: 1 }} facing="back" mode={kind === 'video' ? 'video' : 'picture'} />
        ) : (
          <View style={{ flex: 1, justifyContent: 'center', padding: space[6], gap: space[4] }}>
            <T v="title" header>Fidero Field needs the camera</T>
            <T v="callout" muted>Evidence comes only from this app's camera, never from your gallery, so the client can trust where and when it was taken.</T>
            <Button title="Allow the camera" icon="camera" onPress={() => void requestPerm()} />
          </View>
        )}

        <View style={{ position: 'absolute', top: insets.top + space[2], left: space[4], right: space[4], flexDirection: 'row', alignItems: 'center', gap: space[3] }}>
          <Pressable onPress={() => router.back()} accessibilityRole="button" accessibilityLabel="Close the camera" style={{ width: 44, height: 44, borderRadius: 14, backgroundColor: 'rgba(11,11,11,0.75)', alignItems: 'center', justifyContent: 'center' }}>
            <Ionicons name="close" size={22} color="#F7F6F2" />
          </Pressable>
          <View style={{ flex: 1, backgroundColor: 'rgba(11,11,11,0.75)', borderRadius: 14, paddingHorizontal: space[3], paddingVertical: space[2] }}>
            <T v="headline" color="#F7F6F2" style={{ fontSize: 15 }} numberOfLines={1}>{params.label}</T>
            <Label color={brand.lime}>Camera only · sealed when taken</Label>
          </View>
        </View>

        <View style={{ position: 'absolute', left: 0, right: 0, bottom: insets.bottom + space[6], alignItems: 'center', gap: space[3] }}>
          {problem ? <T v="callout" color={brand.orange}>{problem}</T> : null}
          {perm?.granted ? (
            <Pressable
              onPress={() => void shoot()}
              disabled={busy || !job}
              accessibilityRole="button"
              accessibilityLabel={kind === 'video' ? (recording ? 'Stop recording' : 'Start recording') : 'Take the photo'}
              style={({ pressed }) => ({ width: 82, height: 82, borderRadius: 41, borderWidth: 5, borderColor: '#F7F6F2', alignItems: 'center', justifyContent: 'center', opacity: pressed ? 0.8 : 1 })}
            >
              {busy ? (
                <ActivityIndicator color={brand.lime} />
              ) : (
                <View style={{ width: recording ? 30 : 62, height: recording ? 30 : 62, borderRadius: recording ? 8 : 31, backgroundColor: kind === 'video' ? brand.orange : brand.lime }} />
              )}
            </Pressable>
          ) : null}
          <Label color="#F7F6F2">{busy ? 'Sealing…' : kind === 'video' ? (recording ? 'Recording · up to 30 seconds' : 'Tap to record') : 'Tap to take the photo'}</Label>
        </View>
      </View>
    </GroundContext.Provider>
  );
}

/** "Check this photo" (SCR-MOB-06): where, when and the fingerprint, then use it or retake it. */
function Review({ draft, job, label, onRetake, onUse }: { draft: CaptureT; job: FieldJob; label: string; onRetake: () => void; onUse: (note?: string) => void }) {
  const [why, setWhy] = useState('');

  const warning = distanceWarning(draft.distanceM, job.site);
  const where = warning ?? `On site, ${Math.round(draft.distanceM ?? 0)} m from ${job.site.name}`;

  const retake = onRetake;
  const use = () => onUse(warning ? why.trim() : undefined);

  return (
    <Screen
      ground="ink"
      title="Check this photo"
      eyebrow={label}
      footer={
        <View style={{ flexDirection: 'row', gap: space[2] }}>
          <View style={{ flex: 1 }}>
            <Button title="Retake" icon="refresh" variant="dark" onPress={retake} />
          </View>
          <View style={{ flex: 1.4 }}>
            <Button title={draft.kind === 'video' ? 'Use this video' : 'Use this photo'} icon="checkmark" disabled={!!warning && why.trim().length < 5} onPress={use} />
          </View>
        </View>
      }
    >
      <View style={{ borderRadius: radius.xl, overflow: 'hidden', backgroundColor: '#1A1A1A', aspectRatio: 3 / 4, maxHeight: 420, alignSelf: 'stretch' }}>
        {draft.kind === 'photo' ? (
          <Image source={{ uri: draft.uri }} style={{ flex: 1 }} resizeMode="cover" accessibilityLabel={`Photo for ${label}`} />
        ) : (
          <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', gap: space[2] }}>
            <Ionicons name="videocam" size={48} color={brand.lime} />
            <T v="callout" muted>Video saved</T>
          </View>
        )}
        <View style={{ position: 'absolute', right: space[3], top: space[3], backgroundColor: 'rgba(11,11,11,0.78)', borderRadius: 60 }}>
          <Seal id="capture-seal" ring="#A3EE5B" text="#A3EE5B" check="#A3EE5B" size={100} words="SEALED WHEN TAKEN · CAMERA ONLY · " />
        </View>
      </View>

      <Panel style={{ gap: space[3] }}>
        <Label color={brand.lime}>{job.site.name}</Label>
        <View style={{ flexDirection: 'row', gap: space[3], alignItems: 'center' }}>
          {warning ? <Ionicons name="alert-circle" size={22} color={brand.orange} /> : <Tick />}
          <T v="callout" color={warning ? brand.orange : undefined} style={{ flex: 1 }}>{where}</T>
        </View>
        <View style={{ flexDirection: 'row', gap: space[3], alignItems: 'center' }}>
          <Tick />
          <T v="callout" style={{ flex: 1 }}>{`Taken at ${timeOfDay(draft.takenAt)}, with this app`}</T>
        </View>
        <View style={{ flexDirection: 'row', gap: space[3], alignItems: 'center' }}>
          <Tick />
          <T v="callout" style={{ flex: 1 }}>{`Fingerprint ${shortHash(draft.sha256)}`}</T>
        </View>
      </Panel>

      {warning ? <Input label="Why was this taken away from the site?" value={why} onChange={setWhy} multiline placeholder="For example: the pillar is behind the neighbour's wall" /> : null}
    </Screen>
  );
}
