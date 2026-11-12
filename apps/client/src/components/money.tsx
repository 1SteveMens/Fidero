import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Animated, Easing, Platform, Pressable, ScrollView, View, type NativeScrollEvent, type NativeSyntheticEvent } from 'react-native';
import { router } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import Svg, { Circle, Defs, Path, Text as SvgText, TextPath } from 'react-native-svg';
import { formatMoney, type HeldAccount, type Money } from '@fidero/shared';
import { brand, font, radius, space } from '@fidero/tokens';
import { usePalette, useReducedMotion } from '../theme';
import { Label, T, haptic } from './ui';

const nativeDriver = Platform.OS !== 'web';
const CARD_W = 300;
const CARD_H = 190;
const GAP = 12;

/** The round seal on every account card. Its words turn slowly; the check stays still. */
export function Seal({ id, ring, text, check, size = 132 }: { id: string; ring: string; text: string; check: string; size?: number }) {
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
            <TextPath href={`#${id}`}>HELD AT THE BANK · RELEASED ON PROOF · </TextPath>
          </SvgText>
        </Svg>
      </Animated.View>
      <Svg width={size} height={size} viewBox="0 0 120 120" style={{ position: 'absolute' }}>
        <Path d="M49 61l7 7 15-16" fill="none" stroke={check} strokeWidth={4} strokeLinecap="round" strokeLinejoin="round" />
      </Svg>
    </View>
  );
}

const CARD_STYLES = [
  { bg: brand.ink, fg: '#F7F6F2', sub: '#A9A69E', strip: '#1A1A1A', bank: brand.lime, ring: '#262626', seal: '#55534D', check: brand.lime },
  { bg: brand.lime, fg: brand.ink, sub: '#3F5A1F', strip: '#8FDB47', bank: brand.ink, ring: '#86C94A', seal: '#3F5A1F', check: brand.ink },
];

function AccountCard({ account, holder, index }: { account: HeldAccount; holder: string; index: number }) {
  const s = CARD_STYLES[index % CARD_STYLES.length];
  const reduced = useReducedMotion();
  const enter = useRef(new Animated.Value(reduced ? 1 : 0)).current;
  useEffect(() => {
    if (reduced) return;
    Animated.timing(enter, { toValue: 1, duration: 800, delay: 100 + index * 380, easing: Easing.out(Easing.cubic), useNativeDriver: nativeDriver }).start();
  }, [enter, index, reduced]);
  const kind = account.kind === 'escrow' ? 'Escrow' : 'Family';
  return (
    <Animated.View
      style={{
        opacity: enter,
        transform: index === 0
          ? [{ perspective: 900 }, { rotateX: enter.interpolate({ inputRange: [0, 1], outputRange: ['24deg', '0deg'] }) }, { translateY: enter.interpolate({ inputRange: [0, 1], outputRange: [30, 0] }) }]
          : [{ translateX: enter.interpolate({ inputRange: [0, 1], outputRange: [80, 0] }) }],
      }}
    >
      <Pressable
        onPress={() => {
          haptic('tap');
          router.push(account.href as never);
        }}
        accessibilityRole="button"
        accessibilityLabel={`${kind} account. ${account.label}. ${formatMoney(account.held)} held by ${account.heldAt}.`}
        style={({ pressed }) => ({
          width: CARD_W,
          height: CARD_H,
          borderRadius: radius.xl,
          backgroundColor: s.bg,
          overflow: 'hidden',
          transform: [{ scale: pressed ? 0.98 : 1 }],
          shadowColor: '#000',
          shadowOpacity: 0.2,
          shadowRadius: 16,
          shadowOffset: { width: 0, height: 10 },
          elevation: 6,
        })}
      >
        <View style={{ position: 'absolute', right: -26, top: -36 }}>
          <Seal id={`seal-${account.id}`} ring={s.ring} text={s.seal} check={s.check} />
        </View>
        <View style={{ height: CARD_H - 54, paddingHorizontal: space[5], paddingTop: space[4], justifyContent: 'space-between' }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[2] }}>
            <T v="headline" color={s.fg} style={{ fontFamily: font.heavy, fontSize: 19, letterSpacing: -0.8 }}>fidero</T>
            <Label color={s.sub} style={{ fontSize: 10 }}>{`${kind} · ${account.bankRef}`}</Label>
          </View>
          <View>
            <Label color={s.sub} style={{ fontSize: 10 }}>{account.label}</Label>
            <T v="amount" color={s.fg} style={{ fontSize: 30, lineHeight: 36 }}>{formatMoney(account.held)}</T>
          </View>
        </View>
        <View style={{ position: 'absolute', left: 0, right: 0, bottom: 0, height: 54, paddingHorizontal: space[5], backgroundColor: s.strip, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
          <Label color={s.fg}>{holder}</Label>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <Ionicons name="business" size={14} color={s.bank} />
            <Label color={s.bank}>{account.heldAt}</Label>
          </View>
        </View>
      </Pressable>
    </Animated.View>
  );
}

/** Each account the bank holds, side by side. The next card peeks in from the right. */
export function AccountCards({ accounts, holder, total }: { accounts: HeldAccount[]; holder: string; total: Money }) {
  const p = usePalette();
  const [page, setPage] = useState(0);
  const onScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) => setPage(Math.round(e.nativeEvent.contentOffset.x / (CARD_W + GAP)));
  return (
    <View style={{ gap: space[3] }} accessibilityLabel={`Money held for you: ${accounts.length} accounts, ${formatMoney(total)} in total.`}>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        snapToInterval={CARD_W + GAP}
        decelerationRate="fast"
        onScroll={onScroll}
        scrollEventThrottle={32}
        style={{ marginHorizontal: -space[5], overflow: 'visible' }}
        contentContainerStyle={{ paddingHorizontal: space[5], paddingVertical: space[2], gap: GAP }}
      >
        {accounts.map((a, i) => (
          <AccountCard key={a.id} account={a} holder={holder} index={i} />
        ))}
      </ScrollView>
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 4 }}>
        <View style={{ flexDirection: 'row', gap: 5 }} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
          {accounts.map((a, i) => (
            <View key={a.id} style={{ width: i === page ? 18 : 6, height: 6, borderRadius: 3, backgroundColor: i === page ? p.text : p.lineStrong }} />
          ))}
        </View>
        <T v="footnote" muted>
          Total held <T v="footnote" style={{ fontFamily: font.bold }}>{formatMoney(total)}</T> · {accounts.length} accounts
        </T>
      </View>
    </View>
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
