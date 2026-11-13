import { View } from 'react-native';
import { space } from '@tenmina/tokens';
import { Button, Chip, Label, Panel, Screen, T } from '@tenmina/ui';
import { LoadState, ProblemBox, day, useAction, useGet, words } from '@tenmina/mobile';

interface DataRequest {
  id: string;
  type: string;
  status: string;
  due_on: string | null;
  created_at: string;
  completed_at: string | null;
}

/** My data (SCR-PTL-34, FR-DPR-003): ask for a copy of what Tenmina holds about you. */
export default function MyData() {
  const list = useGet<DataRequest[]>('/v1/me/data-requests');
  const act = useAction();
  const open = (list.data ?? []).some((r) => r.type === 'access' && !r.completed_at && r.status !== 'rejected');

  async function ask() {
    const r = await act.run('POST', '/v1/me/data-requests', { type: 'access', details: 'Requested in the Tenmina app' });
    if (r) list.reload();
  }

  return (
    <Screen ground="ink" back title="My data" footer={<Button title={open ? 'A copy is on its way' : 'Ask for a copy'} disabled={open} loading={act.busy} onPress={() => void ask()} />}>
      <T v="callout" muted>We send a copy of the personal data we hold about you, within the time the law allows. You can also ask us to correct it.</T>
      <LoadState loading={list.loading} problem={list.problem} onRetry={list.reload} hasData={!!list.data} />
      {list.data?.length ? (
        <Panel style={{ gap: 0, paddingVertical: space[1] }}>
          {list.data.map((r, i) => (
            <View key={r.id} style={{ flexDirection: 'row', alignItems: 'center', gap: space[3], paddingVertical: space[3], borderTopWidth: i ? 1 : 0, borderTopColor: '#2C2C2C' }}>
              <View style={{ flex: 1 }}>
                <T v="headline" style={{ fontSize: 15 }}>{words(r.type)}</T>
                <Label>{`Asked ${day(r.created_at)}${r.due_on ? ` · due ${day(r.due_on)}` : ''}`}</Label>
              </View>
              <Chip label={words(r.status)} tone={r.completed_at ? 'lime' : 'paper'} />
            </View>
          ))}
        </Panel>
      ) : null}
      <ProblemBox problem={act.problem} />
    </Screen>
  );
}
