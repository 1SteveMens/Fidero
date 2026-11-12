import { useEffect, useState } from 'react';
import { Pressable, View } from 'react-native';
import Ionicons from '@expo/vector-icons/Ionicons';
import { checkoutNeedsReason, distanceMeters, distanceWarning, type FieldJob } from '@fidero/shared';
import { brand, radius, space } from '@fidero/tokens';
import { Button, Choice, ErrorView, Input, Label, Loading, Panel, Pulse, Rise, Screen, T, Tick, haptic } from '@fidero/ui';
import { currentPosition, timeOfDay, type Position } from '../capture';
import { useField, useFieldLoad } from '../store';
import { CaptureButton, OfflineBanner, Submitted } from './common';

type Phase = 'before' | 'in' | 'out';
const CONCERNS = ['Health', 'Safety', 'Welfare'] as const;

/** Care visit: check in at the address, the plan, check out (W-30, SCR-MOB-14 to 16; FR-MOB-012, FR-CARE-003, FR-CARE-006, RUL-23). */
export function VisitScreen({ job }: { job: FieldJob }) {
  const { capturesFor, submitJob, raiseConcern, submitted, online } = useField();
  const { data: visit, error, reload } = useFieldLoad((api) => api.getVisit(job.id), `visit-${job.id}`);
  const [phase, setPhase] = useState<Phase>('before');
  const [pos, setPos] = useState<Position>();
  const [locating, setLocating] = useState(true);
  const [whyFar, setWhyFar] = useState('');
  const [checkedInAt, setCheckedInAt] = useState<string>();
  const [checkedOutAt, setCheckedOutAt] = useState<string>();
  const [done, setDone] = useState<Record<string, boolean>>({});
  const [whyLeft, setWhyLeft] = useState('');
  const [concern, setConcern] = useState<(typeof CONCERNS)[number]>();
  const [concernNote, setConcernNote] = useState('');
  const [concernSent, setConcernSent] = useState(false);

  const locate = async () => {
    setLocating(true);
    setPos(await currentPosition());
    setLocating(false);
  };
  useEffect(() => {
    void locate();
  }, []);

  if (submitted[job.id]) {
    return <Submitted title="Visit finished." detail="We have sent the family a link and a code on their own phone. You are paid for this visit after the family confirms it." />;
  }
  if (error) return <Screen ground="ink" back><ErrorView message={error} onRetry={reload} /></Screen>;
  if (!visit) return <Screen ground="ink" back><Loading /></Screen>;

  const distance = pos ? distanceMeters(pos, job.site.location) : undefined;
  const far = distanceWarning(distance, job.site);
  const left = checkoutNeedsReason(visit.plan, done);

  const concernPanel = (
    <Panel style={{ gap: space[2], borderWidth: 2, borderColor: '#3A3A3A', backgroundColor: 'transparent' }}>
      <Label color={brand.orange}>Raise a concern</Label>
      {concernSent ? (
        <T v="callout">Sent to the family and a Fidero reviewer. They will contact you today.</T>
      ) : (
        <>
          <View style={{ flexDirection: 'row', gap: space[2] }}>
            {CONCERNS.map((c) => (
              <Pressable
                key={c}
                onPress={() => {
                  haptic('tap');
                  setConcern(c);
                }}
                accessibilityRole="radio"
                accessibilityState={{ selected: concern === c }}
                style={{ flex: 1, height: 42, borderRadius: 12, alignItems: 'center', justifyContent: 'center', backgroundColor: concern === c ? brand.orange : '#242424' }}
              >
                <T v="headline" color={concern === c ? brand.ink : '#F7F6F2'} style={{ fontSize: 14 }}>{c}</T>
              </Pressable>
            ))}
          </View>
          {concern ? (
            <>
              <Input label="What happened?" value={concernNote} onChange={setConcernNote} multiline />
              <Button
                title="Send the concern"
                variant="dark"
                disabled={concernNote.trim().length < 5}
                onPress={() => {
                  raiseConcern(job.id, `${concern} concern: ${visit.person}`);
                  setConcernSent(true);
                }}
              />
            </>
          ) : null}
        </>
      )}
    </Panel>
  );

  if (phase === 'before') {
    return (
      <Screen
        ground="ink"
        back
        title={visit.person}
        eyebrow={`Care visit · ${job.startsAt} to ${job.endsAt ?? ''}`}
        footer={
          <Button
            title={far ? 'Check in · say why first' : 'Check in'}
            icon="locate"
            disabled={locating || (!!far && whyFar.trim().length < 5)}
            onPress={() => {
              setCheckedInAt(new Date().toISOString());
              setPhase('in');
            }}
          />
        }
      >
        {!online ? <OfflineBanner /> : null}
        <T v="callout" muted>{job.site.address}</T>
        <Rise>
          <View style={{ height: 200, borderRadius: radius.xl, backgroundColor: '#1A1A1A', overflow: 'hidden', alignItems: 'center', justifyContent: 'center', gap: space[3] }}>
            <View style={{ position: 'absolute', left: 40, right: 40, top: 96, height: 10, borderRadius: 5, backgroundColor: '#2C2C2C' }} />
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 60 }}>
              <Pulse size={22} radius={11} />
              <View style={{ alignItems: 'center' }}>
                <Ionicons name="home-outline" size={30} color={brand.lime} />
                <Label color={brand.lime} style={{ fontSize: 9 }}>Address</Label>
              </View>
            </View>
            <View style={{ position: 'absolute', left: space[3], bottom: space[3], flexDirection: 'row', alignItems: 'center', gap: space[2], backgroundColor: brand.ink, borderRadius: 12, paddingHorizontal: space[3], paddingVertical: space[2] }}>
              <Ionicons name="locate" size={16} color={far ? brand.orange : brand.lime} />
              <T v="headline" color={far ? brand.orange : '#F7F6F2'} style={{ fontSize: 14 }}>
                {locating ? 'Finding your position…' : far ?? `${Math.round(distance ?? 0)} m from the address`}
              </T>
            </View>
          </View>
        </Rise>
        <Button title="Check my position again" variant="quiet" icon="refresh" onPress={() => void locate()} />
        {far && !locating ? <Input label="Why are you checking in from here?" value={whyFar} onChange={setWhyFar} multiline hint="The visit is flagged for review, and the family sees your reason." /> : null}
        <Panel style={{ gap: 0, paddingVertical: space[1] }}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', paddingVertical: space[3] }}>
            <T v="callout" muted>Plan</T>
            <T v="callout">{`${visit.plan.length} items · ${visit.plan.filter((p) => p.needsPhoto).length} with photos`}</T>
          </View>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', paddingVertical: space[3], borderTopWidth: 1, borderTopColor: '#2C2C2C' }}>
            <T v="callout" muted>After the visit</T>
            <T v="callout">The family confirms</T>
          </View>
        </Panel>
        {concernPanel}
      </Screen>
    );
  }

  if (phase === 'in') {
    return (
      <Screen
        ground="ink"
        back
        title={visit.person}
        eyebrow={`Checked in ${checkedInAt ? timeOfDay(checkedInAt) : ''}${far ? ' · away from the address' : ' · at the address'}`}
        footer={
          <Button
            title={left > 0 ? `Check out · ${left} ${left === 1 ? 'item' : 'items'} left` : 'Check out'}
            disabled={left > 0 && whyLeft.trim().length < 5}
            onPress={() => {
              setCheckedOutAt(new Date().toISOString());
              setPhase('out');
            }}
          />
        }
      >
        <Label>{`Plan · ${visit.plan.length - left} of ${visit.plan.length} done`}</Label>
        <Panel style={{ gap: 0, paddingVertical: space[1] }}>
          {visit.plan.map((item, i) => {
            const photos = capturesFor(job.id, item.id).length;
            const canTick = !item.needsPhoto || photos > 0;
            return (
              <View key={item.id} style={{ flexDirection: 'row', alignItems: 'center', gap: space[3], paddingVertical: space[3], borderBottomWidth: i < visit.plan.length - 1 ? 1 : 0, borderBottomColor: '#2C2C2C' }}>
                <Pressable
                  onPress={() => {
                    if (!canTick) return;
                    haptic('tap');
                    setDone((d) => ({ ...d, [item.id]: !d[item.id] }));
                  }}
                  accessibilityRole="checkbox"
                  accessibilityState={{ checked: !!done[item.id], disabled: !canTick }}
                  accessibilityLabel={item.text}
                  hitSlop={8}
                >
                  {done[item.id] ? <Tick size={26} /> : <View style={{ width: 26, height: 26, borderRadius: 8, borderWidth: 2, borderColor: canTick ? '#A9A69E' : '#3A3A3A' }} />}
                </Pressable>
                <View style={{ flex: 1 }}>
                  <T v="callout">{item.text}</T>
                  {item.needsPhoto && photos === 0 ? <Label>Photo first</Label> : null}
                </View>
                {item.needsPhoto ? <CaptureButton jobId={job.id} itemId={item.id} label={item.text} count={photos} compact /> : null}
              </View>
            );
          })}
        </Panel>
        {left > 0 ? <Input label="Items left: say why" value={whyLeft} onChange={setWhyLeft} placeholder="For example: she was asleep" hint="The family sees this." /> : null}
        {concernPanel}
      </Screen>
    );
  }

  const minutes = checkedInAt && checkedOutAt ? Math.max(1, Math.round((Date.parse(checkedOutAt) - Date.parse(checkedInAt)) / 60000)) : 0;
  return (
    <Screen
      ground="ink"
      back
      title={`Check out · ${checkedOutAt ? timeOfDay(checkedOutAt) : ''}`}
      footer={<Button title="Finish" onPress={() => submitJob(job.id, `Care visit: ${visit.person}`)} />}
    >
      <Panel style={{ gap: space[3] }}>
        <T v="headline">{`Visit lasted ${minutes} ${minutes === 1 ? 'minute' : 'minutes'}.`}</T>
        <T v="callout" muted>We will send the family a link and a code on their own phone. They confirm by tapping it, replying, or by phone. You are paid after the family confirms.</T>
      </Panel>
      {!online ? <OfflineBanner /> : null}
    </Screen>
  );
}
