import { Image, Pressable, View } from 'react-native';
import { router } from 'expo-router';
import { brand, radius, space } from '@tenmina/tokens';
import { Chip, Label, Panel, Screen, T, haptic, usePalette } from '@tenmina/ui';
import { Empty, LoadState, apiBaseUrl, day, itemsOf, money, useGet, useSession, words, type ApiMoney } from '@tenmina/mobile';

export interface Listing {
  id: string;
  reference: string;
  status: string;
  kind: string;
  title: string;
  description: string;
  estate_name: string;
  price: ApiMoney;
  size_sqm: string | null;
  region: string;
  district: string;
  locality: string;
  badge: { label: string; checks_date: string; expires_at: string; report_link: string; report_reference: string } | null;
  checks_date: string | null;
  seller: { name: string; kind: string; established: boolean };
  disclosure: string;
  media: { id: string; kind: string; caption: string; public: boolean; evidence_id: string; url: string | null }[];
  reserved: boolean;
  can_reserve: boolean;
}

export function photoUrl(l: Listing): string | null {
  const m = l.media.find((x) => x.kind === 'photo' && x.url);
  return m?.url ? `${apiBaseUrl()}${m.url}` : null;
}

/**
 * Verified listings in the app (SCR-PTL-20, FR-LST-004): only live listings
 * whose Tenmina check is current. Each shows the badge with its check date.
 */
export default function Listings() {
  const { me } = useSession();
  const p = usePalette();
  const list = useGet<{ items: Listing[] } | Listing[]>('/v1/listings', { country: me?.home_country });
  const rows = itemsOf(list.data);
  return (
    <Screen ground="paper" back eyebrow="Property" title="Verified listings">
      <T v="callout" muted>Plots and homes Tenmina has checked. Buy only through the bank escrow: the seller is paid after the conditions are met.</T>
      <LoadState loading={list.loading} problem={list.problem} onRetry={list.reload} hasData={!!list.data} />
      {list.data && !rows.length ? <Empty icon="map-outline" title="No listings right now" detail="New checked listings appear here." /> : null}
      {rows.map((l) => {
        const img = photoUrl(l);
        return (
          <Pressable
            key={l.id}
            onPress={() => {
              haptic('tap');
              router.push(`/listing/${l.id}`);
            }}
            accessibilityRole="button"
            accessibilityLabel={`${l.title}. ${money(l.price)}.`}
            style={({ pressed }) => ({ borderRadius: radius.xl, backgroundColor: p.surface, overflow: 'hidden', opacity: pressed ? 0.9 : 1 })}
          >
            {img ? <Image source={{ uri: img }} style={{ width: '100%', aspectRatio: 4 / 3, backgroundColor: p.line }} accessibilityLabel={`Photo of ${l.title}`} /> : null}
            <View style={{ padding: space[4], gap: space[1] }}>
              <View style={{ flexDirection: 'row', gap: space[2], alignItems: 'center' }}>
                {l.badge ? <Chip label="Tenmina Verified" tone="lime" icon="checkmark" /> : null}
                {l.reserved ? <Chip label="Reserved" tone="paper" /> : null}
              </View>
              <T v="headline">{l.title}</T>
              <T v="amount" style={{ fontSize: 22, lineHeight: 28 }}>{money(l.price)}</T>
              <Label>{[words(l.kind), l.locality, l.size_sqm ? `${Number(l.size_sqm).toLocaleString('en-GB')} m²` : ''].filter(Boolean).join(' · ')}</Label>
              {l.badge ? <T v="footnote" muted>{`Checked ${day(l.badge.checks_date)} · ${l.seller.name}`}</T> : null}
            </View>
          </Pressable>
        );
      })}
      <View style={{ height: space[2], backgroundColor: brand.paper }} />
    </Screen>
  );
}
