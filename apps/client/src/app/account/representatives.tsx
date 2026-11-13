import { View } from 'react-native';
import { space } from '@tenmina/tokens';
import { Chip, Label, Panel, Screen, T } from '@tenmina/ui';
import { Empty, LoadState, ProblemBox, day, itemsOf, useAction, useGet, words } from '@tenmina/mobile';
import { Button } from '@tenmina/ui';

interface Rep {
  id: string;
  full_name: string;
  email: string;
  subject_type: string;
  read_only: boolean;
  expires_at: string | null;
  status: string;
}

/** Representatives (SCR-PTL-20, FR-ACC-010): people who see or act for you. They never approve money. */
export default function Representatives() {
  const list = useGet<{ items: Rep[] }>('/v1/me/representatives');
  const act = useAction();
  const reps = itemsOf(list.data);

  return (
    <Screen ground="ink" back title="Representatives">
      <T v="callout" muted>A representative can follow your cases. They cannot approve a payment: only you can.</T>
      <LoadState loading={list.loading} problem={list.problem} onRetry={list.reload} hasData={!!list.data} />
      {list.data && !reps.length ? <Empty title="No representatives" detail="Invite one on the Tenmina website." /> : null}
      {reps.map((r) => (
        <Panel key={r.id}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[3] }}>
            <View style={{ flex: 1 }}>
              <T v="headline">{r.full_name || r.email}</T>
              <Label>{`${r.read_only ? 'Read only' : 'Can act'}${r.subject_type ? ` · ${words(r.subject_type)}` : ' · everything'}${r.expires_at ? ` · until ${day(r.expires_at)}` : ''}`}</Label>
            </View>
            <Chip label={words(r.status)} tone={r.status === 'active' ? 'lime' : 'paper'} />
          </View>
          {r.status === 'active' || r.status === 'invited' ? (
            <Button
              title="Remove"
              variant="danger"
              loading={act.busy}
              onPress={() => {
                void act.run('DELETE', `/v1/me/representatives/${r.id}`).then(() => list.reload());
              }}
            />
          ) : null}
        </Panel>
      ))}
      <ProblemBox problem={act.problem} />
    </Screen>
  );
}
