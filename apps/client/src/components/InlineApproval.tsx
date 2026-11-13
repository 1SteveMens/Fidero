import { useState } from 'react';
import { router } from 'expo-router';
import { brand, holdToApproveMs } from '@tenmina/tokens';
import { Button, CodeField, GroundContext, HoldButton, Label, Panel, T, haptic, useScreenReader } from '@tenmina/ui';
import { ProblemBox, money, stepUp, toProblem, useApi, useSession, type ApiMoney, type Problem } from '@tenmina/mobile';

/**
 * A smaller approval on a black panel, for screens that list several payments
 * (event vendors, repair quotes). Same rule as the full sheet: the code, then
 * press and hold. The code is checked first as a step-up (6.3), then the action runs.
 */
export function InlineApproval({ title, amount, payee, note, onApprove, onDone }: { title: string; amount: ApiMoney; payee: string; note?: string; onApprove: () => Promise<unknown>; onDone: () => void }) {
  const api = useApi();
  const { me } = useSession();
  const screenReader = useScreenReader();
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem>();

  async function go() {
    setBusy(true);
    setProblem(undefined);
    const p = await stepUp(api, code);
    if (p) {
      setProblem(p);
      setBusy(false);
      setCode('');
      return;
    }
    try {
      await onApprove();
      haptic('success');
      onDone();
    } catch (e) {
      setProblem(toProblem(e));
    }
    setBusy(false);
  }

  return (
    <GroundContext.Provider value="ink">
      <Panel style={{ backgroundColor: brand.ink }}>
        <Label color={brand.orange}>Needs you · you approve first</Label>
        <T v="headline">{title}</T>
        <T v="amount" style={{ fontSize: 30, lineHeight: 36 }}>{money(amount)}</T>
        <T v="footnote" muted>{`To ${payee}, a verified payee. Then two Tenmina staff approve and the bank pays.${note ? ` ${note}` : ''}`}</T>
        {me?.mfa_enabled ? (
          <>
            <CodeField label="Code from your authenticator app" value={code} onChange={setCode} />
            <HoldButton label="Approve" holdMs={holdToApproveMs} screenReader={screenReader} disabled={code.length < 6} loading={busy} onConfirm={() => void go()} />
          </>
        ) : (
          <Button title="Set up the authenticator first" onPress={() => router.push('/account/security')} />
        )}
        <ProblemBox problem={problem} />
      </Panel>
    </GroundContext.Provider>
  );
}
