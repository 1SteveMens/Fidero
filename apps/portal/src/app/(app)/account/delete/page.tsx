'use client';
import Link from 'next/link';
import { useState } from 'react';
import { Blocked, Button, Chip, CodeBoxes, ProblemBox, Skeleton, When, useGet, useSession } from '@tenmina/web-ui';
import { Ink, PageHead, Section, useAction, words, type Any } from '@/components/kit';
import { toPortal } from '@/lib/links';

/** W-38 · SCR-APP-04 on the web: delete my account, with the preview of what is deleted, what is kept and why. */
export default function DeleteAccount() {
  const { me, stepUp } = useSession();
  const pv = useGet<Any>('/v1/me/deletion-requests/preview');
  const reqs = useGet<Any[]>('/v1/me/deletion-requests');
  const a = useAction();
  const [sure, setSure] = useState(false);
  const [code, setCode] = useState('');
  const p = pv.data;
  const pending = (reqs.data ?? []).find((r: Any) => !['completed', 'rejected'].includes(r.status));
  return (
    <Ink>
      <PageHead back={{ href: '/account', label: 'Account' }} label="Account" title="Delete my account" />
      {pv.isLoading ? <Skeleton lines={5} /> : p ? (
        <>
          <Section title="What we delete">
            <ul style={{ margin: 0, paddingLeft: 18 }}>{(p.deleted ?? []).map((d: string, i: number) => <li key={i}>{d}</li>)}</ul>
          </Section>
          <Section title="What we must keep, and why">
            {(p.kept ?? []).map((k: Any, i: number) => <div key={i} className="card"><strong>{k.what}</strong><div className="muted">{k.why}</div><div className="mono" style={{ fontSize: 12 }}>Until {k.until}</div></div>)}
          </Section>
          {(p.open_matters ?? []).length ? (
            <Section title="Finish these first">
              <Blocked title="Your account cannot be deleted yet">Money or work is still open. We delete your account once these are closed.</Blocked>
              {p.open_matters.map((m: Any) => <Link key={`${m.kind}-${m.id}`} href={toPortal(`/${m.kind === 'case' ? 'cases' : `${m.kind}s`}/${m.id}`) ?? '/'} className="card card-link"><strong>{m.title}</strong><div className="muted">{m.reason}</div></Link>)}
            </Section>
          ) : null}
        </>
      ) : <ProblemBox error={pv.error} />}
      {pending ? <div className="card">You asked to delete your account on <When value={pending.created_at} />. Status: {words(pending.status)}.</div> : (
        <div className="stack">
          <label className="row" style={{ flexWrap: 'nowrap', alignItems: 'flex-start' }}><input type="checkbox" checked={sure} onChange={(e) => setSure(e.target.checked)} style={{ width: 22, height: 22, flex: 'none' }} /> <span>I understand. Delete my account{p?.can_complete_now ? ' now' : ' when the open matters are closed'}.</span></label>
          {me?.mfa_enabled ? <><span className="muted">Code from your authenticator app</span><CodeBoxes value={code} onChange={setCode} /></> : null}
          <ProblemBox error={a.error} />
          <Button variant="danger" disabled={!sure || (!!me?.mfa_enabled && code.length !== 6)} busy={!!a.busy}
            onClick={() => a.run('del', async () => { if (me?.mfa_enabled) await stepUp(code); return a.post('/v1/me/deletion-requests', { confirm: true, source: 'portal' }); }, 'Request received', () => reqs.mutate())}>Delete my account</Button>
          <Chip>This cannot be undone</Chip>
        </div>
      )}
      {a.toast}
    </Ink>
  );
}
