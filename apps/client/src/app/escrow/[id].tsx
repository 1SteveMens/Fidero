import { View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, space } from '@tenmina/tokens';
import { Button, Chip, Label, Panel, Rise, Screen, T, Tick } from '@tenmina/ui';
import { KV, LoadState, ProblemBox, Section, day, itemsOf, money, moneyOf, useAction, useGet, useSession } from '@tenmina/mobile';
import { ActionRow, Figures } from '../../components/rows';
import { ESCROW_STATUS, type Escrow, type Instruction } from '../../lib';

/**
 * Escrow tracker (SCR-PTL-17, W-09) with its terms (SCR-PTL-16) and the bank's
 * own payment details (SCR-PTL-18). The money is at the partner bank, never at
 * Tenmina (RUL-01). Releases wait for the client, then two staff.
 */
export default function EscrowScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { me } = useSession();
  const e = useGet<Escrow>(`/v1/escrows/${id}`);
  const waiting = useGet<{ items: Instruction[] }>('/v1/release-instructions', { status: 'awaiting_client' });
  const accept = useAction();
  const d = e.data;
  const mine = itemsOf(waiting.data).filter((i) => i.escrow === id);
  const f = d?.funds?.[0];
  const myParty = d?.parties.find((p) => p.must_accept && !p.accepted_current_terms && p.name === me?.full_name);
  const pi = d?.payment_instructions;

  async function acceptTerms() {
    const r = await accept.run('POST', `/v1/escrows/${id}/acceptances`, myParty ? { party_id: myParty.id } : {});
    if (r) e.reload();
  }

  return (
    <Screen ground="paper" back eyebrow={d ? `${d.reference} · ${d.country}` : 'Escrow'}>
      <LoadState loading={e.loading} problem={e.problem} onRetry={e.reload} hasData={!!d} />
      {d ? (
        <>
          <Rise delay={40} style={{ gap: space[2] }}>
            <T v="title" header>{d.kind === 'held_funds' ? 'Money held for family and bills' : d.title}</T>
            <View style={{ flexDirection: 'row', gap: space[2], flexWrap: 'wrap' }}>
              <Chip label={ESCROW_STATUS[d.status] ?? d.status} tone={d.status === 'released' ? 'lime' : 'paper'} />
              {Number(d.agreed_price.amount) > 0 ? <Chip label={`Price ${money(d.agreed_price)}`} tone="surface" /> : null}
            </View>
          </Rise>

          {mine.length ? (
            <Section title="Needs you">
              {mine.map((i) => (
                <ActionRow
                  key={i.id}
                  item={{ kind: 'release_approval', id: i.id, title: i.subject_label || i.reason, status: i.status, status_text: `Approve ${money(i.money)} to ${i.payee_name}`, next_date: null, needs_action: true, link: `/release-instructions/${i.id}`, family_member_id: null, line: 'escrow', amount: null }}
                />
              ))}
            </Section>
          ) : null}

          {myParty ? (
            <Panel tone="orange">
              <Label color={brand.ink}>Needs you</Label>
              <T v="headline" color={brand.ink}>Accept the escrow terms</T>
              <T v="footnote" color="#3A1408">Nothing is paid in or out until every party accepts the same terms.</T>
              <Button title="I accept the terms" variant="dark" loading={accept.busy} onPress={() => void acceptTerms()} />
            </Panel>
          ) : null}
          <ProblemBox problem={accept.problem} />

          {f ? (
            <Figures
              items={[
                ['Held at the bank', { amount: f.held_at_bank, currency: f.currency }],
                ['Waiting for the bank', { amount: f.instructed_awaiting_bank, currency: f.currency }],
                ['Free to release', { amount: f.available_to_instruct, currency: f.currency }],
              ]}
            />
          ) : null}

          {d.conditions.length ? (
            <Section title={`Conditions · ${d.conditions.filter((c) => c.status === 'closed').length} of ${d.conditions.length} met`}>
              <Panel style={{ gap: 0, paddingVertical: space[1] }}>
                {d.conditions.map((c, i) => (
                  <View key={c.id} style={{ flexDirection: 'row', gap: space[3], alignItems: 'center', paddingVertical: space[3], borderTopWidth: i ? 1 : 0, borderTopColor: '#ECEAE4' }}>
                    {c.status === 'closed' ? <Tick /> : <View style={{ width: 22, height: 22, borderRadius: 7, borderWidth: 2, borderColor: '#D6D3CB' }} />}
                    <View style={{ flex: 1 }}>
                      <T v="callout">{c.text}</T>
                      {c.closed_at ? <Label>{`Met ${day(c.closed_at)}`}</Label> : <Label>Open</Label>}
                    </View>
                  </View>
                ))}
              </Panel>
            </Section>
          ) : null}

          {d.fresh_search_result_date ? (
            <Panel style={{ flexDirection: 'row', alignItems: 'center' }}>
              <Ionicons name="search-outline" size={20} />
              <T v="callout" style={{ flex: 1 }}>{`Fresh official search: ${day(d.fresh_search_result_date)}`}</T>
            </Panel>
          ) : null}
          {Number(d.held_back_amount) > 0 ? (
            <KV rows={[['Held back', moneyOf(d.held_back_amount, d.currency)], ['Until', d.held_back_condition || '—']]} />
          ) : null}

          {pi?.available ? (
            <Section title="Pay in: the bank's own details">
              <Panel tone="raised">
                <Label color="#A9A69E">Pay the bank, never Tenmina</Label>
                <T v="headline" color="#F7F6F2" style={{ fontSize: 15 }}>{pi.bank_name}</T>
                {[
                  ['Account name', pi.account_name],
                  ['Account number', pi.account_number],
                  ['Reference', pi.reference],
                  ['Currency', pi.currency],
                ].map(([k, v]) => (
                  <View key={k} style={{ flexDirection: 'row', gap: space[3] }}>
                    <T v="footnote" color="#A9A69E" style={{ width: 110 }}>{k}</T>
                    <T v="mono" color={brand.lime} style={{ flex: 1, fontSize: 14 }}>{v}</T>
                  </View>
                ))}
                <T v="footnote" color="#A9A69E">{pi.note}</T>
              </Panel>
            </Section>
          ) : null}

          {d.case_id ? <Button title="Open the case" variant="quiet" icon="document-text-outline" onPress={() => router.push(`/case/${d.case_id}`)} /> : null}
          {d.project_id ? <Button title="Open the project" variant="quiet" icon="construct-outline" onPress={() => router.push(`/project/${d.project_id}`)} /> : null}
        </>
      ) : null}
    </Screen>
  );
}
