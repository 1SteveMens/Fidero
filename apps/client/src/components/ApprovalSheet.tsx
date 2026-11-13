import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Animated, Platform, View } from 'react-native';
import { router } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, holdToApproveMs, radius, space } from '@tenmina/tokens';
import { Button, CodeField, HoldButton, Label, Panel, Pulse, Rise, Screen, T, Tick, haptic, usePalette, useReducedMotion, useScreenReader } from '@tenmina/ui';
import { Field, ProblemBox, initials, money, useSession, type ApiMoney, type Problem } from '@tenmina/mobile';

/** Who approves, in order. Two different Tenmina staff, then the bank pays (RUL-05, RUL-11). */
const CHAIN = ['You', 'Staff 1', 'Staff 2', 'Bank pays'] as const;

export interface PayeeLine {
  name: string;
  last4?: string;
  bank?: string;
  place?: string;
  /** The bank's account-name check (FR-ESC-015). Red only when it does not match. */
  matched: boolean | null;
}

/**
 * One approval pattern for every payment (RUL-05, RUL-11, RUL-22): the amount
 * and exactly who is paid on a ticket, every condition ticked, the approval
 * chain, the code, then press and hold. Silence is never approval: nothing
 * moves until the client acts, and declining says why.
 */
export function ApprovalSheet({
  title,
  source,
  amount,
  description,
  payee,
  checks,
  blockers,
  onApprove,
  onDecline,
  approvedMessage,
  children,
  chain = CHAIN,
  after,
}: {
  title: string;
  source: string;
  amount: ApiMoney;
  description?: string;
  payee: PayeeLine;
  checks: { label: string; detail?: string; ok: boolean }[];
  blockers: string[];
  onApprove: (code: string) => Promise<Problem | undefined>;
  onDecline?: (reason: string) => Promise<Problem | undefined>;
  approvedMessage: string;
  children?: ReactNode;
  chain?: readonly string[];
  /** What happens after the client approves; by default two staff, then the bank. */
  after?: { title: string; detail: string }[];
}) {
  const screenReader = useScreenReader();
  const { me } = useSession();
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem>();
  const [done, setDone] = useState<'approved' | 'declined'>();
  const [declining, setDeclining] = useState(false);
  const [reason, setReason] = useState('');

  async function approve() {
    setBusy(true);
    setProblem(undefined);
    const p = await onApprove(code);
    setBusy(false);
    if (p) {
      haptic('warning');
      setProblem(p);
      setCode('');
      return;
    }
    haptic('success');
    setDone('approved');
  }

  async function decline() {
    if (!onDecline) return;
    setBusy(true);
    const p = await onDecline(reason.trim());
    setBusy(false);
    if (p) {
      setProblem(p);
      return;
    }
    setDone('declined');
  }

  if (done === 'approved') return <Approved amount={amount} payee={payee} message={approvedMessage} after={after} />;
  if (done === 'declined') {
    return (
      <Screen ground="ink" footer={<Button title="Done" onPress={() => router.back()} />}>
        <View style={{ paddingTop: space[7], gap: space[3] }}>
          <T v="display" header>Declined.</T>
          <T v="callout" muted>Nothing was paid. The money stays at the bank. Tenmina will contact you about what happens next.</T>
        </View>
      </Screen>
    );
  }

  const noMfa = me && !me.mfa_enabled;
  const ready = blockers.length === 0;
  const matched = payee.matched !== false;
  const canApprove = ready && matched && !noMfa && code.length === 6;

  return (
    <Screen
      ground="ink"
      title={title}
      eyebrow="You approve first"
      footer={
        declining ? (
          <>
            <Button title="Decline this payment" variant="danger" disabled={reason.trim().length < 5} loading={busy} onPress={() => void decline()} />
            <Button title="Back" variant="quiet" onPress={() => setDeclining(false)} />
          </>
        ) : (
          <>
            <HoldButton label="Approve" holdMs={holdToApproveMs} screenReader={screenReader} disabled={!canApprove} loading={busy} onConfirm={() => void approve()} />
            <Label style={{ textAlign: 'center' }}>Nothing moves until you approve</Label>
            {onDecline && ready ? <Button title="Something is wrong: decline" variant="danger" onPress={() => setDeclining(true)} /> : null}
          </>
        )
      }
    >
      <Rise delay={60}>
        <Ticket
          top={
            <>
              <Label color={brand.ink}>{source}</Label>
              <T v="amount" color={brand.ink} style={{ fontSize: 38, lineHeight: 44 }}>{money(amount)}</T>
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
                  {[payee.place, payee.bank, payee.last4 ? `••${payee.last4}` : undefined, payee.matched === null ? 'name check pending' : matched ? 'name matched' : 'name not matched']
                    .filter(Boolean)
                    .join(' · ')}
                </Label>
              </View>
              {payee.matched === null ? null : <Tick ok={matched} size={26} />}
            </View>
          }
        />
      </Rise>

      {checks.length ? (
        <Rise delay={160}>
          <Panel style={{ paddingVertical: space[2], gap: 0 }}>
            {checks.map((c, i) => (
              <View key={`${c.label}-${i}`} style={{ flexDirection: 'row', alignItems: 'center', gap: space[3], paddingVertical: space[3], borderBottomWidth: i < checks.length - 1 ? 1 : 0, borderBottomColor: '#2C2C2C' }}>
                <Tick ok={c.ok} />
                <T v="callout" style={{ flex: 1 }}>{c.label}</T>
                {c.detail ? <Label>{c.detail}</Label> : null}
              </View>
            ))}
          </Panel>
        </Rise>
      ) : null}

      {children}

      <Rise delay={260}>
        <View style={{ flexDirection: 'row', gap: 6 }} accessibilityLabel={`You approve first. Then ${chain.slice(1).join(', then ')}.`}>
          {chain.map((c, i) => (
            <View key={c} style={{ flex: 1, gap: 6 }}>
              <View style={{ height: 8, borderRadius: 4, backgroundColor: i === 0 ? brand.orange : '#2C2C2C' }} />
              <Label color={i === 0 ? brand.orange : undefined}>{i === 0 ? 'You · now' : c}</Label>
            </View>
          ))}
        </View>
      </Rise>

      {!ready ? (
        <Panel style={{ borderWidth: 2, borderColor: brand.orange, backgroundColor: 'transparent' }}>
          <Label color={brand.orange}>Not ready for your approval</Label>
          {blockers.map((b) => (
            <T key={b} v="callout">{b}</T>
          ))}
        </Panel>
      ) : noMfa ? (
        <Panel style={{ borderWidth: 2, borderColor: brand.orange, backgroundColor: 'transparent' }}>
          <Label color={brand.orange}>Set up your authenticator first</Label>
          <T v="callout">Every approval needs a 6-digit code from an authenticator app. It takes a minute.</T>
          <Button title="Set up the authenticator" variant="dark" onPress={() => router.push('/account/security')} />
        </Panel>
      ) : declining ? (
        <Field label="Why are you declining?" value={reason} onChange={setReason} multiline hint="Tenmina staff read this before anything else happens." />
      ) : (
        <Rise delay={340}>
          <CodeField label="Code from your authenticator app" value={code} onChange={setCode} />
        </Rise>
      )}
      <ProblemBox problem={problem} />
    </Screen>
  );
}

/** The amount above a tear line, who gets paid below. Used only where money is about to move. */
function Ticket({ top, bottom }: { top: ReactNode; bottom: ReactNode }) {
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
          <View pointerEvents="none" style={{ position: 'absolute', left: -11, top: tear - 10, width: 22, height: 22, borderRadius: 11, backgroundColor: brand.ink }} />
          <View pointerEvents="none" style={{ position: 'absolute', right: -11, top: tear - 10, width: 22, height: 22, borderRadius: 11, backgroundColor: brand.ink }} />
        </>
      ) : null}
    </View>
  );
}

/** After the client approves: what happens next, and that the money is still at the bank. */
function Approved({ amount, payee, message, after }: { amount: ApiMoney; payee: PayeeLine; message: string; after?: { title: string; detail: string }[] }) {
  const reduced = useReducedMotion();
  const pop = useRef(new Animated.Value(reduced ? 1 : 0)).current;
  useEffect(() => {
    if (reduced) return;
    Animated.spring(pop, { toValue: 1, friction: 5, tension: 80, useNativeDriver: Platform.OS !== 'web' }).start();
  }, [pop, reduced]);
  const p = usePalette('ink');
  const next = after ?? [
    { title: 'Tenmina staff, first check', detail: 'Checking the conditions again' },
    { title: 'Tenmina staff, second check', detail: 'A different person checks again' },
    { title: 'The bank pays', detail: `${payee.name}${payee.last4 ? ` ••${payee.last4}` : ''}. The receipt comes here.` },
  ];
  const rows: { state: 'done' | 'now' | 'next'; title: string; detail: string }[] = [
    { state: 'done', title: 'You approved', detail: 'Just now, with your authenticator code' },
    ...next.map((r, i) => ({ ...r, state: (i === 0 ? 'now' : 'next') as 'now' | 'next' })),
  ];
  return (
    <Screen ground="ink" footer={<Button title="Done" onPress={() => router.back()} />}>
      <View style={{ alignItems: 'center', paddingTop: space[6], gap: space[4] }}>
        <Animated.View style={{ transform: [{ scale: pop }], width: 104, height: 104, borderRadius: 52, backgroundColor: brand.lime, alignItems: 'center', justifyContent: 'center' }}>
          <Ionicons name="checkmark" size={56} color={brand.ink} />
        </Animated.View>
        <T v="display" header style={{ textAlign: 'center' }}>Your approval is in.</T>
        <T v="callout" muted style={{ textAlign: 'center' }}>{`${money(amount)}. ${message}`}</T>
      </View>
      <Rise delay={300}>
        <Panel>
          {rows.map((r, i) => (
            <View key={r.title} style={{ flexDirection: 'row', gap: space[3] }}>
              <View style={{ alignItems: 'center' }}>
                {r.state === 'done' ? (
                  <Tick size={30} />
                ) : r.state === 'now' ? (
                  <Pulse size={30} radius={9} color={brand.lime}>
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
