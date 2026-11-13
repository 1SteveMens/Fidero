'use client';
/* Premiums (US-INS-002): paid to your account only, never to Tenmina. Confirm what arrived. On black: money. */
import { useState } from 'react';
import { Button, Chip, ProblemBox, Money, When, useGet } from '@tenmina/web-ui';
import { EmptyText, FilePick, Loaded, PageHead, items, useAct, useApi, words, type Page } from '@/components/roles/kit';
import { toBase64 } from '@/components/roles/files';
import type { Premium } from '@/components/roles/insurer';

export default function InsurerPremiums() {
  const q = useGet<Page<Premium>>('/v1/insurance/premiums');
  return (
    <div className="stack">
      <PageHead label="Insurer" title="Premiums received">Premiums go to your account, never to Tenmina: the client pays you directly, or the partner bank pays you from money held for the policy.</PageHead>
      <Loaded q={q}>{(d) => items(d).length ? items(d).map((p) => <PremiumCard key={p.id} p={p} onDone={() => q.mutate()} />) : <EmptyText>No premiums yet.</EmptyText>}</Loaded>
    </div>
  );
}

function PremiumCard({ p, onDone }: { p: Premium; onDone: () => void }) {
  const api = useApi();
  const act = useAct();
  const [file, setFile] = useState<File | null>(null);
  const waiting = p.route === 'client_direct_to_insurer' && ['due', 'overdue', 'client_reported'].includes(p.status);
  async function confirm(received: boolean) {
    await act.run(received ? 'y' : 'n', async () => {
      await api('POST', `/v1/insurance/premiums/${p.id}/insurer-confirmation`, {
        received, ...(file ? { document_base64: await toBase64(file), content_type: file.type || 'application/pdf', file_name: file.name } : {}),
      });
      onDone();
    }, received ? 'Confirmed.' : 'Recorded. Tenmina will follow up.');
  }
  return (
    <div className="card-ink stack">
      <div className="spread"><span className="mono">{p.policy_number}</span><strong style={{ fontSize: 20 }}><Money value={p.amount} /></strong></div>
      <span>Due <When value={p.due_on} /> · {p.route === 'held_funds_to_insurer' ? 'The partner bank pays you from money held for this policy.' : 'The client pays you directly.'}</span>
      <div className="row">{p.paid_at ? <Chip tone="lime">✓ Received <When value={p.paid_at} /></Chip> : <Chip>{words(p.status)}</Chip>}</div>
      {p.client_reported_at ? <span className="muted">The client says they paid <When value={p.client_reported_at} />{p.client_transfer_reference ? `, reference ${p.client_transfer_reference}` : ''}.</span> : null}
      {waiting ? (
        <>
          <FilePick label="Your receipt (optional)" file={file} onFile={setFile} accept="application/pdf,image/*" />
          <div className="row">
            <Button variant="action" busy={act.busy === 'y'} onClick={() => confirm(true)}>We received it</Button>
            <Button variant="ghost" style={{ color: '#fff' }} busy={act.busy === 'n'} onClick={() => confirm(false)}>Not received</Button>
          </div>
        </>
      ) : null}
      <ProblemBox error={act.error} />
      {act.toast}
    </div>
  );
}
