import { useEffect, useState } from 'react';
import { View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { space } from '@tenmina/tokens';
import { Button, Label, Loading, Panel, Screen, T, usePalette } from '@tenmina/ui';
import { useApi } from '@tenmina/mobile';

/** What a summary is about, in words: never the raw part of a link. */
const KIND: Record<string, string> = {
  institutions: 'Institution',
  insurance: 'Insurance',
  payments: 'Payment',
  receipts: 'Receipt',
  'partner-orders': 'Request from a partner',
  account: 'Your account',
  ratings: 'Rating',
  reservations: 'Reservation',
  'vendor-payments': 'Event payment',
  monitoring: 'Monitoring',
};

/**
 * Links whose screen is known only after one lookup: the record names the screen where the client acts.
 * A vendor payment is approved on its event's screen; a reservation's escrow terms are accepted on the escrow.
 */
const LOOKUP: [RegExp, (api: ReturnType<typeof useApi>, id: string) => Promise<string | null>][] = [
  [/^\/vendor-payments\/([^/?]+)$/, async (api, id) => {
    const v = await api.get<{ event: string }>(`/v1/vendor-payments/${id}`);
    return v.event ? `/event/${v.event}` : null;
  }],
  [/^\/reservations\/([^/?]+)$/, async (api, id) => {
    const r = await api.get<{ escrow: { id: string } | null; listing: { id: string } | null }>(`/v1/reservations/${id}`);
    return r.escrow ? `/escrow/${r.escrow.id}` : r.listing ? `/listing/${r.listing.id}` : null;
  }],
];

/**
 * Anything the app shows only as a summary (a partner request, a rating, a
 * monitoring alert): what it is and where it stands. It stays in the app: the
 * full record sits with the case, escrow or project it belongs to, and Tenmina
 * tells you on the home screen when it needs you. Opening it never approves
 * anything. A link whose screen needs one lookup (an event payment, a
 * reservation) goes straight to that screen.
 */
export default function Item() {
  const p = usePalette();
  const api = useApi();
  const { link, title, detail } = useLocalSearchParams<{ link: string; title?: string; detail?: string }>();
  const path = (link ?? '').split('?')[0];
  const lookup = LOOKUP.find(([re]) => re.test(path));
  const [resolving, setResolving] = useState(!!lookup);

  useEffect(() => {
    if (!lookup) return;
    let live = true;
    const id = path.match(lookup[0])?.[1] ?? '';
    lookup[1](api, id)
      .then((to) => {
        if (live && to) router.replace(to as never);
        else if (live) setResolving(false);
      })
      .catch(() => live && setResolving(false));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, path]);

  const where = KIND[path.split('/').filter(Boolean)[0] ?? ''];
  return (
    <Screen ground="paper" back title={title || 'Details'} footer={<Button title="Back to home" variant="dark" onPress={() => router.replace('/')} />}>
      {resolving ? (
        <Loading />
      ) : (
        <>
          <Panel>
            {where ? <Label>{where}</Label> : null}
            <T v="callout">{detail || 'Nothing needs you on this right now.'}</T>
          </Panel>
          <View style={{ flexDirection: 'row', gap: space[3] }}>
            <Ionicons name="notifications-outline" size={18} color={p.text} />
            <T v="footnote" muted style={{ flex: 1 }}>When this needs you, it comes first on your home screen and in your inbox.</T>
          </View>
        </>
      )}
    </Screen>
  );
}
