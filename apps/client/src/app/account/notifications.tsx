import { useEffect, useState } from 'react';
import { brand, space } from '@tenmina/tokens';
import { Button, Label, Panel, Screen, SwitchRow, T } from '@tenmina/ui';
import { LoadState, ProblemBox, pushChoice, registerPush, setPushChoice, toProblem, useAction, useApi, useGet, words, type Problem } from '@tenmina/mobile';

interface Pref {
  channel: string;
  enabled: boolean;
  quiet_start: string | null;
  quiet_end: string | null;
  timezone: string;
  muted_categories: string[];
  address: string;
}

const NAMES: Record<string, string> = { in_app: 'In the app', email: 'Email', sms: 'Text message', whatsapp: 'WhatsApp', push: 'Push on this phone' };

/** Notification channels (SCR-PTL-20, FR-NTF-004). Money and safety messages always come through at least one channel. */
export default function Notifications() {
  const api = useApi();
  const prefs = useGet<Pref[]>('/v1/me/notification-preferences');
  const act = useAction();
  const [items, setItems] = useState<Pref[]>([]);
  const [push, setPush] = useState<'on' | 'off' | null>(null);
  const [pushProblem, setPushProblem] = useState<Problem>();
  useEffect(() => {
    if (prefs.data) setItems(prefs.data);
  }, [prefs.data]);
  useEffect(() => {
    void pushChoice().then(setPush);
  }, []);

  async function save() {
    const r = await act.run<Pref[]>('PUT', '/v1/me/notification-preferences', { items });
    if (r) setItems(r);
  }
  async function turnOnPush() {
    try {
      await registerPush(api);
      await setPushChoice('on');
      setPush('on');
    } catch (e) {
      setPushProblem(toProblem(e));
    }
  }

  return (
    <Screen ground="ink" back title="Notifications" footer={<Button title="Save" loading={act.busy} disabled={!prefs.data} onPress={() => void save()} />}>
      <LoadState loading={prefs.loading} problem={prefs.problem} onRetry={prefs.reload} hasData={!!prefs.data} />
      <Panel style={{ gap: space[2] }}>
        <Label>This phone</Label>
        <T v="callout">{push === 'on' ? 'Push notifications are on for this phone.' : 'Push notifications are off for this phone.'}</T>
        {push !== 'on' ? <Button title="Turn on push" variant="dark" onPress={() => void turnOnPush()} /> : null}
        <ProblemBox problem={pushProblem} />
      </Panel>
      {items.length ? (
        <Panel style={{ paddingVertical: space[1], gap: 0 }}>
          {items.map((p, i) => (
            <SwitchRow
              key={p.channel}
              title={NAMES[p.channel] ?? words(p.channel)}
              detail={p.quiet_start ? `Quiet ${p.quiet_start.slice(0, 5)} to ${p.quiet_end?.slice(0, 5)}` : undefined}
              value={p.enabled}
              onChange={(v) => setItems((all) => all.map((x) => (x.channel === p.channel ? { ...x, enabled: v } : x)))}
              last={i === items.length - 1}
            />
          ))}
        </Panel>
      ) : null}
      <T v="footnote" muted>Lock-screen messages never show amounts or report findings.</T>
      <ProblemBox problem={act.problem} />
    </Screen>
  );
}
