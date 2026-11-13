'use client';
/* A stage payment as the contractor sees it: amount, held-back defects, who is paid, and on the
   client_direct route the contractor's confirmation that the money arrived. */
import { useState } from 'react';
import { Button, Chip, Field, Input, Money, ProblemBox, When } from '@tenmina/web-ui';
import { PayeeLine, useAct, useApi, words } from './kit';
import type { ProjectPayment } from './build';

export function PaymentCard({ x, onDone }: { x: ProjectPayment; onDone: () => void }) {
  const api = useApi();
  const act = useAct();
  const [note, setNote] = useState('');
  const confirmable = x.route === 'client_direct' && !!x.client_paid_at && !x.paid_at;
  return (
    <div className="card-ink stack">
      <div className="spread"><span>{x.label}</span><strong style={{ fontSize: 20 }}><Money value={x.amount} /></strong></div>
      {x.holdback && Number(x.holdback.amount) > 0 ? <span className="muted">Held back for defects: <Money value={x.holdback} /></span> : null}
      {x.payee ? <PayeeLine planned={!x.paid_at} name={x.payee.name} last4={x.payee.account_last4} bank={x.payee.bank_name} /> : null}
      <div className="row">{x.paid_at ? <Chip tone="lime">✓ Paid <When value={x.paid_at} /></Chip> : <Chip>{words(x.status)}</Chip>}{x.bank_reference ? <span className="mono" style={{ fontSize: 12 }}>{x.bank_reference}</span> : null}</div>
      {x.route === 'escrow' && !x.paid_at ? <span className="muted" style={{ fontSize: 14 }}>The money is held by the partner bank, not by Tenmina. The client approves, then two Tenmina staff.</span> : null}
      {confirmable ? (
        <>
          <span>The client says they paid on <When value={x.client_paid_at} />. Confirm when it reaches your account.</span>
          <Field label="Note (optional)"><Input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
          <Button variant="primary" busy={act.busy === 'r'} onClick={() => act.run('r', async () => { await api('POST', `/v1/project-payments/${x.id}/receipt`, { note }); onDone(); }, 'Thank you. Receipt confirmed.')}>The money arrived</Button>
        </>
      ) : null}
      <ProblemBox error={act.error} />
      {act.toast}
    </div>
  );
}
