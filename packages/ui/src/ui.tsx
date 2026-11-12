import { useEffect, useRef, type ComponentRef, type ReactNode } from 'react';
import {
  ActivityIndicator,
  Animated,
  Easing,
  Platform,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
  type StyleProp,
  type TextStyle,
  type ViewStyle,
} from 'react-native';
import { router } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import * as Haptics from 'expo-haptics';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, minTouch, radius, space, type, type Ground } from '@tenmina/tokens';
import type { CaseStep, Verdict } from '@tenmina/shared';
import { GroundContext, useGround, usePalette, useReducedMotion } from './theme';

export type IconName = keyof typeof Ionicons.glyphMap;
const nativeDriver = Platform.OS !== 'web';

export function haptic(kind: 'success' | 'warning' | 'tap' | 'heavy') {
  if (Platform.OS === 'web') return;
  if (kind === 'tap') void Haptics.selectionAsync();
  else if (kind === 'heavy') void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
  else
    void Haptics.notificationAsync(
      kind === 'success' ? Haptics.NotificationFeedbackType.Success : Haptics.NotificationFeedbackType.Warning,
    );
}

/* ---------- Text ---------- */

type Variant = keyof typeof type;

export function T({
  v = 'body',
  color,
  muted,
  style,
  children,
  header,
  numberOfLines,
}: {
  v?: Variant;
  color?: string;
  muted?: boolean;
  style?: StyleProp<TextStyle>;
  children: ReactNode;
  header?: boolean;
  numberOfLines?: number;
}) {
  const p = usePalette();
  return (
    <Text
      accessibilityRole={header ? 'header' : undefined}
      numberOfLines={numberOfLines}
      style={[type[v], { color: color ?? (muted ? p.textMuted : p.text) }, style]}
    >
      {children}
    </Text>
  );
}

/** Mono uppercase label for references, dates and section tags. */
export function Label({ children, color, style }: { children: ReactNode; color?: string; style?: StyleProp<TextStyle> }) {
  const p = usePalette();
  return <Text style={[type.label, { color: color ?? p.textMuted, textTransform: 'uppercase' }, style]}>{children}</Text>;
}

export function Muted({ children }: { children: ReactNode }) {
  return <T v="footnote" muted>{children}</T>;
}

/* ---------- Motion ---------- */

/** Content rises into place. Skipped when the phone asks for less motion. */
export function Rise({ children, delay = 0, style }: { children: ReactNode; delay?: number; style?: StyleProp<ViewStyle> }) {
  const reduced = useReducedMotion();
  const v = useRef(new Animated.Value(reduced ? 1 : 0)).current;
  useEffect(() => {
    if (reduced) {
      v.setValue(1);
      return;
    }
    Animated.timing(v, { toValue: 1, duration: 520, delay, easing: Easing.out(Easing.cubic), useNativeDriver: nativeDriver }).start();
  }, [reduced, delay, v]);
  return (
    <Animated.View style={[{ opacity: v, transform: [{ translateY: v.interpolate({ inputRange: [0, 1], outputRange: [18, 0] }) }] }, style]}>
      {children}
    </Animated.View>
  );
}

/** A soft orange pulse for the one thing that needs the client. */
export function Pulse({ children, size, radius: r, color = brand.orange }: { children?: ReactNode; size: number; radius: number; color?: string }) {
  const reduced = useReducedMotion();
  const v = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (reduced) return;
    const loop = Animated.loop(Animated.timing(v, { toValue: 1, duration: 1800, easing: Easing.out(Easing.quad), useNativeDriver: nativeDriver }));
    loop.start();
    return () => loop.stop();
  }, [reduced, v]);
  return (
    <View style={{ width: size, height: size }}>
      {!reduced ? (
        <Animated.View
          pointerEvents="none"
          style={{
            position: 'absolute',
            inset: 0,
            borderRadius: r,
            backgroundColor: color,
            opacity: v.interpolate({ inputRange: [0, 1], outputRange: [0.55, 0] }),
            transform: [{ scale: v.interpolate({ inputRange: [0, 1], outputRange: [1, 1.7] }) }],
          }}
        />
      ) : null}
      <View style={{ width: size, height: size, borderRadius: r, backgroundColor: color, alignItems: 'center', justifyContent: 'center' }}>{children}</View>
    </View>
  );
}

/* ---------- Screen ---------- */

/** A Bloc screen: black or white ground, big title, optional back button and fixed footer. */
export function Screen({
  ground = 'paper',
  title,
  eyebrow,
  trailing,
  back,
  tabs,
  footer,
  children,
}: {
  ground?: Ground;
  title?: string;
  eyebrow?: string;
  trailing?: ReactNode;
  back?: boolean;
  tabs?: boolean;
  footer?: ReactNode;
  children: ReactNode;
}) {
  const g = useGround(ground);
  const p = usePalette(g);
  const insets = useSafeAreaInsets();
  return (
    <GroundContext.Provider value={g}>
      <View style={{ flex: 1, backgroundColor: p.ground }}>
        <ScrollView
          style={{ flex: 1 }}
          contentContainerStyle={{
            paddingTop: insets.top + space[3],
            paddingBottom: (tabs ? 100 : space[6]) + (footer ? 0 : insets.bottom),
            paddingHorizontal: space[5],
            gap: space[4],
          }}
          contentInsetAdjustmentBehavior="never"
          showsVerticalScrollIndicator={false}
        >
          {back || title || eyebrow || trailing ? (
            <Rise>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[3], minHeight: minTouch }}>
                {back ? <IconButton icon="chevron-back" label="Back" onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))} /> : null}
                <View style={{ flex: 1 }}>
                  {eyebrow ? <Label>{eyebrow}</Label> : null}
                  {title ? (
                    <T v={back ? 'title' : 'largeTitle'} header numberOfLines={2}>
                      {title}
                    </T>
                  ) : null}
                </View>
                {trailing}
              </View>
            </Rise>
          ) : null}
          {children}
        </ScrollView>
        {footer ? <View style={{ paddingHorizontal: space[5], paddingTop: space[3], paddingBottom: insets.bottom + space[3], gap: space[2], backgroundColor: p.ground }}>{footer}</View> : null}
      </View>
    </GroundContext.Provider>
  );
}

export function IconButton({ icon, label, onPress, tone = 'surface' }: { icon: IconName; label: string; onPress: () => void; tone?: 'surface' | 'lime' }) {
  const p = usePalette();
  const bg = tone === 'lime' ? brand.lime : p.surface;
  const fg = tone === 'lime' ? brand.ink : p.text;
  return (
    <Pressable
      onPress={() => {
        haptic('tap');
        onPress();
      }}
      accessibilityRole="button"
      accessibilityLabel={label}
      hitSlop={6}
      style={({ pressed }) => ({ width: minTouch, height: minTouch, borderRadius: radius.md, backgroundColor: bg, alignItems: 'center', justifyContent: 'center', opacity: pressed ? 0.75 : 1 })}
    >
      <Ionicons name={icon} size={22} color={fg} />
    </Pressable>
  );
}

/* ---------- Surfaces ---------- */

export type PanelTone = 'surface' | 'raised' | 'lime' | 'orange' | 'amber' | 'red' | 'ground';

export function usePanelColors(tone: PanelTone) {
  const p = usePalette();
  switch (tone) {
    case 'raised':
      return { bg: p.raised, fg: p.onRaised, muted: p.raised === brand.ink ? '#A9A69E' : '#6A675F' };
    case 'lime':
      return { bg: brand.lime, fg: brand.ink, muted: '#3F5A1F' };
    case 'orange':
      return { bg: brand.orange, fg: brand.ink, muted: '#4A1A0A' };
    case 'amber':
      return { bg: brand.amber, fg: brand.ink, muted: '#5A4E10' };
    case 'red':
      return { bg: brand.red, fg: brand.ink, muted: '#4A0E0A' };
    case 'ground':
      return { bg: p.ground, fg: p.text, muted: p.textMuted };
    default:
      return { bg: p.surface, fg: p.text, muted: p.textMuted };
  }
}

export function Panel({
  tone = 'surface',
  onPress,
  children,
  style,
  accessibilityLabel,
}: {
  tone?: PanelTone;
  onPress?: () => void;
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
  accessibilityLabel?: string;
}) {
  const c = usePanelColors(tone);
  const base: ViewStyle = { backgroundColor: c.bg, borderRadius: radius.xl, padding: space[4], gap: space[3] };
  if (!onPress) return <View style={[base, style]}>{children}</View>;
  return (
    <Pressable
      onPress={() => {
        haptic('tap');
        onPress();
      }}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      style={({ pressed }) => [base, { opacity: pressed ? 0.9 : 1, transform: [{ scale: pressed ? 0.985 : 1 }] }, style]}
    >
      {children}
    </Pressable>
  );
}

/** A square icon block. Black with a lime icon is the default Bloc mark. */
export function IconTile({ name, tone = 'ink', size = 40 }: { name: IconName; tone?: 'ink' | 'lime' | 'orange' | 'surface' | 'paper'; size?: number }) {
  const p = usePalette();
  const map = {
    ink: { bg: brand.ink, fg: brand.lime },
    lime: { bg: brand.lime, fg: brand.ink },
    orange: { bg: brand.orange, fg: brand.ink },
    surface: { bg: p.surface, fg: p.text },
    paper: { bg: brand.paper, fg: brand.ink },
  }[tone];
  return (
    <View style={{ width: size, height: size, borderRadius: size * 0.3, backgroundColor: map.bg, alignItems: 'center', justifyContent: 'center' }}>
      <Ionicons name={name} size={size * 0.5} color={map.fg} />
    </View>
  );
}

/** Black square with an arrow, used at the end of anything that opens. */
export function ArrowBox({ color = brand.ink, arrow = brand.lime }: { color?: string; arrow?: string }) {
  return (
    <View style={{ width: 44, height: 44, borderRadius: radius.md, backgroundColor: color, alignItems: 'center', justifyContent: 'center' }}>
      <Ionicons name="arrow-forward" size={20} color={arrow} />
    </View>
  );
}

export type ChipTone = 'lime' | 'orange' | 'amber' | 'red' | 'ink' | 'paper' | 'surface';

export function Chip({ label, tone = 'surface', icon }: { label: string; tone?: ChipTone; icon?: IconName }) {
  const p = usePalette();
  const map = {
    lime: { bg: brand.lime, fg: brand.ink },
    orange: { bg: brand.orange, fg: brand.ink },
    amber: { bg: brand.amber, fg: brand.ink },
    red: { bg: brand.red, fg: brand.ink },
    ink: { bg: brand.ink, fg: brand.lime },
    paper: { bg: brand.paper, fg: brand.ink },
    surface: { bg: p.surface, fg: p.text },
  }[tone];
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4, backgroundColor: map.bg, borderRadius: radius.sm, paddingHorizontal: 9, paddingVertical: 4 }}>
      {icon ? <Ionicons name={icon} size={13} color={map.fg} /> : null}
      <Text style={[type.footnote, { fontFamily: type.headline.fontFamily, fontSize: 12, lineHeight: 16, color: map.fg }]}>{label}</Text>
    </View>
  );
}

/** A verdict is never colour alone: word, icon and colour together (03 section 5). */
export function VerdictChip({ verdict, suffix }: { verdict: Verdict; suffix?: string }) {
  const map = {
    green: { tone: 'lime' as ChipTone, icon: 'checkmark' as IconName, word: 'Green' },
    amber: { tone: 'amber' as ChipTone, icon: 'alert' as IconName, word: 'Amber' },
    red: { tone: 'red' as ChipTone, icon: 'close' as IconName, word: 'Red' },
  }[verdict];
  return <Chip tone={map.tone} icon={map.icon} label={suffix ? `${map.word} ${suffix}` : map.word} />;
}

export function Tick({ ok = true, size = 22 }: { ok?: boolean; size?: number }) {
  return (
    <View style={{ width: size, height: size, borderRadius: size * 0.32, backgroundColor: ok ? brand.lime : brand.red, alignItems: 'center', justifyContent: 'center' }}>
      <Ionicons name={ok ? 'checkmark' : 'close'} size={size * 0.66} color={brand.ink} />
    </View>
  );
}

/** A row inside a panel: icon, title, detail and something on the right. */
export function ListRow({
  icon,
  iconTone,
  title,
  detail,
  trailing,
  onPress,
  last,
}: {
  icon?: IconName;
  iconTone?: 'ink' | 'lime' | 'orange' | 'surface' | 'paper';
  title: string;
  detail?: string;
  trailing?: ReactNode;
  onPress?: () => void;
  last?: boolean;
}) {
  const p = usePalette();
  const body = (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[3], minHeight: 52, paddingVertical: space[2], borderBottomWidth: last ? 0 : 1, borderBottomColor: p.line }}>
      {icon ? <IconTile name={icon} tone={iconTone} size={38} /> : null}
      <View style={{ flex: 1, gap: 1 }}>
        <T v="headline" style={{ fontSize: 15 }}>{title}</T>
        {detail ? <T v="footnote" muted>{detail}</T> : null}
      </View>
      {trailing}
      {onPress && !trailing ? <Ionicons name="chevron-forward" size={18} color={p.textMuted} /> : null}
    </View>
  );
  if (!onPress) return <View accessible accessibilityLabel={detail ? `${title}. ${detail}` : title}>{body}</View>;
  return (
    <Pressable
      onPress={() => {
        haptic('tap');
        onPress();
      }}
      accessibilityRole="button"
      accessibilityLabel={detail ? `${title}. ${detail}` : title}
      style={({ pressed }) => ({ opacity: pressed ? 0.7 : 1 })}
    >
      {body}
    </Pressable>
  );
}

/** The orange card for something only the client can do. */
export function NeedsYou({ title, detail, count, onPress }: { title: string; detail?: string; count?: number; onPress: () => void }) {
  return (
    <Panel tone="orange" onPress={onPress} accessibilityLabel={`Needs you. ${title}. ${detail ?? ''}`} style={{ flexDirection: 'row', alignItems: 'center', gap: space[3], paddingVertical: space[4] }}>
      <View style={{ flex: 1, gap: 4 }}>
        <Label color={brand.ink}>{count && count > 1 ? `Needs you · ${count}` : 'Needs you'}</Label>
        <T v="headline" color={brand.ink} style={{ fontSize: 18, lineHeight: 23 }}>{title}</T>
        {detail ? <T v="footnote" color="#3A1408">{detail}</T> : null}
      </View>
      <ArrowBox arrow={brand.orange} />
    </Panel>
  );
}

/* ---------- Progress ---------- */

export function SegBar({ done, total, current = true, onDark }: { done: number; total: number; current?: boolean; onDark?: boolean }) {
  const p = usePalette();
  return (
    <View accessibilityRole="progressbar" accessibilityValue={{ min: 0, max: total, now: done }} style={{ flexDirection: 'row', gap: 4 }}>
      {Array.from({ length: total }, (_, i) => (
        <View
          key={i}
          style={{
            flex: 1,
            height: 8,
            borderRadius: 4,
            backgroundColor: i < done ? (onDark ? brand.lime : brand.ink) : i === done && current ? brand.orange : onDark ? '#2C2C2C' : p.lineStrong,
          }}
        />
      ))}
    </View>
  );
}

/** The vertical step trail used for a case: black ticks, an orange "now". */
export function StepTrail({ steps, onStep }: { steps: CaseStep[]; onStep?: (s: CaseStep) => (() => void) | undefined }) {
  const p = usePalette();
  return (
    <View>
      {steps.map((s, i) => {
        const last = i === steps.length - 1;
        const press = onStep?.(s);
        const marker =
          s.state === 'done' ? (
            <View style={{ width: 26, height: 26, borderRadius: 8, backgroundColor: p.text, alignItems: 'center', justifyContent: 'center' }}>
              <Ionicons name="checkmark" size={15} color={p.ground === brand.ink ? brand.ink : brand.lime} />
            </View>
          ) : s.state === 'current' ? (
            <Pulse size={26} radius={8}>
              <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: brand.ink }} />
            </Pulse>
          ) : (
            <View style={{ width: 26, height: 26, borderRadius: 8, borderWidth: 2, borderColor: p.lineStrong }} />
          );
        const content = (
          <View style={{ flex: 1, paddingBottom: last ? 0 : space[4], gap: 2 }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[2], flexWrap: 'wrap' }}>
              <T v="headline" style={{ fontSize: 16, textDecorationLine: press ? 'underline' : 'none' }} muted={s.state === 'upcoming'}>
                {s.title}
              </T>
              {s.state === 'current' ? <Chip tone="orange" label="Now" /> : null}
            </View>
            {s.detail ? <T v="footnote" muted>{s.detail}</T> : null}
          </View>
        );
        return (
          <Rise key={s.id} delay={80 + i * 60}>
            <View
              style={{ flexDirection: 'row', gap: space[3] }}
              accessible={!press}
              accessibilityLabel={`${s.title}. ${s.state === 'done' ? 'Done' : s.state === 'current' ? 'Now' : 'Later'}. ${s.detail ?? ''}`}
            >
              <View style={{ alignItems: 'center' }}>
                {marker}
                {!last ? <View style={{ width: 2, flex: 1, minHeight: 14, backgroundColor: s.state === 'done' ? p.text : p.lineStrong }} /> : null}
              </View>
              {press ? (
                <Pressable onPress={press} accessibilityRole="link" style={{ flex: 1 }}>
                  {content}
                </Pressable>
              ) : (
                content
              )}
            </View>
          </Rise>
        );
      })}
    </View>
  );
}

/** Horizontal dot stepper for errands: ticks, an orange "now", empty circles. */
export function DotStepper({ labels, done }: { labels: string[]; done: number }) {
  const p = usePalette();
  const n = labels.length;
  return (
    <View accessibilityRole="progressbar" accessibilityValue={{ min: 0, max: n, now: done }}>
      <View style={{ position: 'absolute', left: `${50 / n}%`, right: `${50 / n}%`, top: 12, height: 2, backgroundColor: p.lineStrong }} />
      <View style={{ position: 'absolute', left: `${50 / n}%`, width: `${(done / n) * 100}%`, top: 12, height: 2, backgroundColor: p.text }} />
      <View style={{ flexDirection: 'row' }}>
        {labels.map((l, i) => (
          <View key={l} style={{ flex: 1, alignItems: 'center', gap: 6 }}>
            {i < done ? (
              <View style={{ width: 26, height: 26, borderRadius: 13, backgroundColor: p.text, alignItems: 'center', justifyContent: 'center' }}>
                <Ionicons name="checkmark" size={14} color={p.ground === brand.ink ? brand.ink : brand.lime} />
              </View>
            ) : i === done ? (
              <Pulse size={26} radius={13}>
                <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: brand.ink }} />
              </Pulse>
            ) : (
              <View style={{ width: 26, height: 26, borderRadius: 13, backgroundColor: p.ground, borderWidth: 2, borderColor: p.lineStrong }} />
            )}
            <Label color={i <= done ? p.text : p.textMuted} style={{ fontSize: 9, letterSpacing: 0.5 }}>{l}</Label>
          </View>
        ))}
      </View>
    </View>
  );
}

/* ---------- Buttons ---------- */

export function Button({
  title,
  onPress,
  variant = 'primary',
  disabled,
  loading,
  icon,
}: {
  title: string;
  onPress: () => void;
  variant?: 'primary' | 'dark' | 'quiet' | 'danger';
  disabled?: boolean;
  loading?: boolean;
  icon?: IconName;
}) {
  const p = usePalette();
  const s = {
    primary: { bg: brand.lime, fg: brand.ink },
    dark: { bg: p.raised, fg: p.onRaised },
    quiet: { bg: 'transparent', fg: p.text },
    // Orange text is only 2.8:1 on white, so on a paper ground danger is an orange block with black text.
    danger: p.ground === brand.ink ? { bg: 'transparent', fg: brand.orange } : { bg: brand.orange, fg: brand.ink },
  }[variant];
  const slim = variant === 'quiet' || (variant === 'danger' && p.ground === brand.ink);
  const off = disabled || loading;
  return (
    <Pressable
      onPress={() => {
        haptic('tap');
        onPress();
      }}
      disabled={off}
      accessibilityRole="button"
      accessibilityState={{ disabled: !!off, busy: !!loading }}
      style={({ pressed }) => ({
        minHeight: slim ? 46 : 60,
        borderRadius: 18,
        backgroundColor: s.bg,
        opacity: off ? 0.4 : pressed ? 0.85 : 1,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        gap: space[2],
        paddingHorizontal: space[5],
      })}
    >
      {loading ? <ActivityIndicator color={s.fg} /> : icon ? <Ionicons name={icon} size={20} color={s.fg} /> : null}
      <T v="headline" color={s.fg} style={{ fontSize: slim ? 15 : 17 }}>{title}</T>
    </Pressable>
  );
}

/**
 * Press and hold to approve. Holding is deliberate, so money never moves by a stray tap.
 * With a screen reader on, a double tap approves, since holding is hard to do there.
 */
export function HoldButton({
  label,
  onConfirm,
  disabled,
  loading,
  holdMs,
  screenReader,
}: {
  label: string;
  onConfirm: () => void;
  disabled?: boolean;
  loading?: boolean;
  holdMs: number;
  screenReader: boolean;
}) {
  const fill = useRef(new Animated.Value(0)).current;
  const off = disabled || loading;

  function start() {
    if (off || screenReader) return;
    haptic('tap');
    Animated.timing(fill, { toValue: 1, duration: holdMs, easing: Easing.linear, useNativeDriver: nativeDriver }).start(({ finished }) => {
      if (finished) {
        haptic('heavy');
        onConfirm();
        fill.setValue(0);
      }
    });
  }
  function cancel() {
    fill.stopAnimation();
    Animated.timing(fill, { toValue: 0, duration: 180, useNativeDriver: nativeDriver }).start();
  }

  return (
    <Pressable
      onPressIn={start}
      onPressOut={cancel}
      onPress={screenReader && !off ? onConfirm : undefined}
      disabled={off}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityHint={screenReader ? 'Double tap to approve.' : 'Press and hold to approve.'}
      accessibilityState={{ disabled: !!off, busy: !!loading }}
      style={{ height: 64, borderRadius: 20, backgroundColor: brand.lime, overflow: 'hidden', opacity: off ? 0.4 : 1, justifyContent: 'center' }}
    >
      <Animated.View style={{ position: 'absolute', left: 0, right: 0, top: 0, bottom: 0, backgroundColor: brand.orange, transformOrigin: 'left', transform: [{ scaleX: fill }] }} />
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: space[2] }}>
        {loading ? <ActivityIndicator color={brand.ink} /> : <Ionicons name="finger-print" size={22} color={brand.ink} />}
        <T v="headline" color={brand.ink} style={{ fontSize: 17 }}>{screenReader ? label : `Press and hold to ${label.toLowerCase()}`}</T>
      </View>
    </Pressable>
  );
}

/** Six boxes over one hidden input, so paste and one-time-code autofill still work. */
export function CodeField({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  const p = usePalette();
  const input = useRef<ComponentRef<typeof TextInput>>(null);
  const digits = value.padEnd(6, ' ').slice(0, 6).split('');
  return (
    <Pressable onPress={() => input.current?.focus()} accessibilityLabel={label} style={{ gap: space[2] }}>
      <T v="footnote" muted>{label}</T>
      <View style={{ flexDirection: 'row', gap: space[2] }}>
        {digits.map((d, i) => {
          const filled = d.trim() !== '';
          const active = i === Math.min(value.length, 5) && value.length < 6;
          return (
            <View
              key={i}
              style={{
                flex: 1,
                height: 56,
                borderRadius: radius.md,
                backgroundColor: p.surface,
                borderWidth: 2,
                borderColor: filled ? brand.lime : active ? p.text : p.line,
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <T v="title" style={{ fontVariant: ['tabular-nums'] }}>{d.trim()}</T>
            </View>
          );
        })}
      </View>
      <TextInput
        ref={input}
        value={value}
        onChangeText={(t) => onChange(t.replace(/\D/g, '').slice(0, 6))}
        keyboardType="number-pad"
        textContentType="oneTimeCode"
        autoComplete="one-time-code"
        maxLength={6}
        accessibilityLabel={label}
        style={{ position: 'absolute', opacity: 0.01, height: 56, width: '100%', top: 26 }}
      />
    </Pressable>
  );
}

/** A labelled text input in the Bloc style. */
export function Input({
  label,
  value,
  onChange,
  placeholder,
  multiline,
  keyboardType,
  hint,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  multiline?: boolean;
  keyboardType?: 'default' | 'number-pad' | 'decimal-pad';
  hint?: string;
}) {
  const p = usePalette();
  return (
    <View style={{ gap: 6 }}>
      <T v="footnote" style={{ fontFamily: type.headline.fontFamily, fontSize: 14 }}>{label}</T>
      <TextInput
        value={value}
        onChangeText={onChange}
        placeholder={placeholder}
        placeholderTextColor={p.textMuted}
        multiline={multiline}
        keyboardType={keyboardType}
        accessibilityLabel={label}
        style={[
          type.body,
          {
            color: p.text,
            backgroundColor: p.ground === brand.ink ? p.surface : brand.paper,
            borderWidth: 2,
            borderColor: p.ground === brand.ink ? '#77746D' : '#858178',
            borderRadius: radius.md,
            paddingHorizontal: space[3],
            paddingVertical: space[3],
            minHeight: multiline ? 88 : 50,
            textAlignVertical: multiline ? 'top' : 'center',
          },
        ]}
      />
      {hint ? <T v="footnote" muted>{hint}</T> : null}
    </View>
  );
}

/** Two big answer blocks, sized for outdoor use (03 section 6.1c). */
export function YesNo({ value, onChange, label }: { value?: 'yes' | 'no'; onChange: (v: 'yes' | 'no') => void; label: string }) {
  const p = usePalette();
  const opt = (v: 'yes' | 'no', text: string) => {
    const on = value === v;
    return (
      <Pressable
        key={v}
        onPress={() => {
          haptic('tap');
          onChange(v);
        }}
        accessibilityRole="radio"
        accessibilityState={{ selected: on }}
        accessibilityLabel={`${label}: ${text}`}
        style={({ pressed }) => ({
          width: 58,
          height: 44,
          borderRadius: 12,
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: on ? brand.ink : p.ground,
          borderWidth: on ? 0 : 2,
          borderColor: p.lineStrong,
          opacity: pressed ? 0.8 : 1,
        })}
      >
        <T v="headline" color={on ? (v === 'yes' ? brand.lime : '#F7F6F2') : p.text} style={{ fontSize: 15 }}>{text}</T>
      </Pressable>
    );
  };
  return <View accessibilityRole="radiogroup" style={{ flexDirection: 'row', gap: 6 }}>{[opt('yes', 'Yes'), opt('no', 'No')]}</View>;
}

/** One choice in a group of options, as a full-width row. */
export function Choice({ selected, onPress, title, detail }: { selected: boolean; onPress: () => void; title: string; detail?: string }) {
  const p = usePalette();
  return (
    <Pressable
      onPress={() => {
        haptic('tap');
        onPress();
      }}
      accessibilityRole="radio"
      accessibilityState={{ selected }}
      accessibilityLabel={detail ? `${title}. ${detail}` : title}
      style={({ pressed }) => ({ flexDirection: 'row', gap: space[3], alignItems: 'center', paddingVertical: space[2], opacity: pressed ? 0.8 : 1 })}
    >
      <View style={{ width: 24, height: 24, borderRadius: 12, borderWidth: 2, borderColor: p.text, alignItems: 'center', justifyContent: 'center' }}>
        {selected ? <View style={{ width: 12, height: 12, borderRadius: 6, backgroundColor: p.text }} /> : null}
      </View>
      <View style={{ flex: 1 }}>
        <T v="headline" style={{ fontSize: 15, fontFamily: selected ? type.headline.fontFamily : type.callout.fontFamily }}>{title}</T>
        {detail ? <T v="footnote" muted>{detail}</T> : null}
      </View>
    </Pressable>
  );
}

/* ---------- States ---------- */

export function Loading() {
  const p = usePalette();
  return (
    <View style={{ gap: space[3] }} accessibilityLabel="Loading">
      {[180, 72, 72].map((h, i) => (
        <View key={i} style={{ height: h, borderRadius: radius.xl, backgroundColor: p.surface }} />
      ))}
    </View>
  );
}

export function ErrorView({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <Panel>
      <T v="headline">We could not load this</T>
      <T v="callout" muted>{message}</T>
      <Button title="Try again" variant="dark" onPress={onRetry} />
    </Panel>
  );
}
