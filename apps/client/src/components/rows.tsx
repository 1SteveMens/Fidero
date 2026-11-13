import { useState } from 'react';
import { Pressable, View } from 'react-native';
import { router, type Href } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, radius, space } from '@tenmina/tokens';
import { ArrowBox, Button, IconTile, ListRow, NeedsYou, Panel, T, haptic, usePalette, type IconName } from '@tenmina/ui';
import { money, useGet, type ApiMoney } from '@tenmina/mobile';
import { iconFor, routeFor, type Home, type HomeItem } from '../lib';

/** GET /v1/home, shared by the tabs so each shows the same "Needs you" (F-35). */
export function useHome() {
  return useGet<Home>('/v1/home');
}

/** A home item that needs the client: orange, and it opens. */
export function ActionRow({ item }: { item: HomeItem }) {
  return (
    <Pressable
      onPress={() => {
        haptic('tap');
        router.push(routeFor(item.link, item.title, item.status_text));
      }}
      accessibilityRole="button"
      accessibilityLabel={`Needs you. ${item.title}. ${item.status_text}`}
      style={({ pressed }) => ({ flexDirection: 'row', alignItems: 'center', gap: space[3], backgroundColor: brand.orange, borderRadius: radius.lg - 4, padding: space[3], opacity: pressed ? 0.85 : 1 })}
    >
      <IconTile name={iconFor(item.kind)} tone="ink" size={38} />
      <View style={{ flex: 1 }}>
        <T v="headline" color={brand.ink} style={{ fontSize: 15 }}>{item.title}</T>
        <T v="footnote" color="#3A1408">{item.amount ? `${money(item.amount)} · ${item.status_text}` : item.status_text}</T>
      </View>
      <ArrowBox arrow={brand.orange} />
    </Pressable>
  );
}

/**
 * Everything that needs the client: the first as the big orange card, the rest
 * as rows with an orange mark, so orange stays the signal and not the page.
 */
export function NeedsYouList({ items, limit = 5 }: { items: HomeItem[]; limit?: number }) {
  const [all, setAll] = useState(false);
  if (!items.length) {
    return (
      <Panel tone="lime" style={{ flexDirection: 'row', alignItems: 'center' }}>
        <Ionicons name="checkmark-circle" size={22} color={brand.ink} />
        <T v="headline" color={brand.ink} style={{ flex: 1 }}>Nothing needs you right now</T>
      </Panel>
    );
  }
  const [first, ...rest] = items;
  const shown = all ? rest : rest.slice(0, limit);
  return (
    <View style={{ gap: space[2] }}>
      <NeedsYou
        title={first.title}
        detail={first.amount ? `${money(first.amount)} · ${first.status_text}` : first.status_text}
        count={items.length}
        onPress={() => router.push(routeFor(first.link, first.title, first.status_text))}
      />
      {shown.length ? (
        <Panel style={{ paddingVertical: space[1], gap: 0 }}>
          {shown.map((i, n) => (
            <ListRow
              key={`${i.kind}-${i.id}`}
              icon={iconFor(i.kind)}
              iconTone="orange"
              title={i.title}
              detail={i.amount ? `${money(i.amount)} · ${i.status_text}` : i.status_text}
              onPress={() => router.push(routeFor(i.link, i.title, i.status_text))}
              last={n === shown.length - 1}
            />
          ))}
        </Panel>
      ) : null}
      {rest.length > limit ? <Button title={all ? 'Show fewer' : `Show all ${items.length}`} variant="quiet" onPress={() => setAll((a) => !a)} /> : null}
    </View>
  );
}

/** Items in a plain list. One that needs the client carries an orange mark and comes first. */
export function ItemList({ items, empty }: { items: HomeItem[]; empty?: string }) {
  items = [...items.filter((i) => i.needs_action), ...items.filter((i) => !i.needs_action)];
  if (!items.length) return empty ? <T v="callout" muted>{empty}</T> : null;
  return (
    <Panel style={{ paddingVertical: space[1], gap: 0 }}>
      {items.map((r, i) => (
        <ListRow
          key={`${r.kind}-${r.id}`}
          icon={iconFor(r.kind)}
          iconTone={r.needs_action ? 'orange' : 'ink'}
          title={r.title}
          detail={r.amount ? `${money(r.amount)} · ${r.status_text}` : r.status_text}
          onPress={() => router.push(routeFor(r.link, r.title, r.status_text))}
          last={i === items.length - 1}
        />
      ))}
    </Panel>
  );
}

/** A tile that starts something new. */
export function StartTile({ icon, title, detail, tone, href, onPress }: { icon: IconName; title: string; detail: string; tone: 'lime' | 'ink' | 'surface'; href?: Href; onPress?: () => void }) {
  const p = usePalette();
  const bg = tone === 'lime' ? brand.lime : tone === 'ink' ? brand.ink : p.surface;
  const fg = tone === 'ink' ? '#F7F6F2' : tone === 'lime' ? brand.ink : p.text;
  const sub = tone === 'ink' ? '#A9A69E' : tone === 'lime' ? '#3F5A1F' : p.textMuted;
  return (
    <Pressable
      onPress={() => {
        haptic('tap');
        if (onPress) onPress();
        else if (href) router.push(href);
      }}
      accessibilityRole="button"
      accessibilityLabel={`${title}. ${detail}`}
      style={({ pressed }) => ({ flex: 1, minHeight: 124, borderRadius: radius.lg, backgroundColor: bg, padding: space[3], justifyContent: 'space-between', opacity: pressed ? 0.85 : 1 })}
    >
      <Ionicons name={icon} size={24} color={tone === 'ink' ? brand.lime : fg} />
      <View>
        <T v="headline" color={fg} style={{ fontSize: 15, lineHeight: 18 }}>{title}</T>
        <T v="footnote" color={sub} style={{ fontSize: 12 }}>{detail}</T>
      </View>
    </Pressable>
  );
}

/** Money figures in a row of small panels (held at the bank, waiting, available). */
export function Figures({ items }: { items: [string, ApiMoney | null | undefined][] }) {
  return (
    <View style={{ flexDirection: 'row', gap: space[2], flexWrap: 'wrap' }}>
      {items.map(([label, m]) => (
        <Panel key={label} style={{ flexGrow: 1, flexBasis: 140, gap: 2, paddingVertical: space[3] }}>
          <T v="footnote" muted>{label}</T>
          <T v="headline" style={{ fontSize: 17 }}>{money(m)}</T>
        </Panel>
      ))}
    </View>
  );
}
