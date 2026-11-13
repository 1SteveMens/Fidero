import { useState, type ReactNode } from 'react';
import { Linking, Pressable, TextInput, View, type KeyboardTypeOptions } from 'react-native';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, radius, space, type } from '@tenmina/tokens';
import { Button, Chip, CodeField, Label, Panel, Rise, Screen, T, Tick, haptic, usePalette, type ChipTone, type IconName } from '@tenmina/ui';
import { toProblem, type Problem, type UpdateRequired } from './api';
import { useAction, useGet } from './hooks';
import { useApi, useSession } from './session';
import { day } from './format';

/* ---------- Problems ---------- */

const PLAIN: Record<string, string> = {
  offline: 'No connection to Tenmina. Check your signal and try again.',
  'mfa-required': 'Enter the 6-digit code from your authenticator app to go on.',
  'mfa-not-set-up': 'Set up an authenticator app in Account first. Every approval needs its code.',
  unauthenticated: 'Please sign in again.',
};

/**
 * A problem from the API (RFC 9457) in plain words: what happened, the rule
 * that blocks it and any field that needs fixing. Neutral colours: red is
 * kept for the Red verdict and an unmatched payee name (03 section 6.1a).
 */
export function ProblemBox({ problem, onRetry }: { problem?: Problem | null; onRetry?: () => void }) {
  const p = usePalette();
  if (!problem) return null;
  const detail = PLAIN[problem.code] ?? problem.detail;
  return (
    <View
      accessibilityRole="alert"
      style={{ borderRadius: radius.lg, borderWidth: 2, borderColor: p.text, padding: space[4], gap: space[2], backgroundColor: p.ground }}
    >
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[2] }}>
        <Ionicons name="alert-circle" size={20} color={p.text} />
        <T v="headline" style={{ flex: 1, fontSize: 15 }}>{problem.code === 'offline' ? 'No connection' : problem.title || 'That did not work'}</T>
      </View>
      <T v="callout">{detail}</T>
      {problem.blocking_reasons?.map((b) => (
        <View key={`${b.rule}-${b.message}`} style={{ flexDirection: 'row', gap: space[2], alignItems: 'flex-start' }}>
          <Label style={{ marginTop: 3 }}>{b.rule}</Label>
          <T v="footnote" style={{ flex: 1 }}>{b.message}</T>
        </View>
      ))}
      {problem.errors?.map((er) => (
        <T key={`${er.pointer}-${er.message}`} v="footnote" muted>{`${er.pointer.replace(/^\//, '').replace(/\//g, ' › ') || 'Form'}: ${er.message}`}</T>
      ))}
      {onRetry ? <Button title="Try again" variant="dark" onPress={onRetry} /> : null}
    </View>
  );
}

/** Loading, a problem, or nothing: the top of every screen that reads data. */
export function LoadState({ loading, problem, onRetry, hasData }: { loading: boolean; problem?: Problem; onRetry: () => void; hasData: boolean }) {
  const p = usePalette();
  if (problem) return <ProblemBox problem={problem} onRetry={onRetry} />;
  if (loading && !hasData) {
    return (
      <View style={{ gap: space[3] }} accessibilityLabel="Loading">
        {[140, 72, 72].map((h, i) => (
          <View key={i} style={{ height: h, borderRadius: radius.xl, backgroundColor: p.surface }} />
        ))}
      </View>
    );
  }
  return null;
}

export function Empty({ icon = 'checkmark-circle-outline', title, detail, action }: { icon?: IconName; title: string; detail?: string; action?: ReactNode }) {
  const p = usePalette();
  return (
    <Panel style={{ alignItems: 'flex-start' }}>
      <Ionicons name={icon} size={24} color={p.text} />
      <T v="headline">{title}</T>
      {detail ? <T v="callout" muted>{detail}</T> : null}
      {action}
    </Panel>
  );
}

/** A small mono heading over a group. */
export function Section({ title, children, right }: { title: string; children: ReactNode; right?: ReactNode }) {
  return (
    <View style={{ gap: space[2] }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
        <Label>{title}</Label>
        {right}
      </View>
      {children}
    </View>
  );
}

/** Label and value rows, for details. */
export function KV({ rows }: { rows: [string, ReactNode][] }) {
  const p = usePalette();
  return (
    <Panel style={{ paddingVertical: space[1], gap: 0 }}>
      {rows.map(([k, v], i) => (
        <View key={k} style={{ flexDirection: 'row', gap: space[3], paddingVertical: space[3], borderTopWidth: i ? 1 : 0, borderTopColor: p.line }}>
          <T v="callout" muted style={{ width: 120 }}>{k}</T>
          <View style={{ flex: 1 }}>{typeof v === 'string' || typeof v === 'number' ? <T v="callout">{String(v)}</T> : v}</View>
        </View>
      ))}
    </Panel>
  );
}

/** A status chip: lime when done, orange when it waits for this person, plain otherwise. */
export function StatusChip({ label, tone }: { label: string; tone?: ChipTone }) {
  return <Chip label={label} tone={tone ?? 'paper'} />;
}

/* ---------- Text fields ---------- */

export function Field({
  label,
  value,
  onChange,
  secure,
  keyboardType,
  autoComplete,
  placeholder,
  hint,
  multiline,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  secure?: boolean;
  keyboardType?: KeyboardTypeOptions;
  autoComplete?: 'email' | 'password' | 'username' | 'tel' | 'off';
  placeholder?: string;
  hint?: string;
  multiline?: boolean;
}) {
  const p = usePalette();
  const [show, setShow] = useState(false);
  return (
    <View style={{ gap: 6 }}>
      <T v="footnote" style={{ fontFamily: type.headline.fontFamily, fontSize: 14 }}>{label}</T>
      <View>
        <TextInput
          value={value}
          onChangeText={onChange}
          secureTextEntry={secure && !show}
          keyboardType={keyboardType}
          autoComplete={autoComplete}
          autoCapitalize="none"
          autoCorrect={false}
          multiline={multiline}
          placeholder={placeholder}
          placeholderTextColor={p.textMuted}
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
              paddingRight: secure ? 56 : space[3],
              paddingVertical: space[3],
              minHeight: multiline ? 88 : 50,
              textAlignVertical: multiline ? 'top' : 'center',
            },
          ]}
        />
        {secure ? (
          <Pressable
            onPress={() => setShow((s) => !s)}
            accessibilityRole="button"
            accessibilityLabel={show ? 'Hide the password' : 'Show the password'}
            style={{ position: 'absolute', right: 0, top: 0, bottom: 0, width: 52, alignItems: 'center', justifyContent: 'center' }}
          >
            <Ionicons name={show ? 'eye-off-outline' : 'eye-outline'} size={20} color={p.textMuted} />
          </Pressable>
        ) : null}
      </View>
      {hint ? <T v="footnote" muted>{hint}</T> : null}
    </View>
  );
}

/* ---------- Sign in (SCR-PTL-03 in the client app, SCR-MOB-01 in Tenmina Field) ---------- */

/** Email or phone and password, then the authenticator code if the account has MFA (FR-ACC-002, FR-ACC-003). */
export function SignInForm({ onSignedIn, footer }: { onSignedIn: () => void; footer?: ReactNode }) {
  const { signIn } = useSession();
  const [identifier, setIdentifier] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [needsCode, setNeedsCode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem>();

  async function go() {
    setBusy(true);
    setProblem(undefined);
    const r = await signIn(identifier, password, needsCode ? code : undefined);
    setBusy(false);
    if (r.ok) {
      haptic('success');
      onSignedIn();
      return;
    }
    if (r.needsCode) {
      setNeedsCode(true);
      if (r.problem) setProblem(r.problem);
      setCode('');
      return;
    }
    haptic('warning');
    setProblem(r.problem);
  }

  const ready = identifier.trim().length > 3 && password.length > 0 && (!needsCode || code.length === 6);
  return (
    <View style={{ gap: space[4] }}>
      {needsCode ? (
        <Rise style={{ gap: space[3] }}>
          <T v="callout" muted>Open your authenticator app and enter the 6-digit code for Tenmina.</T>
          <CodeField label="Code from your authenticator app" value={code} onChange={setCode} />
        </Rise>
      ) : (
        <>
          <Field label="Email or mobile number" value={identifier} onChange={setIdentifier} keyboardType="email-address" autoComplete="username" placeholder="you@example.com" />
          <Field label="Password" value={password} onChange={setPassword} secure autoComplete="password" />
        </>
      )}
      <ProblemBox problem={problem} />
      <Button title={needsCode ? 'Confirm and sign in' : 'Sign in'} icon="arrow-forward" disabled={!ready} loading={busy} onPress={() => void go()} />
      {needsCode ? <Button title="Use a different account" variant="quiet" onPress={() => setNeedsCode(false)} /> : null}
      {footer}
    </View>
  );
}

/* ---------- Update required (SCR-APP-05, FR-APP-006) ---------- */

export function UpdateRequiredScreen({ info, savedItems }: { info: UpdateRequired; savedItems?: number }) {
  return (
    <Screen ground="ink" footer={<Button title="Open the store" icon="download-outline" disabled={!info.storeUrl} onPress={() => void Linking.openURL(info.storeUrl.replace(/\s*\[TO VERIFY\]\s*$/, ''))} />}>
      <View style={{ paddingTop: space[8], gap: space[4] }}>
        <View style={{ width: 72, height: 72, borderRadius: 22, backgroundColor: brand.lime, alignItems: 'center', justifyContent: 'center' }}>
          <Ionicons name="arrow-up" size={36} color={brand.ink} />
        </View>
        <T v="display" header>Update Tenmina</T>
        <T v="body" muted>{`This version is too old to keep your money and evidence safe. Install version ${info.minVersion || 'the latest'} from the store.`}</T>
        {savedItems ? (
          <Panel style={{ flexDirection: 'row', alignItems: 'center' }}>
            <Ionicons name="cloud-upload-outline" size={22} color={brand.lime} />
            <T v="callout" style={{ flex: 1 }}>{`Your ${savedItems} saved ${savedItems === 1 ? 'item is' : 'items are'} safe on this phone and will upload after you update.`}</T>
          </Panel>
        ) : null}
      </View>
    </Screen>
  );
}

/* ---------- Step-up ---------- */

/** POST /v1/auth/mfa/step-up: a fresh second factor for an approval, valid for 5 minutes. */
export async function stepUp(api: ReturnType<typeof useApi>, code: string): Promise<Problem | undefined> {
  try {
    await api.post('/v1/auth/mfa/step-up', { code });
    return undefined;
  } catch (e) {
    return toProblem(e);
  }
}

/* ---------- Delete my account (SCR-APP-04, FR-APP-004) ---------- */

interface DeletionPreview {
  deleted: string[];
  kept: { data_class: string; what: string; why: string; until: string }[];
  open_matters: { kind: string; id: string; title: string; reason: string }[];
  can_complete_now: boolean;
}

interface DataRequest {
  id: string;
  reference?: string;
  status: string;
  created_at: string;
  due_on?: string;
}

/**
 * The same screen in both apps: what is deleted, what Tenmina must keep and
 * why, and anything still open that delays it. Confirm with a tick and, if the
 * account has an authenticator, its code. The receipt carries a reference.
 */
export function DeleteAccountScreen({ ground = 'paper' }: { ground?: 'paper' | 'ink' }) {
  const api = useApi();
  const { me, signOut } = useSession();
  const pal = usePalette(ground);
  const preview = useGet<DeletionPreview>('/v1/me/deletion-requests/preview');
  const [agree, setAgree] = useState(false);
  const [code, setCode] = useState('');
  const [done, setDone] = useState<DataRequest>();
  const act = useAction();
  const needsCode = !!me?.mfa_enabled;

  async function confirm() {
    if (needsCode) {
      const p = await stepUp(api, code);
      if (p) {
        act.setProblem(p);
        return;
      }
    }
    const r = await act.run<DataRequest>('POST', '/v1/me/deletion-requests', { confirm: true, source: 'app' });
    if (r) setDone(r);
  }

  if (done) {
    return (
      <Screen ground={ground} footer={<Button title="Sign out" onPress={() => void signOut()} />}>
        <View style={{ paddingTop: space[7], gap: space[4] }}>
          <Tick size={56} />
          <T v="display" header>Request received</T>
          <T v="body" muted>{`Reference ${done.reference ?? done.id.slice(0, 8).toUpperCase()}, ${day(done.created_at)}. We delete your account when nothing is open. We will email you when it is done.`}</T>
        </View>
      </Screen>
    );
  }

  const d = preview.data;
  return (
    <Screen
      ground={ground}
      back
      title="Delete my account"
      footer={
        d ? (
          <Button
            title="Delete my account"
            variant="danger"
            icon="trash-outline"
            disabled={!agree || (needsCode && code.length < 6)}
            loading={act.busy}
            onPress={() => void confirm()}
          />
        ) : undefined
      }
    >
      <LoadState loading={preview.loading} problem={preview.problem} onRetry={preview.reload} hasData={!!d} />
      {d ? (
        <>
          {d.open_matters.length > 0 ? (
            <Panel tone="orange">
              <Label color={brand.ink}>{`Still open · ${d.open_matters.length}`}</Label>
              <T v="callout" color={brand.ink}>We will close your account when these end. You can ask now; nothing open is cut short.</T>
              {d.open_matters.slice(0, 6).map((m) => (
                <T key={m.id} v="footnote" color={brand.ink}>{`• ${m.title}. ${m.reason}`}</T>
              ))}
              {d.open_matters.length > 6 ? <T v="footnote" color={brand.ink}>{`and ${d.open_matters.length - 6} more`}</T> : null}
            </Panel>
          ) : null}
          <Panel>
            <Label>Deleted</Label>
            {d.deleted.map((x) => (
              <View key={x} style={{ flexDirection: 'row', gap: space[3] }}>
                <Ionicons name="trash-outline" size={18} color={pal.text} />
                <T v="callout" style={{ flex: 1 }}>{x}</T>
              </View>
            ))}
          </Panel>
          <Panel>
            <Label>Kept, why and for how long</Label>
            {d.kept.map((k) => (
              <View key={k.data_class} style={{ gap: 2 }}>
                <T v="headline" style={{ fontSize: 15 }}>{k.what}</T>
                <T v="footnote" muted>{`${k.why} Kept until: ${k.until}`}</T>
              </View>
            ))}
          </Panel>
          <Pressable
            onPress={() => setAgree((a) => !a)}
            accessibilityRole="checkbox"
            accessibilityState={{ checked: agree }}
            style={{ flexDirection: 'row', gap: space[3], alignItems: 'center', minHeight: 44 }}
          >
            {agree ? <Tick size={26} /> : <View style={{ width: 26, height: 26, borderRadius: 8, borderWidth: 2, borderColor: pal.text }} />}
            <T v="callout" style={{ flex: 1 }}>I understand what is deleted and what Tenmina must keep.</T>
          </Pressable>
          {needsCode ? <CodeField label="Code from your authenticator app" value={code} onChange={setCode} /> : null}
          <ProblemBox problem={act.problem} />
        </>
      ) : null}
    </Screen>
  );
}
