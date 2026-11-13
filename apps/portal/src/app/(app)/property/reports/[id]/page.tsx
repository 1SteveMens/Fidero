'use client';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button, Field, Input, ProblemBox, Skeleton, Verdict, When, call, useGet } from '@tenmina/web-ui';
import { ActionDialog, Copy, FilePick, Ink, PageHead, Section, useAction, useCountry, words, type Any } from '@/components/kit';

const MEANING: Record<string, [string, string]> = {
  green: ['Safe to proceed', 'We found nothing that should stop the purchase.'],
  amber: ['Fix before you pay', 'We found issues that can be resolved before you buy.'],
  red: ['We advise you not to buy', 'We found a problem that cannot be fixed safely.'],
};

function groups(h: string) { return (h.match(/.{1,4}/g) ?? []).join(' '); }

async function sha256(f: File) {
  const d = await crypto.subtle.digest('SHA-256', await f.arrayBuffer());
  return Array.from(new Uint8Array(d)).map((b) => b.toString(16).padStart(2, '0')).join('');
}

/** W-08 · SCR-PTL-14: the report on black, verdict chip with icon and word, the PDF and its fingerprint. */
export default function ReportViewer() {
  const { id } = useParams<{ id: string }>();
  const country = useCountry();
  const router = useRouter();
  const q = useGet<Any>(`/v1/reports/${id}`);
  const a = useAction();
  const [check, setCheck] = useState<null | boolean>(null);
  const [escrow, setEscrow] = useState(false);
  const [price, setPrice] = useState('');
  const [seller, setSeller] = useState('');
  if (q.isLoading) return <Ink><Skeleton lines={6} /></Ink>;
  if (!q.data) return <Ink><ProblemBox error={q.error} /></Ink>;
  const r = q.data;
  const v = (r.overall_verdict ?? '').toLowerCase();
  const [head, meaning] = MEANING[v] ?? ['', ''];
  const graded = (r.sections ?? []).filter((s: Any) => s.in_verdict_rule);
  const reasons = graded.filter((s: Any) => s.verdict && s.verdict !== 'green');
  async function openPdf() {
    const l = await a.run('pdf', () => call<Any>(a.client, 'GET', `/v1/reports/${id}/pdf`));
    if (l?.url) window.open(l.url, '_blank', 'noopener');
  }
  return (
    <Ink>
      <PageHead back={{ href: `/property/cases/${r.case}`, label: `Case ${r.case_reference}` }} label={`Report ${r.reference}`} title="Your report" />
      {r.supersedes ? <div className="card">This report was corrected. Reason: {r.correction_reason}. Version {r.version} replaces the earlier version.</div> : null}
      <section className="card stack" style={{ gap: 8 }}>
        <div className="row"><Verdict value={r.overall_verdict} /><strong style={{ fontSize: 20 }}>{head}</strong></div>
        <p style={{ margin: 0 }}>{meaning}</p>
      </section>
      {reasons.length ? (
        <Section title="Why">
          <ul style={{ margin: 0, paddingLeft: 20 }}>{reasons.map((s: Any) => <li key={s.number}><strong>{s.title}.</strong> {s.text}</li>)}</ul>
        </Section>
      ) : null}
      {r.conditions?.length ? (
        <Section title={v === 'red' ? 'What would have to change' : 'Before you pay'}>
          {r.conditions.map((c: Any) => (
            <div key={c.id} className="check-row">
              <span className="tick" aria-hidden>{c.position}</span>
              <div><div style={{ fontWeight: 700 }}>{c.text}</div><div className="muted" style={{ fontSize: 13 }}>Who: {words(c.responsible)} · Proof: {c.closing_evidence}</div></div>
              <span />
            </div>
          ))}
        </Section>
      ) : null}
      {graded.length ? (
        <Section title="Section verdicts">
          <div className="card stack" style={{ gap: 0 }}>
            {graded.map((s: Any) => (
              <details key={s.number} className="check-row" style={{ display: 'block' }}>
                <summary className="spread" style={{ cursor: 'pointer', listStyle: 'none', minHeight: 44 }}><span><span className="mono muted">{s.label}</span> {s.title}</span><Verdict value={s.verdict} /></summary>
                <p className="muted" style={{ margin: '6px 0 0' }}>{s.text}</p>
              </details>
            ))}
          </div>
        </Section>
      ) : null}
      {r.signatures?.length ? (
        <Section title="Signed by">
          {r.signatures.map((s: Any, i: number) => (
            <div key={i} className="card"><strong>{s.signer_name}</strong> · {words(s.role === 'LW' ? 'lawyer' : s.role === 'SV' ? 'surveyor' : s.role === 'IN' ? 'inspector' : s.role)}<div className="mono muted" style={{ fontSize: 13 }}>{s.licence_body} {s.licence_number} · section {s.section_label} · <When value={s.signed_at} /></div></div>
          ))}
        </Section>
      ) : null}
      <section className="card stack">
        <Button variant="primary" busy={a.busy === 'pdf'} onClick={openPdf} block>Download the PDF</Button>
        <div className="label" style={{ color: '#a9a69e' }}>Version {r.version} · released <When value={r.released_at} /> · SHA-256 fingerprint</div>
        <div className="mono" style={{ fontSize: 14, overflowWrap: 'anywhere' }}>{groups(r.pdf_sha256 || '')}</div>
        <div className="row">
          {r.pdf_sha256 ? <Copy value={r.pdf_sha256} /> : null}
          <FilePick label="Check a PDF against it" accept="application/pdf" onFile={async (f) => setCheck((await sha256(f)) === r.pdf_sha256)} />
        </div>
        {check === true ? <span className="proof">✓ This file is the report we released.</span> : check === false ? <span className="card" style={{ background: '#242424' }}>This file is not the report we released. Do not rely on it.</span> : null}
        <small className="muted">The check runs in your browser. The file is not sent anywhere.</small>
      </section>
      {v === 'green' || v === 'amber' ? (
        <section className="stack">
          <p className="muted" style={{ margin: 0 }}>Buy through escrow: a licensed bank holds the price and pays the seller only when every condition is closed and you approve.</p>
          <Button variant="primary" onClick={() => setEscrow(true)} block>Buy through escrow</Button>
        </section>
      ) : v === 'red' ? <Link href="/property/order" className="btn btn-primary">Check another plot</Link> : null}
      <ProblemBox error={a.error} />
      <ActionDialog ink open={escrow} onClose={() => setEscrow(false)} title="Propose an escrow" submit="Propose the escrow" busy={a.busy === 'esc'} error={a.error}
        onSubmit={() => a.run('esc', () => a.post<Any>('/v1/escrows', { kind: 'purchase', country: country.code, title: `Purchase: ${r.case_reference}`, report_id: r.id, case_id: r.case, agreed_price: { amount: price, currency: country.currency }, parties: seller ? [{ role: 'seller', name: seller }] : [] }), undefined, (e) => router.push(`/property/escrows/${e.id}`))}>
        <p className="muted" style={{ margin: 0 }}>The report&apos;s conditions become the escrow&apos;s conditions. Tenmina checks the seller and their bank account before anything can be paid.</p>
        <Field label={`Agreed price (${country.currency})`}><Input inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value.replace(/[^\d.]/g, ''))} required /></Field>
        <Field label="Seller's name"><Input value={seller} onChange={(e) => setSeller(e.target.value)} /></Field>
      </ActionDialog>
      {a.toast}
    </Ink>
  );
}
