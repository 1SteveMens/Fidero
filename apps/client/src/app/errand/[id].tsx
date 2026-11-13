import { Linking, View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import { brand, space } from '@tenmina/tokens';
import { Button, Chip, DotStepper, Label, Panel, Screen, T, Tick } from '@tenmina/ui';
import { LoadState, ProblemBox, Section, day, money, portalUrl, useAction, useGet, words, type ApiMoney } from '@tenmina/mobile';

interface Errand {
  id: string;
  reference: string;
  status: string;
  status_text: string;
  blocking_reasons: { rule: string; code: string; message: string; key?: string }[];
  name: string;
  official_fees: ApiMoney;
  tenmina_charge: ApiMoney;
  fee_order_id: string | null;
  fee_paid_at: string | null;
  agent: { name?: string } | string | null;
  due_on: string | null;
  documents: { key: string; label: string; required: boolean; status: string; reject_reason: string }[];
  steps: { id: string; seq: number; key: string; description: string; official_fee: ApiMoney; status: string; plain: string; release_instruction_id: string | null; done_at: string | null }[];
  result_uploaded_at: string | null;
  result_checked_at: string | null;
  handover: { method: string; status?: string; confirmed_at?: string | null } | null;
  handed_over_at: string | null;
}

/**
 * Errand progress (SCR-PTL-50, W-34; FR-TSK-002 to FR-TSK-005): the steps,
 * the documents Tenmina needs, each official fee paid straight to the agency,
 * and the handover. The agent never handles the money.
 */
export default function ErrandScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const e = useGet<Errand>(`/v1/errands/${id}`);
  const act = useAction();
  const d = e.data;
  const done = d?.steps.filter((s) => s.status === 'done').length ?? 0;
  const waitingApproval = d?.steps.find((s) => s.release_instruction_id && s.status !== 'done' && !s.done_at);

  async function confirmHandover() {
    const r = await act.run('POST', `/v1/errands/${id}/handover-confirmations`);
    if (r) e.reload();
  }

  return (
    <Screen ground="paper" back eyebrow={d ? `${d.reference}${d.due_on ? ` · due ${day(d.due_on)}` : ''}` : 'Errand'} title={d?.name}>
      <LoadState loading={e.loading} problem={e.problem} onRetry={e.reload} hasData={!!d} />
      {d ? (
        <>
          <Chip label={words(d.status)} tone={d.status === 'completed' ? 'lime' : 'paper'} />
          <T v="callout">{d.status_text}</T>
          {d.steps.length ? (
            <Panel>
              <DotStepper labels={d.steps.map((s) => s.key.slice(0, 8).toUpperCase())} done={done} />
            </Panel>
          ) : null}

          {d.fee_order_id && !d.fee_paid_at ? (
            <Panel tone="orange" onPress={() => router.push(`/pay-fee/${d.fee_order_id}`)}>
              <Label color={brand.ink}>Needs you</Label>
              <T v="headline" color={brand.ink}>{`Pay Tenmina's charge, ${money(d.tenmina_charge)}`}</T>
            </Panel>
          ) : null}
          {waitingApproval?.release_instruction_id ? (
            <Panel tone="orange" onPress={() => router.push(`/release/${waitingApproval.release_instruction_id}`)}>
              <Label color={brand.ink}>Needs you</Label>
              <T v="headline" color={brand.ink}>{`Approve the official fee for step ${waitingApproval.seq}`}</T>
              <T v="footnote" color="#3A1408">{`${money(waitingApproval.official_fee)}, paid straight to the agency.`}</T>
            </Panel>
          ) : null}
          {d.handover && !d.handover.confirmed_at && d.status === 'handed_over' ? (
            <Panel tone="orange">
              <Label color={brand.ink}>Needs you</Label>
              <T v="headline" color={brand.ink}>Confirm you received the document</T>
              <Button title="I have it" variant="dark" loading={act.busy} onPress={() => void confirmHandover()} />
            </Panel>
          ) : null}
          <ProblemBox problem={act.problem} />

          <Section title="Steps">
            <Panel style={{ gap: 0, paddingVertical: space[1] }}>
              {d.steps.map((s, i) => (
                <View key={s.id} style={{ flexDirection: 'row', gap: space[3], alignItems: 'center', paddingVertical: space[3], borderTopWidth: i ? 1 : 0, borderTopColor: '#ECEAE4' }}>
                  {s.status === 'done' ? <Tick /> : <View style={{ width: 22, height: 22, borderRadius: 7, borderWidth: 2, borderColor: '#D6D3CB' }} />}
                  <View style={{ flex: 1 }}>
                    <T v="callout">{`${s.seq}. ${s.description}`}</T>
                    <Label>{`${s.plain}${Number(s.official_fee.amount) > 0 ? ` · official fee ${money(s.official_fee)}` : ''}`}</Label>
                  </View>
                </View>
              ))}
            </Panel>
          </Section>

          {d.documents.length ? (
            <Section title="Documents">
              <Panel style={{ gap: 0, paddingVertical: space[1] }}>
                {d.documents.map((doc, i) => (
                  <View key={doc.key} style={{ paddingVertical: space[3], borderTopWidth: i ? 1 : 0, borderTopColor: '#ECEAE4', gap: 2 }}>
                    <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[2] }}>
                      <T v="callout" style={{ flex: 1 }}>{doc.label}</T>
                      <Chip label={words(doc.status)} tone={doc.status === 'accepted' ? 'lime' : doc.status === 'rejected' ? 'orange' : 'paper'} />
                    </View>
                    {doc.reject_reason ? <T v="footnote">{doc.reject_reason}</T> : null}
                  </View>
                ))}
              </Panel>
              {d.documents.some((doc) => doc.status === 'rejected' || doc.status === 'missing' || doc.status === 'pending') ? (
                <Button title="Send documents on the website" variant="dark" icon="open-outline" onPress={() => void Linking.openURL(`${portalUrl()}/errands/${id}`)} />
              ) : null}
            </Section>
          ) : null}
        </>
      ) : null}
    </Screen>
  );
}
