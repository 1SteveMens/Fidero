import { Pressable, View } from 'react-native';
import { router, type Href } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import type { HeldAccount } from '@tenmina/shared';
import { brand, font, radius, space } from '@tenmina/tokens';
import { AccountCards, IconButton, Label, Mark, Rise, Screen, T, haptic, usePalette, type IconName } from '@tenmina/ui';
import { LoadState, Section, itemsOf, toMinor, useGet, useLoad, type ApiMoney } from '@tenmina/mobile';
import { ItemList, NeedsYouList } from '../../components/rows';
import type { Escrow, Home as HomeData } from '../../lib';

function Quick({ icon, label, tone, href, delay }: { icon: IconName; label: string; tone: 'lime' | 'ink' | 'surface'; href: Href; delay: number }) {
  const p = usePalette();
  const bg = tone === 'lime' ? brand.lime : tone === 'ink' ? brand.ink : p.surface;
  const fg = tone === 'lime' ? brand.ink : tone === 'ink' ? brand.lime : p.text;
  return (
    <Rise delay={delay} style={{ flex: 1 }}>
      <Pressable
        onPress={() => {
          haptic('tap');
          router.push(href);
        }}
        accessibilityRole="button"
        accessibilityLabel={label}
        style={({ pressed }) => ({ alignItems: 'center', gap: 6, opacity: pressed ? 0.8 : 1, transform: [{ scale: pressed ? 0.96 : 1 }] })}
      >
        <View style={{ width: 64, height: 64, borderRadius: radius.lg, backgroundColor: bg, alignItems: 'center', justifyContent: 'center' }}>
          <Ionicons name={icon} size={26} color={fg} />
        </View>
        <T v="footnote" style={{ fontFamily: font.semibold, textAlign: 'center' }}>{label}</T>
      </Pressable>
    </Rise>
  );
}

const HELD = ['funded', 'ready_to_release', 'partly_released', 'client_approved', 'release_approved', 'frozen', 'disputed'];

/** Every account the bank holds for the client, as cards with the seal (03 6.1a). Tenmina never holds it (RUL-01). */
async function loadAccounts(api: Parameters<Parameters<typeof useLoad>[0]>[0]): Promise<{ accounts: HeldAccount[]; total: ApiMoney | null }> {
  const [held, list] = await Promise.all([
    api.get<Escrow[]>('/v1/held-funds'),
    api.get<{ items: { id: string; status: string; kind: string }[] }>('/v1/escrows'),
  ]);
  const others = itemsOf(list).filter((e) => HELD.includes(e.status) && e.kind !== 'held_funds').slice(0, 5);
  const details = await Promise.all(others.map((e) => api.get<Escrow>(`/v1/escrows/${e.id}`).catch(() => null)));
  const all = [...held, ...details.filter((d): d is Escrow => !!d)];
  const accounts: HeldAccount[] = [];
  for (const e of all) {
    const f = e.funds?.[0];
    if (!f || Number(f.held_at_bank) <= 0) continue;
    accounts.push({
      id: e.id,
      label: e.kind === 'held_funds' ? 'Family and bills' : e.title,
      kind: e.kind === 'held_funds' ? 'family' : 'escrow',
      bankRef: f.virtual_account_ref || e.reference,
      heldAt: e.payment_instructions?.bank_name?.replace(/\s*\[TO VERIFY\]/, '') || 'Partner bank',
      held: toMinor({ amount: f.held_at_bank, currency: f.currency }) as HeldAccount['held'],
      href: `/escrow/${e.id}`,
    });
  }
  const currency = accounts[0]?.held.currency;
  const sum = accounts.filter((a) => a.held.currency === currency).reduce((n, a) => n + a.held.amountMinor, 0);
  return { accounts, total: currency ? { amount: (sum / 100).toFixed(2), currency } : null };
}

/** Home dashboard (SCR-PTL-36, W-25): account cards with the seal, what needs you, then everything else. */
export default function Home() {
  const p = usePalette('paper');
  const home = useGet<HomeData>('/v1/home');
  const money = useLoad(loadAccounts, 'accounts');
  const unread = useGet<{ count: number }>('/v1/me/notifications/unread-count');
  const d = home.data;
  const needs = d?.items.filter((i) => i.needs_action) ?? [];
  const rest = d?.items.filter((i) => !i.needs_action && i.kind !== 'rating_opportunity') ?? [];
  const first = d?.person.full_name.split(' ')[0];
  const bill = needs.find((i) => i.kind === 'fee_invoice');

  return (
    <Screen ground="paper" tabs>
      <Rise>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[3] }}>
          <Mark />
          <T v="title" header style={{ flex: 1 }}>{first ? `Akwaaba, ${first}` : 'Akwaaba'}</T>
          <View>
            <IconButton icon="notifications-outline" label={unread.data?.count ? `Messages, ${unread.data.count} new` : 'Messages'} onPress={() => router.push('/inbox')} />
            {unread.data?.count ? <View style={{ position: 'absolute', top: 10, right: 11, width: 10, height: 10, borderRadius: 5, backgroundColor: brand.orange, borderWidth: 2, borderColor: p.surface }} /> : null}
          </View>
        </View>
      </Rise>

      <LoadState loading={home.loading} problem={home.problem} onRetry={home.reload} hasData={!!d} />

      {money.data && money.data.accounts.length && money.data.total ? (
        <AccountCards accounts={money.data.accounts} holder={d?.person.full_name.toUpperCase() ?? ''} total={toMinor(money.data.total) as HeldAccount['held']} />
      ) : null}

      {d ? (
        <>
          <View style={{ flexDirection: 'row', gap: space[2] }}>
            <Quick icon="location-outline" label="Check land" tone="lime" href="/order" delay={200} />
            <Quick icon="receipt-outline" label="Pay a bill" tone="ink" href={bill ? (`/invoice/${bill.id}` as Href) : '/family'} delay={260} />
            <Quick icon="construct-outline" label="Build" tone="surface" href="/projects" delay={320} />
            <Quick icon="heart-outline" label="Care visit" tone="surface" href="/family" delay={380} />
          </View>

          <Rise delay={420}>
            <NeedsYouList items={needs} />
          </Rise>

          <Rise delay={500}>
            <Section title={`Everything else · ${rest.length}`}>
              <ItemList items={rest.slice(0, 8)} empty="Nothing yet. Start with a land check or a bill." />
            </Section>
          </Rise>
          <Label style={{ textAlign: 'center' }}>{`${d.person.home_country} · money is held by the partner bank, never by Tenmina`}</Label>
        </>
      ) : null}
    </Screen>
  );
}
