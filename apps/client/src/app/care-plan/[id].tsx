import { useState } from 'react';
import { View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import { brand, holdToApproveMs, space } from '@tenmina/tokens';
import { Button, Chip, CodeField, HoldButton, Label, ListRow, Panel, Screen, T, useScreenReader } from '@tenmina/ui';
import { KV, LoadState, ProblemBox, Section, day, itemsOf, money, stepUp, useAction, useApi, useGet, useLoad, useSession, when, words, type ApiMoney, type Problem } from '@tenmina/mobile';

interface CarePlan {
  id: string;
  reference: string;
  status: string;
  status_reason: string;
  family_member: { id: string; full_name: string; relationship: string };
  address: string;
  schedule: { weekly?: string[]; window?: string };
  visit_fee: ApiMoney;
  confirmers: { id: string; full_name: string }[];
  confirm_channel: string;
  carer: { id: string; name: string; status: string; pay_route: string } | null;
  escrow: string | null;
  fee_order_id: string | null;
  fee_paid_at: string | null;
  terms_accepted_at: string | null;
  notes: string;
  items: { id: string; key: string; label: string; photo_required: boolean; reading_required: boolean; reading_kind: string }[];
  next_visit_at: string | null;
  needs_client: string | null;
}

interface Visit {
  id: string;
  window_start: string;
  status: string;
  items_done: number;
  items: unknown[];
}

/**
 * Care plan, visits and alerts (SCR-PTL-43, SCR-PTL-44; W-29): who visits, what
 * they do, who confirms, and each visit's state. Starting the plan accepts the
 * terms and agrees the carer as payee, with the authenticator code (RUL-28).
 */
export default function CarePlanScreen() {
  const api = useApi();
  const { me } = useSession();
  const screenReader = useScreenReader();
  const { id } = useLocalSearchParams<{ id: string }>();
  const plan = useGet<CarePlan>(`/v1/care-plans/${id}`);
  const visits = useGet<{ items: (Visit & { plan: string })[] }>('/v1/care-visits');
  const terms = useLoad((a) => a.get<{ terms: { title: string; text: string }; terms_version: string; scope_version: string }>('/v1/catalogue/terms'), 'terms');
  const act = useAction();
  const [code, setCode] = useState('');
  const [problem, setProblem] = useState<Problem>();
  const d = plan.data;
  const mine = itemsOf(visits.data).filter((v) => v.plan === id);

  async function activate() {
    setProblem(undefined);
    const p = await stepUp(api, code);
    if (p) {
      setProblem(p);
      return;
    }
    const r = await act.run('POST', `/v1/care-plans/${id}/activate`, { terms_version: terms.data?.terms_version, scope_version: terms.data?.scope_version });
    if (r) plan.reload();
  }

  return (
    <Screen ground="paper" back eyebrow={d?.reference} title={d ? `Care for ${d.family_member.full_name}` : 'Care plan'}>
      <LoadState loading={plan.loading} problem={plan.problem} onRetry={plan.reload} hasData={!!d} />
      {d ? (
        <>
          <View style={{ flexDirection: 'row', gap: space[2], flexWrap: 'wrap' }}>
            <Chip label={words(d.status)} tone={d.status === 'active' ? 'lime' : 'paper'} />
            <Chip label={`${money(d.visit_fee)} a visit`} tone="surface" />
          </View>

          {d.needs_client === 'activate' ? (
            <Panel tone="raised">
              <Label color={brand.orange}>Needs you · start the plan</Label>
              <T v="headline" color="#F7F6F2">{`${d.carer?.name ?? 'The carer'} is ready to visit.`}</T>
              <T v="footnote" color="#A9A69E">
                {`Accepting starts the visits. Each visit is paid ${money(d.visit_fee)} from your money held at the bank, only after the family confirms it.`}
              </T>
              {terms.data ? <T v="footnote" color="#A9A69E">{`${terms.data.terms.title}: ${terms.data.terms.text}`}</T> : null}
              {me?.mfa_enabled ? (
                <>
                  <CodeField label="Code from your authenticator app" value={code} onChange={setCode} />
                  <HoldButton label="Start the plan" holdMs={holdToApproveMs} screenReader={screenReader} disabled={code.length < 6 || !terms.data} loading={act.busy} onConfirm={() => void activate()} />
                </>
              ) : (
                <Button title="Set up the authenticator first" variant="primary" onPress={() => router.push('/account/security')} />
              )}
              <ProblemBox problem={problem ?? act.problem} />
            </Panel>
          ) : null}
          {d.fee_order_id && !d.fee_paid_at && d.status === 'active' ? (
            <Panel tone="orange" onPress={() => router.push(`/pay-fee/${d.fee_order_id}`)}>
              <Label color={brand.ink}>Needs you</Label>
              <T v="headline" color={brand.ink}>Pay Tenmina's fee for the plan</T>
            </Panel>
          ) : null}

          <KV
            rows={[
              ['Carer', d.carer ? `${d.carer.name} · ${words(d.carer.status)}` : 'Not assigned yet'],
              ['Where', d.address],
              ['When', `${(d.schedule.weekly ?? []).map((x) => x.toUpperCase()).join(', ')} ${d.schedule.window ?? ''}`.trim() || '—'],
              ['Confirms', `${d.confirmers.map((c) => c.full_name).join(', ') || '—'} by ${words(d.confirm_channel)}`],
              ['Next visit', when(d.next_visit_at)],
            ]}
          />

          <Section title="What the carer does">
            <Panel style={{ gap: 0, paddingVertical: space[1] }}>
              {d.items.map((i, n) => (
                <ListRow key={i.id} icon="checkbox-outline" iconTone="surface" title={i.label} detail={[i.photo_required ? 'Photo' : '', i.reading_required ? `${words(i.reading_kind)} reading` : ''].filter(Boolean).join(' · ') || undefined} last={n === d.items.length - 1} />
              ))}
            </Panel>
          </Section>

          <Section title={`Visits · ${mine.length}`}>
            {mine.length ? (
              <Panel style={{ gap: 0, paddingVertical: space[1] }}>
                {mine.slice(0, 12).map((v, n) => (
                  <ListRow key={v.id} icon="heart-outline" iconTone={v.status === 'confirmed' ? 'lime' : 'ink'} title={day(v.window_start)} detail={`${words(v.status)} · ${v.items_done} of ${v.items.length} done`} onPress={() => router.push(`/care-visit/${v.id}`)} last={n === Math.min(mine.length, 12) - 1} />
                ))}
              </Panel>
            ) : (
              <T v="callout" muted>No visits yet.</T>
            )}
          </Section>
        </>
      ) : null}
    </Screen>
  );
}
