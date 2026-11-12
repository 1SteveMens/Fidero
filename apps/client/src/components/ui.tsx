import { useRef, type ComponentRef, type ReactNode } from 'react';
import {
  ActivityIndicator,
  Platform,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { LinearGradient } from 'expo-linear-gradient';
import * as Haptics from 'expo-haptics';
import Ionicons from '@expo/vector-icons/Ionicons';
import { hero, minTouch, radius, space, type } from '@fidero/tokens';
import type { Verdict } from '@fidero/shared';
import { usePalette } from '../theme';

type IconName = keyof typeof Ionicons.glyphMap;

export function haptic(kind: 'success' | 'warning' | 'tap') {
  if (Platform.OS === 'web') return;
  if (kind === 'tap') void Haptics.selectionAsync();
  else
    void Haptics.notificationAsync(
      kind === 'success' ? Haptics.NotificationFeedbackType.Success : Haptics.NotificationFeedbackType.Warning,
    );
}

/** A scrolling screen with an in-content large title, the current iOS and Material pattern. */
export function Screen({
  title,
  subtitle,
  children,
  trailing,
  topInset = true,
}: {
  title?: string;
  subtitle?: string;
  children: ReactNode;
  trailing?: ReactNode;
  topInset?: boolean;
}) {
  const p = usePalette();
  const insets = useSafeAreaInsets();
  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: p.bg }}
      contentContainerStyle={{
        paddingTop: (topInset ? insets.top : 0) + space[4],
        paddingBottom: insets.bottom + 96,
        paddingHorizontal: space[5],
        gap: space[5],
      }}
      contentInsetAdjustmentBehavior="never"
    >
      {title ? (
        <View style={{ flexDirection: 'row', alignItems: 'flex-end', gap: space[3] }}>
          <View style={{ flex: 1 }}>
            {subtitle ? <Text style={[type.footnote, { color: p.textMuted, fontWeight: '600' }]}>{subtitle}</Text> : null}
            <Text accessibilityRole="header" style={[type.largeTitle, { color: p.text, letterSpacing: -0.5 }]}>
              {title}
            </Text>
          </View>
          {trailing}
        </View>
      ) : null}
      {children}
    </ScrollView>
  );
}

export function Card({
  children,
  onPress,
  style,
  accessibilityLabel,
}: {
  children: ReactNode;
  onPress?: () => void;
  style?: StyleProp<ViewStyle>;
  accessibilityLabel?: string;
}) {
  const p = usePalette();
  const base: ViewStyle = {
    backgroundColor: p.surface,
    borderRadius: radius.lg,
    padding: space[4],
    shadowColor: p.shadow,
    shadowOpacity: 1,
    shadowRadius: 16,
    shadowOffset: { width: 0, height: 6 },
    elevation: 2,
  };
  if (!onPress) return <View style={[base, style]}>{children}</View>;
  return (
    <Pressable
      onPress={() => {
        haptic('tap');
        onPress();
      }}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      style={({ pressed }) => [base, { opacity: pressed ? 0.85 : 1, transform: [{ scale: pressed ? 0.99 : 1 }] }, style]}
    >
      {children}
    </Pressable>
  );
}

export function SectionHeader({ title, count }: { title: string; count?: number }) {
  const p = usePalette();
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[2], marginBottom: -space[2] }}>
      <Text accessibilityRole="header" style={[type.title, { color: p.text, fontSize: 20 }]}>
        {title}
      </Text>
      {count !== undefined ? (
        <View style={{ backgroundColor: p.accent, borderRadius: radius.pill, minWidth: 22, height: 22, paddingHorizontal: 7, alignItems: 'center', justifyContent: 'center' }}>
          <Text style={[type.caption, { color: '#FFFFFF' }]}>{count}</Text>
        </View>
      ) : null}
    </View>
  );
}

/** Deep indigo hero used for money held at the bank. */
export function Hero({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return (
    <LinearGradient
      colors={[hero.from, hero.to]}
      start={{ x: 0, y: 0 }}
      end={{ x: 1, y: 1 }}
      style={[{ borderRadius: radius.xl, padding: space[5], gap: space[2] }, style]}
    >
      {children}
    </LinearGradient>
  );
}

export function IconBadge({ name, tone = 'primary' }: { name: IconName; tone?: Tone }) {
  const c = useTone(tone);
  return (
    <View style={{ width: 40, height: 40, borderRadius: radius.md, backgroundColor: c.bg, alignItems: 'center', justifyContent: 'center' }}>
      <Ionicons name={name} size={22} color={c.fg} />
    </View>
  );
}

export function Row({
  icon,
  tone,
  title,
  detail,
  onPress,
  trailing,
}: {
  icon?: IconName;
  tone?: Tone;
  title: string;
  detail?: string;
  onPress?: () => void;
  trailing?: ReactNode;
}) {
  const p = usePalette();
  return (
    <Card onPress={onPress} accessibilityLabel={detail ? `${title}. ${detail}` : title}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[3], minHeight: minTouch }}>
        {icon ? <IconBadge name={icon} tone={tone} /> : null}
        <View style={{ flex: 1, gap: 2 }}>
          <Text style={[type.headline, { color: p.text }]}>{title}</Text>
          {detail ? <Text style={[type.callout, { color: p.textMuted }]}>{detail}</Text> : null}
        </View>
        {trailing}
        {onPress ? <Ionicons name="chevron-forward" size={20} color={p.textMuted} /> : null}
      </View>
    </Card>
  );
}

export type Tone = 'primary' | 'success' | 'warning' | 'danger' | 'neutral';

function useTone(tone: Tone) {
  const p = usePalette();
  switch (tone) {
    case 'success':
      return { fg: p.success, bg: p.successSoft };
    case 'warning':
      return { fg: p.warning, bg: p.warningSoft };
    case 'danger':
      return { fg: p.danger, bg: p.dangerSoft };
    case 'neutral':
      return { fg: p.textMuted, bg: p.surfaceAlt };
    default:
      return { fg: p.primary, bg: p.primarySoft };
  }
}

export function Pill({ label, tone = 'neutral', icon, inline = false }: { label: string; tone?: Tone; icon?: IconName; inline?: boolean }) {
  const c = useTone(tone);
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4, alignSelf: inline ? 'center' : 'flex-start', backgroundColor: c.bg, borderRadius: radius.pill, paddingHorizontal: 10, paddingVertical: 5 }}>
      {icon ? <Ionicons name={icon} size={14} color={c.fg} /> : null}
      <Text style={[type.caption, { color: c.fg }]}>{label}</Text>
    </View>
  );
}

/** A verdict is never colour alone: icon, word and colour together (03 section 5). */
export function VerdictPill({ verdict }: { verdict: Verdict }) {
  const map = {
    green: { tone: 'success' as Tone, icon: 'checkmark-circle' as IconName, label: 'Green' },
    amber: { tone: 'warning' as Tone, icon: 'alert-circle' as IconName, label: 'Amber' },
    red: { tone: 'danger' as Tone, icon: 'close-circle' as IconName, label: 'Red' },
  }[verdict];
  return <Pill label={map.label} tone={map.tone} icon={map.icon} inline />;
}

export function ProgressBar({ value, tone = 'primary', onHero = false }: { value: number; tone?: Tone; onHero?: boolean }) {
  const c = useTone(tone);
  const p = usePalette();
  const pct = Math.max(0, Math.min(1, value));
  return (
    <View
      accessibilityRole="progressbar"
      accessibilityValue={{ min: 0, max: 100, now: Math.round(pct * 100) }}
      style={{ height: 6, borderRadius: 3, backgroundColor: onHero ? hero.chip : p.surfaceAlt, overflow: 'hidden' }}
    >
      <View style={{ width: `${pct * 100}%`, height: '100%', borderRadius: 3, backgroundColor: onHero ? '#FFFFFF' : c.fg }} />
    </View>
  );
}

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
  variant?: 'primary' | 'secondary' | 'quiet' | 'danger';
  disabled?: boolean;
  loading?: boolean;
  icon?: IconName;
}) {
  const p = usePalette();
  const styles = {
    primary: { bg: p.primary, fg: p.onPrimary },
    secondary: { bg: p.surfaceAlt, fg: p.text },
    quiet: { bg: 'transparent', fg: p.primary },
    danger: { bg: 'transparent', fg: p.danger },
  }[variant];
  const off = disabled || loading;
  return (
    <Pressable
      onPress={onPress}
      disabled={off}
      accessibilityRole="button"
      accessibilityState={{ disabled: !!off, busy: !!loading }}
      style={({ pressed }) => ({
        minHeight: 54,
        borderRadius: radius.md + 2,
        backgroundColor: styles.bg,
        opacity: off ? 0.45 : pressed ? 0.85 : 1,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        gap: space[2],
        paddingHorizontal: space[5],
      })}
    >
      {loading ? <ActivityIndicator color={styles.fg} /> : icon ? <Ionicons name={icon} size={20} color={styles.fg} /> : null}
      <Text style={[type.headline, { color: styles.fg }]}>{title}</Text>
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
      <Text style={[type.footnote, { color: p.textMuted, fontWeight: '600' }]}>{label}</Text>
      <View style={{ flexDirection: 'row', gap: space[2] }}>
        {digits.map((d, i) => (
          <View
            key={i}
            style={{
              flex: 1,
              height: 56,
              borderRadius: radius.sm + 2,
              backgroundColor: p.surfaceAlt,
              borderWidth: 2,
              borderColor: i === Math.min(value.length, 5) ? p.primary : 'transparent',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Text style={[type.title, { color: p.text, fontVariant: ['tabular-nums'] }]}>{d.trim()}</Text>
          </View>
        ))}
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
        style={{ position: 'absolute', opacity: 0.01, height: 56, width: '100%', top: 24 }}
      />
    </Pressable>
  );
}

export function Loading() {
  const p = usePalette();
  return (
    <View style={{ gap: space[4] }} accessibilityLabel="Loading">
      {[120, 72, 72].map((h, i) => (
        <View key={i} style={{ height: h, borderRadius: radius.lg, backgroundColor: p.surfaceAlt }} />
      ))}
    </View>
  );
}

export function ErrorView({ message, onRetry }: { message: string; onRetry: () => void }) {
  const p = usePalette();
  return (
    <Card>
      <Text style={[type.headline, { color: p.text }]}>We could not load this</Text>
      <Text style={[type.callout, { color: p.textMuted, marginVertical: space[2] }]}>{message}</Text>
      <Button title="Try again" variant="secondary" onPress={onRetry} />
    </Card>
  );
}

export function Muted({ children }: { children: ReactNode }) {
  const p = usePalette();
  return <Text style={[type.footnote, { color: p.textMuted }]}>{children}</Text>;
}
