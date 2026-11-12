import { useState, type ReactNode } from 'react';
import { Text, View } from 'react-native';
import { router } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { RELEASE_STEPS, formatMoney, type Money, type Payee } from '@fidero/shared';
import { radius, space, type } from '@fidero/tokens';
import { Button, Card, CodeField, Muted, Pill, haptic } from './ui';
import { usePalette } from '../theme';

/**
 * One approval pattern for every payment (RUL-05, RUL-11, RUL-22):
 * the amount, exactly who is paid, what must be true, the code, then the three steps.
 */
export function ApprovalSheet({
  eyebrow,
  title,
  amount,
  payee,
  heldAt,
  checks,
  blockers,
  onApprove,
  children,
}: {
  eyebrow: string;
  title: string;
  amount: Money;
  payee: Payee;
  heldAt: string;
  checks: { label: string; ok: boolean }[];
  blockers: string[];
  onApprove: (code: string) => Promise<{ ok: boolean; message: string }>;
  children?: ReactNode;
}) {
  const p = usePalette();
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; message: string }>();
  const approved = result?.ok === true;

  async function approve() {
    setBusy(true);
    const r = await onApprove(code);
    setBusy(false);
    setResult(r);
    haptic(r.ok ? 'success' : 'warning');
  }

  return (
    <View style={{ gap: space[5] }}>
      <View style={{ gap: space[1] }}>
        <Text style={[type.footnote, { color: p.textMuted, fontWeight: '600' }]}>{eyebrow}</Text>
        <Text accessibilityRole="header" style={[type.title, { color: p.text }]}>{title}</Text>
        <Text style={[type.amount, { color: p.text, fontVariant: ['tabular-nums'], letterSpacing: -1, marginTop: space[2] }]}>{formatMoney(amount)}</Text>
        <Muted>Held at {heldAt}. Fidero never holds this money.</Muted>
      </View>

      <Card style={{ gap: space[2] }}>
        <Text style={[type.caption, { color: p.textMuted, textTransform: 'uppercase', letterSpacing: 0.6 }]}>Who gets paid</Text>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[3] }}>
          <View style={{ width: 40, height: 40, borderRadius: radius.md, backgroundColor: p.primarySoft, alignItems: 'center', justifyContent: 'center' }}>
            <Ionicons name="business" size={20} color={p.primary} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={[type.headline, { color: p.text }]}>{payee.name}</Text>
            <Text style={[type.footnote, { color: p.textMuted }]}>
              {payee.bankName} · account ending {payee.accountLast4}
            </Text>
          </View>
        </View>
        {payee.nameCheck === 'matched' ? (
          <Pill label="Bank confirmed the account name" tone="success" icon="shield-checkmark" />
        ) : (
          <Pill label="Account name not confirmed" tone="danger" icon="warning" />
        )}
      </Card>

      <Card style={{ gap: space[3] }}>
        {checks.map((c) => (
          <View key={c.label} style={{ flexDirection: 'row', alignItems: 'center', gap: space[3] }}>
            <Ionicons name={c.ok ? 'checkmark-circle' : 'close-circle'} size={22} color={c.ok ? p.success : p.danger} />
            <Text style={[type.callout, { color: p.text, flex: 1 }]}>{c.label}</Text>
          </View>
        ))}
      </Card>

      {children}

      {approved ? (
        <Card style={{ backgroundColor: p.successSoft, gap: space[2] }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[2] }}>
            <Ionicons name="checkmark-circle" size={24} color={p.success} />
            <Text style={[type.headline, { color: p.text }]}>Approved by you</Text>
          </View>
          <Text style={[type.callout, { color: p.text }]}>{result.message}</Text>
        </Card>
      ) : blockers.length > 0 ? (
        <Card style={{ backgroundColor: p.warningSoft, gap: space[2] }}>
          <Text style={[type.headline, { color: p.text }]}>Not ready for your approval</Text>
          {blockers.map((b) => (
            <Text key={b} style={[type.callout, { color: p.text }]}>· {b}</Text>
          ))}
        </Card>
      ) : (
        <CodeField label="Code from your authenticator app" value={code} onChange={setCode} />
      )}

      {result && !result.ok ? (
        <Text accessibilityLiveRegion="polite" style={[type.callout, { color: p.danger }]}>{result.message}</Text>
      ) : null}

      <View style={{ flexDirection: 'row', gap: space[2] }}>
        {RELEASE_STEPS.map((s, i) => {
          const active = i === 0 ? !approved : i === 1 && approved;
          const complete = i === 0 && approved;
          return (
            <View key={s} style={{ flex: 1, gap: space[1] }}>
              <View style={{ height: 4, borderRadius: 2, backgroundColor: complete ? p.success : active ? p.primary : p.surfaceAlt }} />
              <Text style={[type.caption, { color: active || complete ? p.text : p.textMuted, fontWeight: active ? '700' : '500' }]}>{s}</Text>
            </View>
          );
        })}
      </View>

      {approved ? (
        <Button title="Done" onPress={() => router.back()} />
      ) : (
        <>
          <Button title="Approve" icon="lock-closed" disabled={blockers.length > 0 || code.length < 6} loading={busy} onPress={approve} />
          <Button title="Something is wrong: raise a dispute" variant="danger" onPress={() => undefined} />
        </>
      )}
    </View>
  );
}
