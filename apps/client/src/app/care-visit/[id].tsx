import { View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import { space } from '@tenmina/tokens';
import { Button, Chip, Label, Panel, Screen, T, Tick } from '@tenmina/ui';
import { KV, LoadState, Section, clock, day, money, useGet, words, type ApiMoney } from '@tenmina/mobile';

interface CareVisit {
  id: string;
  plan: string;
  plan_reference: string;
  family_member: { full_name: string };
  carer: { name: string };
  window_start: string;
  window_end: string;
  status: string;
  check_in: { at: string; within_radius: boolean; distance_m: string } | null;
  check_out: { at: string; within_radius: boolean; distance_m: string } | null;
  late_minutes: number | null;
  items: { key: string; label: string; outcome: string; reason: string; reading: Record<string, number | string> | null; evidence: string | null }[];
  confirmation: { sent_to: string; channel: string; family_confirmed_at: string | null; confirmed_at: string | null } | null;
  needs_review_reason: string;
  fee: ApiMoney | null;
  paid_at: string | null;
}

function reading(r: Record<string, number | string> | null): string {
  if (!r) return '';
  if (r.systolic !== undefined) return `${r.systolic}/${r.diastolic} ${r.unit ?? ''}`.trim();
  return `${r.value ?? ''} ${r.unit ?? ''}`.trim();
}

/** One care visit as the client sees it (SCR-PTL-44): check-in at the address, the plan, readings, and the family's confirmation. */
export default function CareVisitScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const v = useGet<CareVisit>(`/v1/care-visits/${id}`);
  const d = v.data;
  return (
    <Screen ground="paper" back eyebrow={d?.plan_reference} title={d ? `Visit to ${d.family_member.full_name}` : 'Visit'}>
      <LoadState loading={v.loading} problem={v.problem} onRetry={v.reload} hasData={!!d} />
      {d ? (
        <>
          <View style={{ flexDirection: 'row', gap: space[2] }}>
            <Chip label={words(d.status)} tone={d.status === 'confirmed' || d.status === 'paid' ? 'lime' : 'paper'} />
          </View>
          <KV
            rows={[
              ['Carer', d.carer.name],
              ['Planned', `${day(d.window_start)}, ${clock(d.window_start)} to ${clock(d.window_end)}`],
              ['Checked in', d.check_in ? `${clock(d.check_in.at)} · ${d.check_in.within_radius ? 'at the address' : `${Math.round(Number(d.check_in.distance_m))} m away, flagged`}` : 'Not yet'],
              ['Checked out', d.check_out ? `${clock(d.check_out.at)}` : 'Not yet'],
              ['Paid', d.paid_at ? `${money(d.fee)} on ${day(d.paid_at)}` : d.fee ? `${money(d.fee)} after the family confirms` : '—'],
            ]}
          />
          <Section title="The plan">
            <Panel style={{ gap: 0, paddingVertical: space[1] }}>
              {d.items.map((i, n) => (
                <View key={i.key} style={{ flexDirection: 'row', gap: space[3], alignItems: 'center', paddingVertical: space[3], borderTopWidth: n ? 1 : 0, borderTopColor: '#ECEAE4' }}>
                  {i.outcome === 'done' ? <Tick /> : <View style={{ width: 22, height: 22, borderRadius: 7, borderWidth: 2, borderColor: '#D6D3CB' }} />}
                  <View style={{ flex: 1 }}>
                    <T v="callout">{i.label}</T>
                    <Label>{[words(i.outcome), reading(i.reading), i.reason, i.evidence ? 'photo' : ''].filter(Boolean).join(' · ')}</Label>
                  </View>
                </View>
              ))}
            </Panel>
          </Section>
          {d.confirmation ? (
            <Panel>
              <Label>Family confirmation</Label>
              <T v="callout">{d.confirmation.family_confirmed_at ? `Confirmed ${day(d.confirmation.family_confirmed_at)}.` : `A code went to ${d.confirmation.sent_to} by ${words(d.confirmation.channel)}. The carer never sees it.`}</T>
            </Panel>
          ) : null}
          {d.needs_review_reason ? (
            <Panel>
              <Label>Being checked by Tenmina</Label>
              <T v="callout">{d.needs_review_reason}</T>
            </Panel>
          ) : null}
          <Button title="Open the care plan" variant="quiet" onPress={() => router.push(`/care-plan/${d.plan}`)} />
        </>
      ) : null}
    </Screen>
  );
}
