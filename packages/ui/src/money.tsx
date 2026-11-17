import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Animated, Easing, Platform, Pressable, View } from 'react-native';
import { router } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import Svg, { Circle, Defs, Path, Text as SvgText, TextPath } from 'react-native-svg';
import { formatMoney, type Money } from '@tenmina/shared';
import { brand, font, radius, space } from '@tenmina/tokens';
import { usePalette, useReducedMotion } from './theme';
import { Label, T, haptic } from './ui';

const nativeDriver = Platform.OS !== 'web';

/** The round seal on the account card. Its words turn slowly; the check stays still. */
export function Seal({ id, ring, text, check, size = 132, words = 'HELD AT THE BANK · RELEASED ON PROOF · ' }: { id: string; ring: string; text: string; check: string; size?: number; words?: string }) {
  const reduced = useReducedMotion();
  const spin = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (reduced) return;
    const loop = Animated.loop(Animated.timing(spin, { toValue: 1, duration: 24000, easing: Easing.linear, useNativeDriver: nativeDriver }));
    loop.start();
    return () => loop.stop();
  }, [reduced, spin]);
  const rotate = spin.interpolate({ inputRange: [0, 1], outputRange: ['0deg', '360deg'] });
  return (
    <View style={{ width: size, height: size }} pointerEvents="none">
      <Animated.View style={{ position: 'absolute', inset: 0, transform: [{ rotate }] }}>
        <Svg width={size} height={size} viewBox="0 0 120 120">
          <Defs>
            <Path id={id} d="M60,60 m-44,0 a44,44 0 1,1 88,0 a44,44 0 1,1 -88,0" />
          </Defs>
          <Circle cx={60} cy={60} r={56} fill="none" stroke={ring} strokeWidth={1.5} />
          <Circle cx={60} cy={60} r={31} fill="none" stroke={ring} strokeWidth={1.5} />
          <SvgText fill={text} fontSize={8.5} letterSpacing={1.6} fontFamily={font.monoBold}>
            <TextPath href={`#${id}`}>{words}</TextPath>
          </SvgText>
        </Svg>
      </Animated.View>
      <Svg width={size} height={size} viewBox="0 0 120 120" style={{ position: 'absolute' }}>
        <Path d="M49 61l7 7 15-16" fill="none" stroke={check} strokeWidth={4} strokeLinecap="round" strokeLinejoin="round" />
      </Svg>
    </View>
  );
}

/** One commitment inside the account (decision 2026-11-17): money set aside for one deal. */
export interface AccountCommitmentRow {
  id: string;
  /** What the money is for, for example "Plot at Kasoa". */
  label: string;
  /** Purchase, Building, Event, Repair, ... */
  kind: string;
  /** One plain sentence on its state. */
  state: string;
  amount: Money;
  /** "set aside" or "agreed". */
  amountNote: string;
  href: string;
  needsYou?: boolean;
}

export interface TenminaAccountCardData {
  /** The client's one pay-in reference at the bank. */
  reference: string;
  heldAt: string;
  /** One line per currency the client pays in. */
  balances: { held: Money; free: Money; setAside: Money }[];
  commitments: AccountCommitmentRow[];
  href: string;
}

/**
 * The client's one Tenmina account (03 6.1a, decision 2026-11-17): one black card with the seal, the balance held
 * at the bank, the free balance and what is set aside, and the commitments inside it. Never a wallet, never a payment
 * card: the bank holds the money and releases it only on proof. Tenmina never holds it (RUL-01).
 */
export function TenminaAccountCard({ account, holder, max = 4 }: { account: TenminaAccountCardData; holder: string; max?: number }) {
  const reduced = useReducedMotion();
  const enter = useRef(new Animated.Value(reduced ? 1 : 0)).current;
  useEffect(() => {
    if (reduced) return;
    Animated.timing(enter, { toValue: 1, duration: 800, delay: 100, easing: Easing.out(Easing.cubic), useNativeDriver: nativeDriver }).start();
  }, [enter, reduced]);
  const fg = '#F7F6F2';
  const sub = '#A9A69E';
  const line = '#2C2C2C';
  const shown = account.commitments.slice(0, max);
  const main = account.balances[0];
  const open = (href: string) => {
    haptic('tap');
    router.push(href as never);
  };
  return (
    <Animated.View
      style={{
        opacity: enter,
        transform: [{ perspective: 900 }, { rotateX: enter.interpolate({ inputRange: [0, 1], outputRange: ['18deg', '0deg'] }) }, { translateY: enter.interpolate({ inputRange: [0, 1], outputRange: [24, 0] }) }],
        borderRadius: radius.xl,
        backgroundColor: brand.ink,
        overflow: 'hidden',
        shadowColor: '#000',
        shadowOpacity: 0.2,
        shadowRadius: 16,
        shadowOffset: { width: 0, height: 10 },
        elevation: 6,
      }}
    >
      <Pressable
        onPress={() => open(account.href)}
        accessibilityRole="button"
        accessibilityLabel={`Your Tenmina account, reference ${account.reference}. ${account.balances.map((b) => `${formatMoney(b.held)} held by ${account.heldAt}, ${formatMoney(b.free)} free, ${formatMoney(b.setAside)} set aside`).join('. ')}.`}
        style={{ paddingHorizontal: space[5], paddingTop: space[4], paddingBottom: space[3], minHeight: 44 }}
      >
        <View style={{ position: 'absolute', right: -26, top: -36 }}>
          <Seal id="seal-account" ring="#262626" text="#55534D" check={brand.lime} />
        </View>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[2] }}>
          <T v="headline" color={fg} style={{ fontFamily: font.heavy, fontSize: 19, letterSpacing: -0.8 }}>tenmina</T>
          <Label color={sub} style={{ fontSize: 10 }}>{`Account · ${account.reference}`}</Label>
        </View>
        <Label color={sub} style={{ fontSize: 10, marginTop: space[4] }}>Held at the bank for you</Label>
        {account.balances.map((b) => (
          <T key={b.held.currency} v="amount" color={fg} style={{ fontSize: 30, lineHeight: 36 }}>{formatMoney(b.held)}</T>
        ))}
        {main ? (
          <View style={{ flexDirection: 'row', gap: space[4], marginTop: space[2], paddingTop: space[2], borderTopWidth: 1, borderTopColor: line }}>
            <View style={{ flex: 1 }}>
              <Label color={sub} style={{ fontSize: 10 }}>Free balance</Label>
              {account.balances.map((b) => <T key={b.free.currency} v="callout" color={fg} style={{ fontFamily: font.bold }}>{formatMoney(b.free)}</T>)}
            </View>
            <View style={{ flex: 1 }}>
              <Label color={sub} style={{ fontSize: 10 }}>Set aside</Label>
              {account.balances.map((b) => <T key={b.setAside.currency} v="callout" color={fg} style={{ fontFamily: font.bold }}>{formatMoney(b.setAside)}</T>)}
            </View>
          </View>
        ) : null}
      </Pressable>
      {shown.length ? (
        <View style={{ paddingHorizontal: space[5] }}>
          <Label color={sub} style={{ fontSize: 10, marginBottom: 2 }}>{`Commitments inside it · ${account.commitments.length}`}</Label>
          {shown.map((c, i) => (
            <Pressable
              key={c.id}
              onPress={() => open(c.href)}
              accessibilityRole="button"
              accessibilityLabel={`${c.kind}: ${c.label}. ${formatMoney(c.amount)} ${c.amountNote}. ${c.state}${c.needsYou ? ' Needs you.' : ''}`}
              style={({ pressed }) => ({ flexDirection: 'row', gap: space[3], paddingVertical: space[2], minHeight: 44, borderTopWidth: i ? 1 : 0, borderTopColor: line, opacity: pressed ? 0.8 : 1 })}
            >
              <View style={{ flex: 1 }}>
                <Label color={c.needsYou ? brand.orange : sub} style={{ fontSize: 10 }}>{c.needsYou ? `${c.kind} · needs you` : c.kind}</Label>
                <T v="callout" color={fg} style={{ fontFamily: font.bold }} numberOfLines={1}>{c.label}</T>
                <T v="footnote" color={sub} numberOfLines={2}>{c.state}</T>
              </View>
              <View style={{ alignItems: 'flex-end' }}>
                <T v="callout" color={fg} style={{ fontFamily: font.bold }}>{formatMoney(c.amount)}</T>
                <T v="footnote" color={sub}>{c.amountNote}</T>
              </View>
            </Pressable>
          ))}
          {account.commitments.length > shown.length ? (
            <Pressable onPress={() => open(account.href)} accessibilityRole="button" style={{ minHeight: 44, justifyContent: 'center' }}>
              <T v="footnote" color={fg} style={{ fontFamily: font.semibold }}>{`See all ${account.commitments.length} commitments`}</T>
            </Pressable>
          ) : null}
        </View>
      ) : null}
      <View style={{ minHeight: 54, paddingHorizontal: space[5], backgroundColor: '#1A1A1A', flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: space[3], marginTop: space[2] }}>
        <Label color={fg} style={{ flexShrink: 1 }}>{holder}</Label>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, flexShrink: 1 }}>
          <Ionicons name="business" size={14} color={sub} />
          <Label color={sub}>{account.heldAt}</Label>
        </View>
      </View>
    </Animated.View>
  );
}

/** A ticket: the amount above a tear line, who gets paid below. Used only where money is about to move. */
export function Ticket({ top, bottom }: { top: ReactNode; bottom: ReactNode }) {
  const p = usePalette();
  const [tear, setTear] = useState<number>();
  return (
    <View style={{ backgroundColor: brand.paper, borderRadius: radius.xl }}>
      <View onLayout={(e) => setTear(e.nativeEvent.layout.height)} style={{ padding: space[5], paddingBottom: space[4], gap: 4 }}>
        {top}
      </View>
      <View style={{ marginHorizontal: space[4], borderTopWidth: 2, borderStyle: 'dashed', borderColor: 'rgba(11,11,11,0.25)' }} />
      <View style={{ padding: space[5], paddingTop: space[4] }}>{bottom}</View>
      {tear !== undefined ? (
        <>
          <View pointerEvents="none" style={{ position: 'absolute', left: -11, top: tear - 10, width: 22, height: 22, borderRadius: 11, backgroundColor: p.ground }} />
          <View pointerEvents="none" style={{ position: 'absolute', right: -11, top: tear - 10, width: 22, height: 22, borderRadius: 11, backgroundColor: p.ground }} />
        </>
      ) : null}
    </View>
  );
}
