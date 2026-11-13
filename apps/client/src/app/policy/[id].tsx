import { useLocalSearchParams } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand } from '@tenmina/tokens';
import { Chip, Label, Panel, Screen, T } from '@tenmina/ui';
import { KV, LoadState, day, money, useGet, words, type ApiMoney } from '@tenmina/mobile';

interface Policy {
  id: string;
  insurer_name: string;
  product_name: string;
  policy_number: string;
  starts_on: string;
  renews_on: string;
  claim_contact: string;
  premium: ApiMoney;
  premium_period: string;
  premium_route: string;
  status: string;
  status_note: string;
  statement: string;
}

/** Policy wallet (SCR-PTL-52, FR-INS-004): the insurer's policy, sold only as the licensed insurer's product. */
export default function PolicyScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const p = useGet<Policy>(`/v1/insurance/policies/${id}`);
  const d = p.data;
  return (
    <Screen ground="paper" back eyebrow={d?.policy_number} title={d?.product_name ?? 'Policy'}>
      <LoadState loading={p.loading} problem={p.problem} onRetry={p.reload} hasData={!!d} />
      {d ? (
        <>
          <Chip label={words(d.status)} tone={d.status === 'active' ? 'lime' : 'paper'} />
          <KV
            rows={[
              ['Insurer', d.insurer_name],
              ['Cover from', day(d.starts_on)],
              ['Renews', day(d.renews_on)],
              ['Premium', `${money(d.premium)} a ${d.premium_period}`],
              ['Paid', d.premium_route === 'client_direct_to_insurer' ? 'By you, straight to the insurer' : 'From your held money, to the insurer'],
              ['To claim', d.claim_contact],
            ]}
          />
          <Panel tone="raised" style={{ flexDirection: 'row' }}>
            <Ionicons name="umbrella-outline" size={20} color={brand.lime} />
            <T v="footnote" color="#F7F6F2" style={{ flex: 1 }}>{d.statement}</T>
          </Panel>
          {d.status_note ? (
            <Panel>
              <Label>Note</Label>
              <T v="callout">{d.status_note}</T>
            </Panel>
          ) : null}
        </>
      ) : null}
    </Screen>
  );
}
