import { useState } from 'react';
import { View } from 'react-native';
import { brand, space } from '@tenmina/tokens';
import { Button, Chip, Choice, Label, Panel, Rise, Screen, T, Tick, haptic } from '@tenmina/ui';
import { Empty, Field, LoadState, ProblemBox, day, itemsOf, useAction, useGet, words } from '@tenmina/mobile';

interface Rep {
  id: string;
  full_name: string;
  email: string;
  subject_type: string;
  read_only: boolean;
  expires_at: string | null;
  status: string;
}

interface CaseRow {
  id: string;
  reference: string;
  title?: string;
  status: string;
}

/**
 * Representatives (SCR-PTL-20, FR-ACC-008, FR-ACC-010): people who follow a
 * case for you, read-only. Invite one here; they never approve or pay
 * anything: only you can.
 */
export default function Representatives() {
  const list = useGet<{ items: Rep[] }>('/v1/me/representatives');
  const cases = useGet<{ items: CaseRow[] }>('/v1/cases');
  const act = useAction();
  const invite = useAction();
  const [inviting, setInviting] = useState(false);
  const [f, setF] = useState({ full_name: '', email: '', case: '' });
  const [sent, setSent] = useState<string>();
  const reps = itemsOf(list.data);
  const myCases = itemsOf(cases.data);

  async function send() {
    const r = await invite.run('POST', '/v1/me/representatives', { email: f.email.trim(), full_name: f.full_name.trim(), subject_type: 'case', subject_id: f.case });
    if (r) {
      haptic('success');
      setSent(f.full_name.trim() || f.email.trim());
      setInviting(false);
      setF({ full_name: '', email: '', case: '' });
      list.reload();
    }
  }

  const ready = f.email.includes('@') && !!f.case;
  return (
    <Screen
      ground="ink"
      back
      title="Representatives"
      footer={
        inviting ? (
          <Button title="Send the invitation" icon="paper-plane-outline" disabled={!ready} loading={invite.busy} onPress={() => void send()} />
        ) : (
          <Button title="Invite a representative" icon="person-add-outline" variant="dark" onPress={() => { setInviting(true); setSent(undefined); invite.clear(); }} />
        )
      }
    >
      <T v="callout" muted>A representative, for example a relative at home, can follow a case and see its updates. They cannot approve a payment: only you can.</T>
      <LoadState loading={list.loading} problem={list.problem} onRetry={list.reload} hasData={!!list.data} />
      {sent ? (
        <Panel style={{ flexDirection: 'row', alignItems: 'center' }}>
          <Tick size={26} />
          <T v="callout" style={{ flex: 1 }}>{`Invitation sent to ${sent}.`}</T>
        </Panel>
      ) : null}
      {list.data && !reps.length && !inviting ? <Empty title="No representatives" detail="Invite someone you trust to follow a case." /> : null}
      {reps.map((r) => (
        <Panel key={r.id}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[3] }}>
            <View style={{ flex: 1 }}>
              <T v="headline">{r.full_name || r.email}</T>
              <Label>{`${r.read_only ? 'Read only' : 'Can act'}${r.subject_type ? ` · ${words(r.subject_type)}` : ' · everything'}${r.expires_at ? ` · until ${day(r.expires_at)}` : ''}`}</Label>
            </View>
            <Chip label={r.status === 'pending' ? 'Invited' : words(r.status)} tone={r.status === 'active' ? 'lime' : 'paper'} />
          </View>
          {r.status === 'active' || r.status === 'pending' ? (
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

      {inviting ? (
        <Rise style={{ gap: space[3] }}>
          <Label>Invite someone</Label>
          <Field label="Their name" value={f.full_name} onChange={(v) => setF({ ...f, full_name: v })} />
          <Field label="Their email" value={f.email} onChange={(v) => setF({ ...f, email: v })} keyboardType="email-address" autoComplete="email" hint="We email them a link. They sign up with this address to see the case." />
          <Label>Which case</Label>
          {cases.loading && !cases.data ? <T v="callout" muted>Loading your cases</T> : null}
          {cases.data && !myCases.length ? <T v="callout" muted>You have no case yet. A representative follows one case.</T> : null}
          <Panel style={{ gap: 0, paddingVertical: space[1] }}>
            {myCases.map((c) => (
              <Choice key={c.id} selected={f.case === c.id} onPress={() => setF({ ...f, case: c.id })} title={c.title || c.reference} detail={`${c.reference} · ${words(c.status)}`} />
            ))}
          </Panel>
          <View style={{ borderLeftWidth: 3, borderLeftColor: brand.lime, paddingLeft: space[3] }}>
            <T v="footnote" muted>They see the case and its updates. They cannot approve, pay or change who gets paid.</T>
          </View>
          <ProblemBox problem={invite.problem} />
          <Button title="Cancel" variant="quiet" onPress={() => setInviting(false)} />
        </Rise>
      ) : null}
    </Screen>
  );
}
