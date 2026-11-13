import { View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import { space } from '@tenmina/tokens';
import { Chip, Label, ListRow, Panel, Screen, T } from '@tenmina/ui';
import { KV, LoadState, Section, day, itemsOf, useLoad, words } from '@tenmina/mobile';

interface Managed {
  id: string;
  title: string;
  asset_reference: string;
  locality: string;
  status: string;
  rent_account: { bank_name: string; account_name: string; last4: string; verification_status: string } | null;
  active_tenancy: { tenant_name?: string; rent?: { amount: string; currency: string }; starts_on?: string; ends_on?: string } | null;
  blockers: { rule: string; message: string }[];
  next_inspection_due_on: string | null;
  inspection_interval_months: number;
}

interface Repair {
  id: string;
  property: string;
  title: string;
  status: string;
  urgent: boolean;
  quotes: unknown[];
}

/**
 * Property dashboard (SCR-PTL-46, SCR-PTL-47, W-32): rent into the owner's own
 * account (RUL-24), inspections with photos, repairs and their quotes, and the timeline.
 */
export default function ManagedScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const data = useLoad(async (a) => {
    const [p, timeline, repairs] = await Promise.all([
      a.get<Managed>(`/v1/managed-properties/${id}`),
      a.get<{ date: string; kind: string; title: string; status: string; detail: string; id: string }[]>(`/v1/managed-properties/${id}/timeline`),
      a.get<{ items: Repair[] }>('/v1/repairs'),
    ]);
    return { p, timeline, repairs: itemsOf(repairs).filter((r) => r.property === id) };
  }, `managed-${id}`);
  const d = data.data?.p;

  return (
    <Screen ground="paper" back eyebrow={d ? `${d.asset_reference} · ${d.locality}` : 'Property'} title={d?.title}>
      <LoadState loading={data.loading} problem={data.problem} onRetry={data.reload} hasData={!!d} />
      {d && data.data ? (
        <>
          <Chip label={words(d.status)} tone={d.status === 'managed' || d.status === 'active' ? 'lime' : 'paper'} />
          {d.blockers.length ? (
            <Panel>
              <Label>Before management starts</Label>
              {d.blockers.map((b) => (
                <View key={b.message} style={{ flexDirection: 'row', gap: space[2] }}>
                  <Label style={{ marginTop: 3 }}>{b.rule}</Label>
                  <T v="callout" style={{ flex: 1 }}>{b.message}</T>
                </View>
              ))}
            </Panel>
          ) : null}
          <KV
            rows={[
              ['Rent goes to', d.rent_account ? `${d.rent_account.account_name} ••${d.rent_account.last4} · ${words(d.rent_account.verification_status)}` : 'Add your own bank account'],
              ['Tenant', d.active_tenancy?.tenant_name ?? 'None'],
              ['Next inspection', d.next_inspection_due_on ? day(d.next_inspection_due_on) : `Every ${d.inspection_interval_months} months`],
            ]}
          />
          <Section title={`Repairs · ${data.data.repairs.length}`}>
            {data.data.repairs.length ? (
              <Panel style={{ gap: 0, paddingVertical: space[1] }}>
                {data.data.repairs.map((r, i) => (
                  <ListRow
                    key={r.id}
                    icon="hammer-outline"
                    iconTone={r.status === 'quotes_ready' ? 'orange' : 'ink'}
                    title={r.title}
                    detail={`${words(r.status)}${r.urgent ? ' · urgent' : ''} · ${r.quotes.length} quotes`}
                    onPress={() => router.push(`/repair/${r.id}`)}
                    last={i === data.data!.repairs.length - 1}
                  />
                ))}
              </Panel>
            ) : (
              <T v="callout" muted>No repairs.</T>
            )}
          </Section>
          <Section title="Timeline">
            <Panel style={{ gap: space[3] }}>
              {data.data.timeline.map((t) => (
                <View key={`${t.kind}-${t.id}-${t.date}`} style={{ gap: 2 }}>
                  <Label>{`${day(t.date)} · ${words(t.status)}`}</Label>
                  <T v="callout">{t.title}</T>
                  {t.detail ? <T v="footnote" muted>{t.detail}</T> : null}
                </View>
              ))}
            </Panel>
          </Section>
        </>
      ) : null}
    </Screen>
  );
}
