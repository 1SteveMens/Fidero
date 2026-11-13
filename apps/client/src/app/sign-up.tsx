import { useState } from 'react';
import { Pressable, View } from 'react-native';
import { router } from 'expo-router';
import { brand, space } from '@tenmina/tokens';
import { Button, Choice, CodeField, Label, Panel, Screen, T, Tick, usePalette } from '@tenmina/ui';
import { Field, ProblemBox, toProblem, useApi, useGet, useSession, type Person, type Problem } from '@tenmina/mobile';

interface Country {
  code: string;
  name: string;
  currency: string;
  phone_prefix: string;
}

/**
 * Sign up and choose a country (SCR-PTL-02, SCR-PTL-37; FR-ACC-001, US-DPR-001):
 * name, email, phone and a password, the privacy notice, then a code to the
 * email and one to the phone. Both codes must be entered before the account works.
 */
export default function SignUp() {
  const api = useApi();
  const { adopt } = useSession();
  const pal = usePalette('ink');
  const countries = useGet<Country[]>('/v1/countries');
  const notice = useGet<{ version: string; title: string; summary: string }>('/v1/privacy-notices/current');
  const [country, setCountry] = useState('GH');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [agree, setAgree] = useState(false);
  const [step, setStep] = useState<'details' | 'codes'>('details');
  const [emailCode, setEmailCode] = useState('');
  const [phoneCode, setPhoneCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem>();

  async function create() {
    setBusy(true);
    setProblem(undefined);
    try {
      await api.request('POST', '/v1/auth/signup', {
        anonymous: true,
        body: { full_name: name.trim(), email: email.trim(), phone: phone.trim(), password, home_country: country, privacy_notice_version: notice.data?.version, mode: 'token' },
      });
      setStep('codes');
    } catch (e) {
      setProblem(toProblem(e));
    }
    setBusy(false);
  }

  async function verify() {
    setBusy(true);
    setProblem(undefined);
    try {
      await api.request('POST', '/v1/auth/otp/verify', { anonymous: true, body: { identifier: email.trim(), channel: 'email', code: emailCode, mode: 'token' } });
      const out = await api.request<{ verified: boolean; person?: Person; access?: string; refresh?: string; expires_in?: number }>('POST', '/v1/auth/otp/verify', {
        anonymous: true,
        body: { identifier: phone.trim(), channel: 'phone', code: phoneCode, mode: 'token' },
      });
      if (out.verified && out.person && out.access && out.refresh && out.expires_in) {
        await adopt({ person: out.person, access: out.access, refresh: out.refresh, expires_in: out.expires_in });
        router.replace('/turn-on-notifications');
      } else {
        setProblem({ type: 'about:blank', title: 'Not verified yet', status: 400, code: 'not-verified', detail: 'Both codes are needed. Check them and try again.' });
      }
    } catch (e) {
      setProblem(toProblem(e));
    }
    setBusy(false);
  }

  if (step === 'codes') {
    return (
      <Screen ground="ink" back title="Check your codes" footer={<Button title="Confirm" icon="checkmark" disabled={emailCode.length < 6 || phoneCode.length < 6} loading={busy} onPress={() => void verify()} />}>
        <T v="callout" muted>{`We sent one code to ${email} and another to ${phone}. Enter both.`}</T>
        <CodeField label="Code from the email" value={emailCode} onChange={setEmailCode} />
        <CodeField label="Code from the text message" value={phoneCode} onChange={setPhoneCode} />
        <ProblemBox problem={problem} />
      </Screen>
    );
  }

  const prefix = countries.data?.find((c) => c.code === country)?.phone_prefix ?? '';
  const ready = name.trim().length > 1 && /@/.test(email) && phone.trim().length > 6 && password.length >= 10 && agree;
  return (
    <Screen ground="ink" back title="Create your account" footer={<Button title="Create account" icon="arrow-forward" disabled={!ready} loading={busy} onPress={() => void create()} />}>
      <Panel style={{ gap: 0 }}>
        <Label>Where is the work done?</Label>
        {(countries.data ?? [{ code: 'GH', name: 'Ghana', currency: 'GHS', phone_prefix: '+233' }]).map((c) => (
          <Choice key={c.code} selected={country === c.code} onPress={() => setCountry(c.code)} title={c.name} detail={`Prices in ${c.currency}`} />
        ))}
      </Panel>
      <Field label="Full name, as on your passport" value={name} onChange={setName} />
      <Field label="Email address" value={email} onChange={setEmail} keyboardType="email-address" autoComplete="email" />
      <Field label="Mobile number with country code" value={phone} onChange={setPhone} keyboardType="phone-pad" autoComplete="tel" placeholder={prefix ? `${prefix} or +44 …` : '+44 …'} />
      <Field label="Password" value={password} onChange={setPassword} secure autoComplete="password" hint="At least 10 characters." />
      <Pressable onPress={() => setAgree((a) => !a)} accessibilityRole="checkbox" accessibilityState={{ checked: agree }} style={{ flexDirection: 'row', gap: space[3], alignItems: 'flex-start', minHeight: 44 }}>
        {agree ? <Tick size={26} /> : <View style={{ width: 26, height: 26, borderRadius: 8, borderWidth: 2, borderColor: pal.text }} />}
        <View style={{ flex: 1 }}>
          <T v="callout">{`I have read "${notice.data?.title ?? 'How Tenmina uses your data'}"${notice.data ? ` (version ${notice.data.version})` : ''}.`}</T>
          {notice.data ? <T v="footnote" muted>{notice.data.summary}</T> : null}
        </View>
      </Pressable>
      <T v="footnote" color={brand.lime}>Tenmina never holds your money. A licensed bank does.</T>
      <ProblemBox problem={problem} />
    </Screen>
  );
}
