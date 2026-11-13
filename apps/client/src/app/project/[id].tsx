import { ScrollView, View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import { brand, space } from '@tenmina/tokens';
import { Button, Chip, Label, Panel, Screen, SegBar, T, Tick } from '@tenmina/ui';
import { LoadState, Section, day, itemsOf, money, useLoad, words, type ApiMoney } from '@tenmina/mobile';
import { ActionRow, Figures } from '../../components/rows';
import { EvidenceThumb } from '../../components/EvidenceThumb';
import type { Instruction } from '../../lib';

interface Dashboard {
  project_id: string;
  title: string;
  type: string;
  status: string;
  route: string;
  budget: ApiMoney;
  variations_agreed: ApiMoney | null;
  paid: ApiMoney;
  remaining: ApiMoney;
  defect_value_held: ApiMoney | null;
  retention_held: ApiMoney | null;
  held_at_bank: ApiMoney | null;
  defects_period_ends_on: string | null;
  contractor: string | null;
  inspector: string | null;
  milestones: { id: string; seq: number; key: string; name: string; status: string; amount: ApiMoney; paid: ApiMoney; needs_client: boolean }[];
  inspections: { id: string; milestone: string; status: string; scheduled_for: string | null; outcome: string | null; inspector: string; defect_value: ApiMoney | null; defects: { id: string; description: string }[] }[];
  payments: { id: string; label: string; status: string; amount: ApiMoney; payee: string; paid_at: string | null }[];
  photo_timeline: { evidence_id: string; kind: string; milestone: string; captured_at: string; app_captured: boolean }[];
}

interface Project {
  id: string;
  type: string;
  title: string;
  escrow_id: string | null;
  start_blockers: { message: string }[] | string[];
}

const OUTCOME: Record<string, string> = { pass: 'Passed', pass_with_defects: 'Passed with defects', fail: 'Failed' };

/**
 * Build dashboard and project fund (SCR-PTL-22, SCR-PTL-30; W-19, W-20): each
 * milestone, its inspection and payment, money held and paid, and the photo
 * timeline taken in Tenmina Field. A milestone is paid only after it passes.
 */
export default function ProjectScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const data = useLoad(async (a) => {
    const [dash, project, waiting] = await Promise.all([
      a.get<Dashboard>(`/v1/projects/${id}/dashboard`),
      a.get<Project>(`/v1/projects/${id}`),
      a.get<{ items: Instruction[] }>('/v1/release-instructions', { status: 'awaiting_client' }),
    ]);
    return { dash, project, waiting: itemsOf(waiting).filter((i) => project.escrow_id && i.escrow === project.escrow_id) };
  }, `project-${id}`);
  const d = data.data?.dash;
  const paidCount = d?.milestones.filter((m) => m.status === 'paid').length ?? 0;

  return (
    <Screen ground="paper" back eyebrow={d ? `${words(d.type)} · ${words(d.status)}` : 'Project'} title={d?.title}>
      <LoadState loading={data.loading} problem={data.problem} onRetry={data.reload} hasData={!!d} />
      {d && data.data ? (
        <>
          {data.data.waiting.length ? (
            <Section title="Needs you">
              {data.data.waiting.map((i) => (
                <ActionRow
                  key={i.id}
                  item={{ kind: 'release_approval', id: i.id, title: i.subject_label || i.reason, status: i.status, status_text: `Approve ${money(i.money)} to ${i.payee_name}. Nothing is paid until you approve.`, next_date: null, needs_action: true, link: `/release-instructions/${i.id}`, family_member_id: null, line: 'construction', amount: null }}
                />
              ))}
            </Section>
          ) : null}

          <Figures
            items={[
              ['Budget', d.budget],
              ['Paid', d.paid],
              ['Held at the bank', d.held_at_bank ?? d.remaining],
              ...(d.defect_value_held && Number(d.defect_value_held.amount) > 0 ? ([['Held for defects', d.defect_value_held]] as [string, ApiMoney][]) : []),
            ]}
          />
          <View style={{ gap: space[2] }}>
            <SegBar done={paidCount} total={d.milestones.length} current={d.milestones.some((m) => m.needs_client)} />
            <Label>{`${paidCount} of ${d.milestones.length} milestones paid${d.contractor ? ` · ${d.contractor}` : ''}${d.inspector ? ` · inspector ${d.inspector}` : ''}`}</Label>
          </View>

          <Section title="Milestones">
            <Panel style={{ gap: 0, paddingVertical: space[1] }}>
              {d.milestones.map((m, i) => (
                <View key={m.id} style={{ flexDirection: 'row', alignItems: 'center', gap: space[3], paddingVertical: space[3], borderTopWidth: i ? 1 : 0, borderTopColor: '#ECEAE4' }}>
                  {m.status === 'paid' ? <Tick /> : <View style={{ width: 22, height: 22, borderRadius: 7, borderWidth: 2, borderColor: m.needs_client ? brand.orange : '#D6D3CB' }} />}
                  <View style={{ flex: 1 }}>
                    <T v="headline" style={{ fontSize: 15 }}>{m.name}</T>
                    <Label>{`${money(m.amount)} · ${words(m.status)}`}</Label>
                  </View>
                  {m.needs_client ? <Chip label="Needs you" tone="orange" /> : null}
                </View>
              ))}
            </Panel>
          </Section>

          {d.inspections.length ? (
            <Section title="Inspections">
              {d.inspections.map((x) => (
                <Panel key={x.id} style={{ gap: space[1] }}>
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[2] }}>
                    <T v="headline" style={{ flex: 1, fontSize: 15 }}>{x.milestone}</T>
                    <Chip label={x.outcome ? OUTCOME[x.outcome] ?? words(x.outcome) : words(x.status)} tone="paper" />
                  </View>
                  <Label>{`${x.inspector}${x.scheduled_for ? ` · ${day(x.scheduled_for)}` : ''}`}</Label>
                  {x.defects.map((df) => (
                    <T key={df.id} v="footnote">{`Defect: ${df.description}`}</T>
                  ))}
                  {x.defect_value && Number(x.defect_value.amount) > 0 ? <T v="footnote" muted>{`${money(x.defect_value)} held back until fixed`}</T> : null}
                </Panel>
              ))}
            </Section>
          ) : null}

          {d.photo_timeline.length ? (
            <Section title={`Photos from site · ${d.photo_timeline.length}`}>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginHorizontal: -space[5] }} contentContainerStyle={{ paddingHorizontal: space[5], gap: space[2] }}>
                {d.photo_timeline.slice(0, 12).map((ph) => (
                  <View key={ph.evidence_id} style={{ width: 132, gap: 4 }}>
                    <EvidenceThumb id={ph.evidence_id} label={`Photo, ${ph.milestone}`} />
                    <Label>{`${ph.milestone} · ${day(ph.captured_at)}`}</Label>
                    {ph.app_captured ? <T v="footnote" muted>Taken in Tenmina Field</T> : null}
                  </View>
                ))}
              </ScrollView>
            </Section>
          ) : null}

          {d.payments.length ? (
            <Section title="Payments">
              <Panel style={{ gap: 0, paddingVertical: space[1] }}>
                {d.payments.map((p, i) => (
                  <View key={p.id} style={{ paddingVertical: space[3], borderTopWidth: i ? 1 : 0, borderTopColor: '#ECEAE4', gap: 2 }}>
                    <View style={{ flexDirection: 'row', gap: space[2] }}>
                      <T v="callout" style={{ flex: 1 }}>{p.label}</T>
                      <T v="headline" style={{ fontSize: 15 }}>{money(p.amount)}</T>
                    </View>
                    <Label>{`${p.payee} · ${p.paid_at ? `paid ${day(p.paid_at)}` : words(p.status)}`}</Label>
                  </View>
                ))}
              </Panel>
            </Section>
          ) : null}
          {data.data.project.escrow_id ? <Button title="Open the escrow at the bank" variant="quiet" icon="lock-closed-outline" onPress={() => router.push(`/escrow/${data.data?.project.escrow_id}`)} /> : null}
        </>
      ) : null}
    </Screen>
  );
}
