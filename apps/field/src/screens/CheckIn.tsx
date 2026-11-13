import { useEffect, useState } from 'react';
import { View } from 'react-native';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, radius, space } from '@tenmina/tokens';
import { Button, Input, Label, Panel, Pulse, T, Tick } from '@tenmina/ui';
import { clock } from '@tenmina/mobile';
import { currentPosition, siteCheck, type Position } from '../capture';
import { useField } from '../store';
import type { Job } from '../types';

/**
 * Check in or out at the registered address (FR-MOB-012). The position is
 * signed with the time. Far away is recorded and flagged for review, never
 * blocked, and the person says why.
 */
export function CheckCard({ job, kind, done, onDone }: { job: Job; kind: 'checkin' | 'checkout'; done?: string; onDone: (at: string, why?: string) => void }) {
  const { signedCheck } = useField();
  const [pos, setPos] = useState<Position>();
  const [locating, setLocating] = useState(true);
  const [why, setWhy] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string>();

  async function locate() {
    setLocating(true);
    setPos(await currentPosition());
    setLocating(false);
  }
  useEffect(() => {
    if (!done) void locate();
  }, [done]);

  if (done) {
    return (
      <Panel style={{ flexDirection: 'row', alignItems: 'center' }}>
        <Tick />
        <T v="callout" style={{ flex: 1 }}>{`${kind === 'checkin' ? 'Checked in' : 'Checked out'} at ${clock(done)}. Signed on this phone.`}</T>
      </Panel>
    );
  }
  const check = siteCheck(job, pos);
  return (
    <Panel style={{ gap: space[3] }}>
      <View style={{ height: 140, borderRadius: radius.lg, backgroundColor: '#1A1A1A', overflow: 'hidden', alignItems: 'center', justifyContent: 'center' }}>
        <View style={{ position: 'absolute', left: 40, right: 40, top: 64, height: 8, borderRadius: 4, backgroundColor: '#2C2C2C' }} />
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 60 }}>
          <Pulse size={20} radius={10} color={check.far ? brand.orange : brand.lime} />
          <View style={{ alignItems: 'center' }}>
            <Ionicons name="home-outline" size={28} color={brand.lime} />
            <Label color={brand.lime} style={{ fontSize: 9 }}>Address</Label>
          </View>
        </View>
        <View style={{ position: 'absolute', left: space[3], bottom: space[3], right: space[3], flexDirection: 'row', alignItems: 'center', gap: space[2], backgroundColor: brand.ink, borderRadius: 12, paddingHorizontal: space[3], paddingVertical: space[2] }}>
          <Ionicons name="locate" size={16} color={check.far ? brand.orange : brand.lime} />
          <T v="headline" color={check.far ? brand.orange : '#F7F6F2'} style={{ fontSize: 14, flex: 1 }}>{locating ? 'Finding your position…' : check.text}</T>
        </View>
      </View>
      <Button title="Check my position again" variant="quiet" icon="refresh" onPress={() => void locate()} />
      {!pos && !locating ? <T v="callout" muted>Turn on location for Tenmina Field. A check-in needs your position.</T> : null}
      {check.far && pos && !locating ? <Input label={`Why are you ${kind === 'checkin' ? 'checking in' : 'checking out'} from here?`} value={why} onChange={setWhy} multiline hint="It is flagged for review. The family or client sees your reason." /> : null}
      {err ? <T v="callout" color={brand.orange}>{err}</T> : null}
      <Button
        title={kind === 'checkin' ? 'Check in' : 'Check out'}
        icon="locate"
        loading={busy}
        disabled={locating || !pos || (check.far && why.trim().length < 5)}
        onPress={() => {
          if (!pos) return;
          setBusy(true);
          setErr(undefined);
          void signedCheck(kind, job.subject_type, job.subject_id, pos)
            .then((op) => onDone(op.createdAt, check.far ? why.trim() : undefined))
            .catch((e: unknown) => setErr(e instanceof Error ? e.message : 'Could not sign the check-in.'))
            .finally(() => setBusy(false));
        }}
      />
    </Panel>
  );
}
