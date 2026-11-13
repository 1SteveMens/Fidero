import { router } from 'expo-router';
import { space } from '@tenmina/tokens';
import { Button, ListRow, Panel, Screen } from '@tenmina/ui';
import { Empty, LoadState, itemsOf, useAction, useGet, when } from '@tenmina/mobile';
import { routeFor } from '../lib';

interface Note {
  id: string;
  category: string;
  subject: string;
  body: string;
  link: string;
  needs_action: boolean;
  action_open: boolean;
  unread: boolean;
  created_at: string;
}

/** Messages (FR-NTF-001): what Tenmina told you, newest first. Opening one never approves anything. */
export default function Inbox() {
  const list = useGet<{ items: Note[] }>('/v1/me/notifications');
  const act = useAction();
  const notes = itemsOf(list.data);
  return (
    <Screen
      ground="paper"
      back
      title="Messages"
      trailing={notes.some((n) => n.unread) ? <Button title="Mark all read" variant="quiet" loading={act.busy} onPress={() => void act.run('POST', '/v1/me/notifications/read-all').then(list.reload)} /> : undefined}
    >
      <LoadState loading={list.loading} problem={list.problem} onRetry={list.reload} hasData={!!list.data} />
      {list.data && !notes.length ? <Empty title="No messages" /> : null}
      {notes.length ? (
        <Panel style={{ gap: 0, paddingVertical: space[1] }}>
          {notes.map((n, i) => (
            <ListRow
              key={n.id}
              icon={n.needs_action && n.action_open ? 'hand-left-outline' : n.unread ? 'mail-unread-outline' : 'mail-open-outline'}
              iconTone={n.needs_action && n.action_open ? 'orange' : n.unread ? 'ink' : 'surface'}
              title={n.subject || n.body.slice(0, 60)}
              detail={`${when(n.created_at)} · ${n.body}`}
              onPress={() => {
                if (n.unread) void act.run('POST', `/v1/me/notifications/${n.id}/read`);
                if (n.link) router.push(routeFor(n.link, n.subject, n.body));
              }}
              last={i === notes.length - 1}
            />
          ))}
        </Panel>
      ) : null}
    </Screen>
  );
}
