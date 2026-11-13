'use client';
/* Buyer enquiries on your listings: answer or close. The buyer stays Tenmina's client. */
import { useState } from 'react';
import { Button, Card, Field, ProblemBox, Status, Textarea, When, useGet } from '@tenmina/web-ui';
import { EmptyText, Loaded, PageHead, items, useAct, useApi, type Page } from '@/components/roles/kit';

type Enquiry = { id: string; reference: string; listing_id: string | null; status: string; message: string; answer: string; answered_at: string | null; buyer_name: string | null; created_at: string };

export default function Enquiries() {
  const q = useGet<Page<Enquiry>>('/v1/enquiries');
  return (
    <div className="stack">
      <PageHead label="Selling" title="Enquiries">Questions from buyers about your listings. Answer in plain words; never ask a buyer to pay you outside escrow.</PageHead>
      <Loaded q={q}>{(d) => items(d).length ? items(d).map((e) => <EnquiryCard key={e.id} e={e} onDone={() => q.mutate()} />) : <EmptyText>No enquiries yet.</EmptyText>}</Loaded>
    </div>
  );
}

function EnquiryCard({ e, onDone }: { e: Enquiry; onDone: () => void }) {
  const api = useApi();
  const act = useAct();
  const [answer, setAnswer] = useState('');
  return (
    <Card className="stack">
      <div className="spread"><span className="label">{e.reference} · <When value={e.created_at} /></span><Status value={e.status} needsYou={e.status === 'open' && !e.answer} /></div>
      <p style={{ margin: 0, fontWeight: 700 }}>{e.message}</p>
      {e.answer ? <p style={{ margin: 0 }}>Your answer{e.answered_at ? <> (<When value={e.answered_at} />)</> : null}: {e.answer}</p> : null}
      {e.status === 'open' ? (
        <>
          {!e.answer ? <Field label="Your answer"><Textarea value={answer} onChange={(x) => setAnswer(x.target.value)} /></Field> : null}
          <div className="row">
            {!e.answer ? <Button variant="action" disabled={!answer.trim()} busy={act.busy === 'a'} onClick={() => act.run('a', async () => { await api('POST', `/v1/enquiries/${e.id}/replies`, { answer }); onDone(); }, 'Answer sent.')}>Send answer</Button> : null}
            <Button variant="ghost" busy={act.busy === 'c'} onClick={() => act.run('c', async () => { await api('POST', `/v1/enquiries/${e.id}/closures`); onDone(); }, 'Closed.')}>Close</Button>
          </div>
        </>
      ) : null}
      <ProblemBox error={act.error} />
      {act.toast}
    </Card>
  );
}
