'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button, Chip, Empty, ProblemBox, Skeleton, Tabs, When, useGet } from '@tenmina/web-ui';
import { PageHead, list, useAction, type Any } from '@/components/kit';
import { toPortal } from '@/lib/links';

/** Messages from Tenmina (FR-NTF-001): all, unread, and what needs action. */
export default function Inbox() {
  const [tab, setTab] = useState('all');
  const q = useGet<Any>('/v1/me/notifications', tab === 'unread' ? { unread: true } : tab === 'action' ? { needs_action: true } : undefined);
  const count = useGet<Any>('/v1/me/notifications/unread-count');
  const a = useAction();
  const router = useRouter();
  const rows = list(q.data);
  async function open(m: Any) {
    if (m.unread) await a.post(`/v1/me/notifications/${m.id}/read`).catch(() => undefined);
    const to = toPortal(m.link);
    if (to) router.push(to);
    else { q.mutate(); count.mutate(); }
  }
  return (
    <div className="stack" style={{ gap: 16 }}>
      <PageHead label="Inbox" title="Messages" sub={count.data ? `${count.data.unread ?? count.data.count ?? 0} unread` : undefined}
        right={<Button variant="ghost" size="sm" busy={a.busy === 'all'} onClick={() => a.run('all', () => a.post('/v1/me/notifications/read-all'), 'All marked as read', () => { q.mutate(); count.mutate(); })}>Mark all read</Button>} />
      <Tabs current={tab} onChange={setTab} items={[{ key: 'all', label: 'All' }, { key: 'unread', label: 'Unread' }, { key: 'action', label: 'Needs action' }]} />
      <ProblemBox error={q.error ?? a.error} />
      {q.isLoading ? <Skeleton lines={5} /> : !rows.length ? <Empty>{tab === 'action' ? 'Nothing needs you.' : 'No messages.'}</Empty> : (
        <div className="stack" style={{ gap: 8 }}>
          {rows.map((m: Any) => {
            const needs = m.needs_action && m.action_open !== false && !m.action_done_at;
            return (
              <button key={m.id} className="card card-link" style={{ border: 0, textAlign: 'left', cursor: 'pointer', font: 'inherit', color: 'inherit', width: '100%' }} onClick={() => open(m)}>
                <div className="spread" style={{ flexWrap: 'nowrap', alignItems: 'flex-start' }}>
                  <div style={{ minWidth: 0 }}>
                    <div className="row" style={{ gap: 6 }}>
                      {m.unread ? <span aria-label="Unread" style={{ width: 9, height: 9, borderRadius: 9, background: 'var(--ink)', display: 'inline-block' }} /> : null}
                      <span className="label"><When value={m.created_at} withTime /></span>
                    </div>
                    {m.subject ? <div style={{ fontWeight: m.unread ? 800 : 600 }}>{m.subject}</div> : null}
                    <div style={{ fontSize: 15, fontWeight: !m.subject && m.unread ? 700 : 400 }}>{m.body}</div>
                  </div>
                  {needs ? <Chip tone="orange">Needs you</Chip> : m.action_done_at ? <Chip>Done</Chip> : null}
                </div>
              </button>
            );
          })}
        </div>
      )}
      <p className="muted" style={{ fontSize: 14 }}>Messages about a case are also in that case. <Link href="/account/notifications">Choose how we contact you</Link>.</p>
      {a.toast}
    </div>
  );
}
