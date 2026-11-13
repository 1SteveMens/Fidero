import { createElement, useRef, useState, type ComponentRef } from 'react';
import { ActivityIndicator, Image, Platform, Pressable, View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import { CameraView, useCameraPermissions } from 'expo-camera';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, radius, space } from '@tenmina/tokens';
import { Button, GroundContext, Input, Label, Panel, Screen, Seal, T, Tick, haptic } from '@tenmina/ui';
import { clock, shortHash } from '@tenmina/mobile';
import { makeCapture, siteCheck } from '../capture';
import { useField, useJob } from '../store';
import type { Capture as CaptureT } from '../types';

type Draft = Omit<CaptureT, 'signed' | 'state'>;

/**
 * The web preview has no camera in a test browser. Only in development, a file
 * input stands in for the shutter. Store builds have the camera only (RUL-08).
 */
const DEV_FILE_INPUT = Platform.OS === 'web' && (__DEV__ || process.env.EXPO_PUBLIC_DEV_FILE_CAPTURE === '1');

/**
 * The app's own camera (SCR-MOB-05), then "Check this capture" (SCR-MOB-06).
 * There is no gallery or file button: evidence comes only from this camera
 * (RUL-08, FR-MOB-002). The capture is fingerprinted at once and signed when kept.
 */
export default function Capture() {
  const params = useLocalSearchParams<{ subjectType: string; subjectId: string; reqKey: string; label: string; kind?: 'photo' | 'video' }>();
  const kind = params.kind === 'video' ? 'video' : 'photo';
  const insets = useSafeAreaInsets();
  const job = useJob(params.subjectType, params.subjectId);
  const { keepCapture } = useField();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [perm, requestPerm] = useCameraPermissions();
  const cam = useRef<ComponentRef<typeof CameraView>>(null);
  const [busy, setBusy] = useState(false);
  const [recording, setRecording] = useState(false);
  const [problem, setProblem] = useState<string>();

  async function finish(uri: string, blob?: Blob, mediaType?: string) {
    setBusy(true);
    try {
      setDraft(await makeCapture({ uri, kind, mediaType, blob, subjectType: params.subjectType, subjectId: params.subjectId, requirementKey: params.reqKey ?? '', job }));
    } catch {
      setProblem('The capture could not be saved. Try again.');
    }
    setBusy(false);
  }

  async function shoot() {
    if (!cam.current || busy) return;
    haptic('tap');
    if (kind === 'photo') {
      const pic = await cam.current.takePictureAsync({ quality: 0.8 });
      if (pic?.uri) await finish(pic.uri);
      return;
    }
    if (recording) {
      cam.current.stopRecording();
      return;
    }
    setRecording(true);
    // Videos are capped so they upload on a weak signal (FR-MOB-008); 60 s is the server's setting.
    const video = await cam.current.recordAsync({ maxDuration: 60 });
    setRecording(false);
    if (video?.uri) await finish(video.uri);
  }

  if (draft) {
    return (
      <Review
        draft={draft}
        label={params.label}
        onRetake={() => setDraft(null)}
        onUse={async (note) => {
          try {
            await keepCapture({ ...draft, note });
            haptic('success');
            router.back();
          } catch (e) {
            setProblem(e instanceof Error ? e.message : 'The capture could not be sealed.');
            setDraft(null);
          }
        }}
      />
    );
  }

  return (
    <GroundContext.Provider value="ink">
      <View style={{ flex: 1, backgroundColor: brand.ink }}>
        {DEV_FILE_INPUT ? (
          <View style={{ flex: 1, justifyContent: 'center', padding: space[6], gap: space[4] }}>
            <T v="title" header>Development camera</T>
            <T v="callout" muted>The web preview has no camera. This file input exists in development only; phones use the camera.</T>
            {createElement('input', {
              type: 'file',
              accept: kind === 'video' ? 'video/*' : 'image/*',
              capture: 'environment',
              'aria-label': 'Development capture',
              style: { color: '#F7F6F2', fontSize: 16 },
              onChange: (e: { target: { files?: FileList | null } }) => {
                const f = e.target.files?.[0];
                if (f) void finish(URL.createObjectURL(f), f, f.type || undefined);
              },
            })}
          </View>
        ) : perm?.granted ? (
          <CameraView ref={cam} style={{ flex: 1 }} facing="back" mode={kind === 'video' ? 'video' : 'picture'} />
        ) : (
          <View style={{ flex: 1, justifyContent: 'center', padding: space[6], gap: space[4] }}>
            <T v="title" header>Tenmina Field needs the camera</T>
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
            <Label color={brand.lime}>Camera only · sealed when kept</Label>
          </View>
        </View>

        <View style={{ position: 'absolute', left: 0, right: 0, bottom: insets.bottom + space[6], alignItems: 'center', gap: space[3] }}>
          {problem ? <T v="callout" color={brand.orange}>{problem}</T> : null}
          {busy ? <ActivityIndicator color={brand.lime} /> : null}
          {perm?.granted && !DEV_FILE_INPUT ? (
            <Pressable
              onPress={() => void shoot()}
              disabled={busy}
              accessibilityRole="button"
              accessibilityLabel={kind === 'video' ? (recording ? 'Stop recording' : 'Start recording') : 'Take the photo'}
              style={({ pressed }) => ({ width: 82, height: 82, borderRadius: 41, borderWidth: 5, borderColor: '#F7F6F2', alignItems: 'center', justifyContent: 'center', opacity: pressed ? 0.8 : 1 })}
            >
              <View style={{ width: recording ? 30 : 62, height: recording ? 30 : 62, borderRadius: recording ? 8 : 31, backgroundColor: kind === 'video' ? brand.orange : brand.lime }} />
            </Pressable>
          ) : null}
          {!DEV_FILE_INPUT ? <Label color="#F7F6F2">{busy ? 'Sealing…' : kind === 'video' ? (recording ? 'Recording · up to 60 seconds' : 'Tap to record') : 'Tap to take the photo'}</Label> : null}
        </View>
      </View>
    </GroundContext.Provider>
  );
}

/** "Check this capture" (SCR-MOB-06): where, when and the fingerprint, then keep it or retake it. */
function Review({ draft, label, onRetake, onUse }: { draft: Draft; label: string; onRetake: () => void; onUse: (note?: string) => Promise<void> }) {
  const job = useJob(draft.subjectType, draft.subjectId);
  const [why, setWhy] = useState('');
  const [busy, setBusy] = useState(false);
  const check = siteCheck(job, draft.lat !== undefined ? { lat: draft.lat, lng: draft.lng!, accuracyM: draft.accuracyM } : undefined);

  return (
    <Screen
      ground="ink"
      title="Check this capture"
      eyebrow={label}
      footer={
        <View style={{ flexDirection: 'row', gap: space[2] }}>
          <View style={{ flex: 1 }}>
            <Button title="Retake" icon="refresh" variant="dark" onPress={onRetake} />
          </View>
          <View style={{ flex: 1.4 }}>
            <Button
              title={draft.kind === 'video' ? 'Use this video' : 'Use this photo'}
              icon="checkmark"
              loading={busy}
              disabled={check.far && why.trim().length < 5}
              onPress={() => {
                setBusy(true);
                void onUse(check.far ? why.trim() : undefined).finally(() => setBusy(false));
              }}
            />
          </View>
        </View>
      }
    >
      <View style={{ borderRadius: radius.xl, overflow: 'hidden', backgroundColor: '#1A1A1A', aspectRatio: 3 / 4, maxHeight: 400, alignSelf: 'stretch' }}>
        {draft.kind === 'photo' ? (
          <Image source={{ uri: draft.uri }} style={{ flex: 1 }} resizeMode="cover" accessibilityLabel={`Photo for ${label}`} />
        ) : (
          <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', gap: space[2] }}>
            <Ionicons name="videocam" size={48} color={brand.lime} />
            <T v="callout" muted>Video saved</T>
          </View>
        )}
        <View style={{ position: 'absolute', right: space[3], top: space[3], backgroundColor: 'rgba(11,11,11,0.78)', borderRadius: 60 }}>
          <Seal id="capture-seal" ring="#A3EE5B" text="#A3EE5B" check="#A3EE5B" size={96} words="SEALED WHEN KEPT · CAMERA ONLY · " />
        </View>
      </View>

      <Panel style={{ gap: space[3] }}>
        {job ? <Label color={brand.lime}>{job.address || job.title}</Label> : null}
        <View style={{ flexDirection: 'row', gap: space[3], alignItems: 'center' }}>
          {check.far ? <Ionicons name="alert-circle" size={22} color={brand.orange} /> : <Tick />}
          <T v="callout" color={check.far ? brand.orange : undefined} style={{ flex: 1 }}>{check.text}</T>
        </View>
        <View style={{ flexDirection: 'row', gap: space[3], alignItems: 'center' }}>
          <Tick />
          <T v="callout" style={{ flex: 1 }}>{`Taken at ${clock(draft.takenAt)}, with this app`}</T>
        </View>
        <View style={{ flexDirection: 'row', gap: space[3], alignItems: 'center' }}>
          <Tick />
          <T v="callout" style={{ flex: 1 }}>{`Fingerprint ${shortHash(draft.sha256)} · ${Math.round(draft.size / 1024)} KB`}</T>
        </View>
      </Panel>

      {check.far ? <Input label="Why was this taken away from the site?" value={why} onChange={setWhy} multiline placeholder="For example: the pillar is behind the neighbour's wall" hint="Tenmina reviews it. The client sees your reason." /> : null}
    </Screen>
  );
}
