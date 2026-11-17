import { useState } from 'react';
import { router } from 'expo-router';
import { brand, holdToApproveMs } from '@tenmina/tokens';
import { Button, GroundContext, HoldButton, Label, Panel, T, haptic, useScreenReader } from '@tenmina/ui';
import { ProblemBox, SecondFactorInput, money, toProblem, useSecondFactor, type ApiMoney, type Problem } from '@tenmina/mobile';

/**
 * A smaller approval on a black panel, for screens that list several payments
 * (event vendors, repair quotes). Same rule as the full sheet: press and hold,
 * then Face ID or a fingerprint (FR-ACC-014), or the code where this phone has
 * no approval key. The step-up runs first (6.3), then the action.
 */
export function InlineApproval({ title, amount, payee, note, onApprove, onDone }: { title: string; amount: ApiMoney; payee: string; note?: string; onApprove: () => Promise<unknown>; onDone: () => void }) {
  const factor = useSecondFactor();
  const screenReader = useScreenReader();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem>();

  async function go() {
    setBusy(true);
    setProblem(undefined);
    const f = await factor.confirm({ stepUp: true });
    if (!f.ok) {
      setProblem(f.problem);
      setBusy(false);
      return;
    }
    try {
      await onApprove();
      haptic('success');
      onDone();
    } catch (e) {
      setProblem(toProblem(e));
      factor.reset();
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
        {factor.mode === 'none' ? (
          <Button title="Set up the authenticator first" onPress={() => router.push('/account/security')} />
        ) : (
          <>
            <SecondFactorInput factor={factor} />
            <HoldButton label="Approve" holdMs={holdToApproveMs} screenReader={screenReader} disabled={!factor.ready} loading={busy} onConfirm={() => void go()} />
          </>
        )}
        <ProblemBox problem={problem} />
      </Panel>
    </GroundContext.Provider>
  );
}
