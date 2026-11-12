import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Animated, Platform, View } from 'react-native';
import { router } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { formatMoney, type Money, type Payee } from '@tenmina/shared';
import { brand, holdToApproveMs, radius, space } from '@tenmina/tokens';
import { usePalette, useReducedMotion, useScreenReader } from '@tenmina/ui';
import { Button, CodeField, HoldButton, Label, Panel, Pulse, Rise, Screen, T, Tick, haptic } from '@tenmina/ui';
import { Ticket } from '@tenmina/ui';

/** Who approves, in order. Two different Tenmina staff, then the bank pays (RUL-05, RUL-11). */
const CHAIN = ['You', 'Staff 1', 'Staff 2', 'Bank pays'] as const;

function initials(name: string) {
  return name
    .split(/\s+/)
    .filter((w) => /^[A-Z]/.test(w))
    .slice(0, 2)
    .map((w) => w[0])
    .join('');
}

/**
 * One approval pattern for every payment (RUL-05, RUL-11, RUL-22):
 * the amount and exactly who is paid on a ticket, what must be true, the code,
 * then press and hold. Silence is never approval: nothing moves until the client acts.
 */
export function ApprovalSheet({
  title,
  source,
  amount,
  description,
  payee,
  payeePlace,
  checks,
  blockers,
  onApprove,
  children,
}: {
  title: string;
  /** Shown above the amount, for example "Release from PB-ESC-2207". */
  source: string;
  amount: Money;
  description?: string;
  payee: Payee;
  payeePlace?: string;
  checks: { label: string; detail?: string; ok: boolean }[];
  blockers: string[];
  onApprove: (code: string) => Promise<{ ok: boolean; message: string }>;
  children?: ReactNode;
}) {
  const screenReader = useScreenReader();
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; message: string }>();

  async function approve() {
    setBusy(true);
    const r = await onApprove(code);
    setBusy(false);
    setResult(r);
    haptic(r.ok ? 'success' : 'warning');
  }

  if (result?.ok) return <Approved amount={amount} payee={payee} message={result.message} />;

  const ready = blockers.length === 0;
  const matched = payee.nameCheck === 'matched';

  return (
    <Screen
      ground="ink"
      title={title}
      eyebrow="Step 1 of 4"
      footer={
        <>
          {result && !result.ok ? (
            <T v="callout" color={brand.orange} style={{ textAlign: 'center' }}>
              {result.message}
            </T>
          ) : null}
          <HoldButton label="Approve" holdMs={holdToApproveMs} screenReader={screenReader} disabled={!ready || !matched || code.length < 6} loading={busy} onConfirm={approve} />
          <Label style={{ textAlign: 'center' }}>Nothing moves until you approve</Label>
          <Button title="Something is wrong: raise a dispute" variant="danger" onPress={() => undefined} />
        </>
      }
    >
      <Rise delay={60}>
        <Ticket
          top={
            <>
              <Label color={brand.ink}>{source}</Label>
              <T v="amount" color={brand.ink} style={{ fontSize: 40, lineHeight: 46 }}>{formatMoney(amount)}</T>
              {description ? <T v="callout" color={brand.ink}>{description}</T> : null}
            </>
          }
          bottom={
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[3] }}>
              <View style={{ width: 44, height: 44, borderRadius: radius.md, backgroundColor: brand.ink, alignItems: 'center', justifyContent: 'center' }}>
                <T v="headline" color={brand.lime}>{initials(payee.name)}</T>
              </View>
              <View style={{ flex: 1, gap: 2 }}>
                <T v="headline" color={brand.ink}>{payee.name}</T>
                <Label color={matched ? brand.ink : '#B3261E'}>
                  {`${payeePlace ? `${payeePlace} · ` : ''}${payee.bankName} ••${payee.accountLast4} · ${matched ? 'name matched' : 'name not matched'}`}
                </Label>
              </View>
              <Tick ok={matched} size={26} />
            </View>
          }
        />
      </Rise>

      <Rise delay={180}>
        <Panel style={{ paddingVertical: space[2], gap: 0 }}>
          {checks.map((c, i) => (
            <View key={c.label} style={{ flexDirection: 'row', alignItems: 'center', gap: space[3], paddingVertical: space[3], borderBottomWidth: i < checks.length - 1 ? 1 : 0, borderBottomColor: '#2C2C2C' }}>
              <Tick ok={c.ok} />
              <T v="callout" style={{ flex: 1 }}>{c.label}</T>
              {c.detail ? <Label>{c.detail}</Label> : null}
            </View>
          ))}
        </Panel>
      </Rise>

      {children}

      <Rise delay={280}>
        <View style={{ flexDirection: 'row', gap: 6 }} accessibilityLabel="You approve first. Then two Tenmina staff. Then the bank pays.">
          {CHAIN.map((c, i) => (
            <View key={c} style={{ flex: 1, gap: 6 }}>
              <View style={{ height: 8, borderRadius: 4, backgroundColor: i === 0 ? brand.orange : '#2C2C2C' }} />
              <Label color={i === 0 ? brand.orange : undefined}>{i === 0 ? 'You · now' : c}</Label>
            </View>
          ))}
        </View>
      </Rise>

      {ready ? (
        <Rise delay={360}>
          <CodeField label="Code from your authenticator app" value={code} onChange={setCode} />
        </Rise>
      ) : (
        <Panel style={{ borderWidth: 2, borderColor: brand.orange, backgroundColor: 'transparent' }}>
          <Label color={brand.orange}>Not ready for your approval</Label>
          {blockers.map((b) => (
            <T key={b} v="callout">{b}</T>
          ))}
        </Panel>
      )}
    </Screen>
  );
}

/** After the client approves: what happens next, and that the money is still at the bank. */
function Approved({ amount, payee, message }: { amount: Money; payee: Payee; message: string }) {
  const reduced = useReducedMotion();
  const pop = useRef(new Animated.Value(reduced ? 1 : 0)).current;
  useEffect(() => {
    if (reduced) return;
    Animated.spring(pop, { toValue: 1, friction: 5, tension: 80, useNativeDriver: Platform.OS !== 'web' }).start();
  }, [pop, reduced]);
  const p = usePalette('ink');
  const rows: { state: 'done' | 'now' | 'next'; title: string; detail: string }[] = [
    { state: 'done', title: 'You approved', detail: 'Just now, with your authenticator code' },
    { state: 'now', title: 'Tenmina staff, first check', detail: 'Checking the conditions again' },
    { state: 'next', title: 'Tenmina staff, second check', detail: 'A different person checks again' },
    { state: 'next', title: 'The bank pays', detail: `${payee.name} ••${payee.accountLast4}. The receipt comes here.` },
  ];
  return (
    <Screen ground="ink" footer={<Button title="Done" onPress={() => router.back()} />}>
      <View style={{ alignItems: 'center', paddingTop: space[6], gap: space[4] }}>
        <Animated.View style={{ transform: [{ scale: pop }], width: 104, height: 104, borderRadius: 52, backgroundColor: brand.lime, alignItems: 'center', justifyContent: 'center' }}>
          <Ionicons name="checkmark" size={56} color={brand.ink} />
        </Animated.View>
        <T v="display" header style={{ textAlign: 'center' }}>Your approval is in.</T>
        <T v="callout" muted style={{ textAlign: 'center' }}>
          {formatMoney(amount)}. {message} The money stays at the bank until every step is done.
        </T>
      </View>
      <Rise delay={300}>
        <Panel>
          {rows.map((r, i) => (
            <View key={r.title} style={{ flexDirection: 'row', gap: space[3] }}>
              <View style={{ alignItems: 'center' }}>
                {r.state === 'done' ? (
                  <Tick size={30} />
                ) : r.state === 'now' ? (
                  <Pulse size={30} radius={9}>
                    <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: brand.ink }} />
                  </Pulse>
                ) : (
                  <View style={{ width: 30, height: 30, borderRadius: 9, borderWidth: 2, borderColor: p.lineStrong }} />
                )}
                {i < rows.length - 1 ? <View style={{ width: 2, flex: 1, minHeight: 16, backgroundColor: r.state === 'done' ? brand.lime : p.line }} /> : null}
              </View>
              <View style={{ flex: 1, paddingBottom: i < rows.length - 1 ? space[4] : 0 }}>
                <T v="headline">{r.title}</T>
                <T v="footnote" muted>{r.detail}</T>
              </View>
            </View>
          ))}
        </Panel>
      </Rise>
    </Screen>
  );
}
