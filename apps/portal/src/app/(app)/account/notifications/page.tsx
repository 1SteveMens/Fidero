'use client';
import { useEffect, useState } from 'react';
import { Button, Field, Input, ProblemBox, Skeleton, useGet } from '@tenmina/web-ui';
import { Ink, PageHead, Section, useAction, words, type Any } from '@/components/kit';

const CHANNEL: Record<string, string> = { in_app: 'In Tenmina', email: 'Email', sms: 'SMS', whatsapp: 'WhatsApp', push: 'Phone notifications' };
const CATS = ['status', 'task', 'request', 'approval', 'reminder', 'money', 'safety', 'account', 'marketing'];
const MANDATORY = ['money', 'safety'];

/** SCR-PTL-20: notification preferences per channel. Money and safety messages always reach you in Tenmina. */
export default function Notifications() {
  const q = useGet<Any[]>('/v1/me/notification-preferences');
  const a = useAction();
  const [items, setItems] = useState<Any[] | null>(null);
  useEffect(() => { if (q.data && !items) setItems(q.data); }, [q.data, items]);
  if (!items) return <Ink><Skeleton /></Ink>;
  const set = (i: number, k: string, v: unknown) => setItems(items.map((x, j) => (j === i ? { ...x, [k]: v } : x)));
  return (
    <Ink>
      <PageHead back={{ href: '/account', label: 'Account' }} label="Account" title="Notifications" sub="Phone messages never show amounts above the limit. Open the app to see them." />
      {items.map((p, i) => (
        <Section key={p.channel} title={CHANNEL[p.channel] ?? words(p.channel)}>
          <div className="card stack">
            <label className="row" style={{ flexWrap: 'nowrap' }}><input type="checkbox" checked={p.enabled} disabled={p.channel === 'in_app'} onChange={(e) => set(i, 'enabled', e.target.checked)} style={{ width: 22, height: 22 }} /> {p.channel === 'in_app' ? 'Always on' : 'On'}</label>
            {p.enabled && p.channel !== 'in_app' ? (
              <>
                <div className="row">
                  <Field label="Quiet from"><Input type="time" value={p.quiet_start ?? ''} onChange={(e) => set(i, 'quiet_start', e.target.value || null)} /></Field>
                  <Field label="Until"><Input type="time" value={p.quiet_end ?? ''} onChange={(e) => set(i, 'quiet_end', e.target.value || null)} /></Field>
                </div>
                <div className="label">Topics</div>
                <div className="tile-btns">
                  {CATS.map((c) => {
                    const on = !(p.muted_categories ?? []).includes(c);
                    return <button type="button" key={c} aria-pressed={on} disabled={MANDATORY.includes(c)} className={`btn btn-sm ${on ? 'btn-dark' : 'btn-ghost'}`} onClick={() => set(i, 'muted_categories', on ? [...(p.muted_categories ?? []), c] : (p.muted_categories ?? []).filter((x: string) => x !== c))}>{words(c)}</button>;
                  })}
                </div>
              </>
            ) : null}
          </div>
        </Section>
      ))}
      <ProblemBox error={a.error} />
      <Button variant="primary" busy={!!a.busy} onClick={() => a.run('s', () => a.post('/v1/me/notification-preferences', { items: items.map((p) => ({ ...p, quiet_start: p.quiet_start || null, quiet_end: p.quiet_end || null })) }, 'PUT'), 'Saved', () => q.mutate())}>Save</Button>
      {a.toast}
    </Ink>
  );
}
