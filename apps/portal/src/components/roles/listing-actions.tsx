'use client';
/* Actions on a public listing for a signed-in buyer: read the full report (RUL-14), ask a question, or
   reserve (SCR-PTL-28): a fresh search starts and a purchase escrow is proposed (FR-LST-005). */
import Link from 'next/link';
import { useState } from 'react';
import { Button, Card, Field, ProblemBox, Textarea, Verdict, useSession } from '@tenmina/web-ui';
import { useAct, useApi } from './kit';

type ReportView = { reference: string; verdict: string; released_at: string; pdf_sha256: string; pdf: { url?: string }; sections: { number?: string; label?: string; title?: string; verdict?: string | null }[] };

export function ListingActions({ id, live, hasReport }: { id: string; live: boolean; hasReport: boolean }) {
  const { me, loading } = useSession();
  const api = useApi();
  const act = useAct();
  const [msg, setMsg] = useState('');
  const [asked, setAsked] = useState(false);
  const [report, setReport] = useState<ReportView | null>(null);
  const [reserved, setReserved] = useState<{ reference: string } | null>(null);
  if (loading) return null;
  if (!me) {
    return (
      <Card className="stack">
        <strong>Sign in to read the full report, ask a question or reserve.</strong>
        <div className="row">
          <Link className="btn btn-primary" href={`/login?next=/listings/${id}`}>Sign in</Link>
          <Link className="btn btn-ghost" href={`/register?next=/listings/${id}`}>Create an account</Link>
        </div>
      </Card>
    );
  }
  return (
    <div className="stack">
      {hasReport ? (
        report ? (
          <div className="card-ink stack">
            <div className="spread"><span className="mono">{report.reference}</span><Verdict value={report.verdict} /></div>
            {report.sections.map((s, n) => <div key={n} className="statline"><span>{s.number ?? s.label ? `${s.number ?? s.label}. ` : ''}{s.title}</span><span>{s.verdict ? <Verdict value={s.verdict} /> : null}</span></div>)}
            <span className="mono" style={{ fontSize: 12, overflowWrap: 'anywhere' }}>SHA-256 {report.pdf_sha256}</span>
            {report.pdf?.url ? <a className="btn btn-primary" href={report.pdf.url} target="_blank" rel="noopener noreferrer">Open the PDF</a> : null}
            <Link className="btn btn-ghost" style={{ color: '#fff' }} href="/check">Check this PDF is genuine</Link>
          </div>
        ) : <Button variant="dark" busy={act.busy === 'r'} onClick={() => act.run('r', async () => setReport(await api<ReportView>('GET', `/v1/listings/${id}/report`)))}>Read the full report</Button>
      ) : null}
      {live && me.roles.includes('CL') ? (
        reserved ? (
          <Card className="stack"><strong>Reserved: {reserved.reference}</strong><span>Tenmina is running a fresh search for you. We will tell you when the escrow terms are ready.</span><Link className="btn btn-primary" href="/">Go to my home</Link></Card>
        ) : (
          <Card className="stack">
            <strong>Reserve this plot</strong>
            <span style={{ fontSize: 14 }}>Tenmina runs a fresh official search for you and proposes a purchase escrow at the partner bank. You pay nothing to the seller directly.</span>
            <Button variant="action" busy={act.busy === 'res'} onClick={() => act.run('res', async () => setReserved(await api<{ reference: string }>('POST', `/v1/listings/${id}/reservations`)))}>Reserve</Button>
          </Card>
        )
      ) : null}
      <Card className="stack">
        {asked ? <strong>Question sent. The seller answers through Tenmina.</strong> : (
          <>
            <Field label="Ask the seller a question"><Textarea value={msg} onChange={(e) => setMsg(e.target.value)} /></Field>
            <Button variant="ghost" disabled={!msg.trim()} busy={act.busy === 'q'} onClick={() => act.run('q', async () => { await api('POST', `/v1/listings/${id}/enquiries`, { message: msg }); setAsked(true); })}>Send question</Button>
          </>
        )}
      </Card>
      <ProblemBox error={act.error} />
    </div>
  );
}
