import { Pressable, View } from 'react-native';
import { router, type Href } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, font, radius, space } from '@tenmina/tokens';
import { IconButton, Label, Mark, Rise, Screen, T, haptic, usePalette, TenminaAccountCard, type IconName, type TenminaAccountCardData } from '@tenmina/ui';
import { LoadState, Section, toMinor, useGet, useLoad } from '@tenmina/mobile';
import { ItemList, NeedsYouList } from '../../components/rows';
import { COMMITMENT_KIND, commitmentState, type Home as HomeData, type TenminaAccount } from '../../lib';

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

/** The client's one Tenmina account and the commitments inside it (03 6.1a, decision 2026-11-17). The bank holds
 * it, never Tenmina (RUL-01). No account yet: no card. */
async function loadAccount(api: Parameters<Parameters<typeof useLoad>[0]>[0]): Promise<TenminaAccountCardData | null> {
  const acc = await api.get<TenminaAccount>('/v1/account').catch(() => null);
  if (!acc) return null;
  const open = acc.commitments.filter((c) => !['released', 'cancelled'].includes(c.status) || Number(c.set_aside.amount) > 0);
  return {
    reference: acc.pay_in?.reference ?? acc.reference,
    heldAt: (acc.pay_in?.bank_name ?? acc.bank_name).replace(/\s*\[TO VERIFY\]/, '') || 'Partner bank',
    href: '/money',
    balances: acc.balances.map((b) => ({ held: toMinor(b.held_at_bank), free: toMinor(b.free_balance), setAside: toMinor(b.set_aside) })),
    commitments: open.map((c) => {
      const setAside = Number(c.set_aside.amount) > 0;
      return {
        id: c.id, label: c.title, kind: COMMITMENT_KIND[c.kind] ?? c.kind, state: commitmentState(c), href: `/escrow/${c.id}`,
        amount: toMinor(setAside ? c.set_aside : c.agreed), amountNote: setAside ? 'set aside' : 'agreed', needsYou: c.needs_you,
      };
    }),
  };
}

/** Home dashboard (SCR-PTL-36, W-25): the one account card with its commitments, what needs you, then everything else. */
export default function Home() {
  const p = usePalette('paper');
  const home = useGet<HomeData>('/v1/home');
  const money = useLoad(loadAccount, 'account');
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

      {money.data ? <TenminaAccountCard account={money.data} holder={d?.person.full_name.toUpperCase() ?? ''} /> : null}

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
