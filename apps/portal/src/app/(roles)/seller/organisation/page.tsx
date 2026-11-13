'use client';
/* Organisation account with several users (US-ACC-011): see, add and remove members. Admins only change it. */
import { useState } from 'react';
import { Button, Card, Field, Input, KV, ProblemBox, Select, Status, useGet, useSession } from '@tenmina/web-ui';
import { EmptyText, Loaded, PageHead, Section, items, useAct, useApi, words, type Page } from '@/components/roles/kit';

type Org = { id: string; name: string; kind: string; country: string; registration_number: string; status: string; contact_email: string; contact_phone: string; address: string; my_org_role: string };
type Member = { id: string; person: { id: string; full_name: string; email: string }; org_role: string; status: string };

export default function Organisation() {
  const q = useGet<Page<Org>>('/v1/organisations');
  return (
    <div className="stack">
      <PageHead label="Selling" title="Your team">People who can work on your organisation&apos;s listings.</PageHead>
      <Loaded q={q}>{(d) => items(d).length ? items(d).map((o) => <OrgCard key={o.id} o={o} />) : <EmptyText>You are not part of an organisation yet. Ask Tenmina to set one up.</EmptyText>}</Loaded>
    </div>
  );
}

function OrgCard({ o }: { o: Org }) {
  const { me } = useSession();
  const api = useApi();
  const act = useAct();
  const m = useGet<Member[]>(`/v1/organisations/${o.id}/members`);
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [role, setRole] = useState('member');
  const admin = o.my_org_role === 'admin';
  return (
    <>
      <Card><KV items={[['Name', o.name], ['Type', words(o.kind)], ['Country', o.country], ['Registration', o.registration_number || '—'], ['Status', <Status key="s" value={o.status} />]]} /></Card>
      <Section title="Members">
        {(m.data ?? []).filter((x) => x.status === 'active').map((x) => (
          <Card key={x.id} className="spread">
            <div style={{ minWidth: 0 }}><strong>{x.person.full_name}</strong><div className="muted" style={{ fontSize: 14, overflowWrap: 'anywhere' }}>{x.person.email} · {x.org_role}</div></div>
            {admin && x.person.id !== me?.id ? <Button size="sm" variant="ghost" busy={act.busy === x.id} onClick={() => act.run(x.id, async () => { await api('DELETE', `/v1/organisations/${o.id}/members/${x.id}`); await m.mutate(); }, 'Removed.')}>Remove</Button> : null}
          </Card>
        ))}
        {admin ? (
          <Card className="stack">
            <h3 style={{ margin: 0 }}>Add a member</h3>
            <Field label="Email"><Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
            <Field label="Full name"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <Field label="Can"><Select value={role} onChange={(e) => setRole(e.target.value)}><option value="member">Work on listings</option><option value="admin">Also manage the team</option></Select></Field>
            <Button variant="dark" disabled={!email} busy={act.busy === 'add'} onClick={() => act.run('add', async () => { await api('POST', `/v1/organisations/${o.id}/members`, { email, full_name: name, org_role: role }); setEmail(''); setName(''); await m.mutate(); }, 'Added. New people get an invitation by email.')}>Add</Button>
          </Card>
        ) : <p className="muted">Only an admin of {o.name} can change the team.</p>}
        <ProblemBox error={act.error ?? m.error} />
      </Section>
      {act.toast}
    </>
  );
}
