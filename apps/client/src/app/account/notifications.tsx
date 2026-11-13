import { useEffect, useState } from 'react';
import { Switch, View } from 'react-native';
import { brand, space } from '@tenmina/tokens';
import { Button, Label, Panel, Screen, T } from '@tenmina/ui';
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
            <View key={p.channel} style={{ flexDirection: 'row', alignItems: 'center', gap: space[3], minHeight: 56, borderTopWidth: i ? 1 : 0, borderTopColor: '#2C2C2C' }}>
              <View style={{ flex: 1 }}>
                <T v="headline" style={{ fontSize: 15 }}>{NAMES[p.channel] ?? words(p.channel)}</T>
                {p.quiet_start ? <T v="footnote" muted>{`Quiet ${p.quiet_start.slice(0, 5)} to ${p.quiet_end?.slice(0, 5)}`}</T> : null}
              </View>
              <Switch
                value={p.enabled}
                onValueChange={(v) => setItems((all) => all.map((x) => (x.channel === p.channel ? { ...x, enabled: v } : x)))}
                trackColor={{ true: brand.lime, false: '#3A3A3A' }}
                thumbColor={brand.ink}
                accessibilityLabel={NAMES[p.channel] ?? p.channel}
              />
            </View>
          ))}
        </Panel>
      ) : null}
      <T v="footnote" muted>Lock-screen messages never show amounts or report findings.</T>
      <ProblemBox problem={act.problem} />
    </Screen>
  );
}
