'use client';
/* Plot status for a partner (J-06, FR-PTR-001, FR-PTR-002): by plot reference or by a point. The full
   report is shown only where the client gave specific consent to share it with you (RUL-16). */
import { useState } from 'react';
import { Button, Card, Field, Input, KV, ProblemBox, Verdict, When } from '@tenmina/web-ui';
import { PageHead, Section, useAct, words } from '@/components/roles/kit';
import { PartnerBar, usePartner } from '@/components/roles/partner';

type Status = { status: string; verdict?: string; report_date?: string; report_reference?: string; full_report_available?: boolean; report_id?: string };
type Full = { report_reference: string; verdict: string | null; report_date: string; pdf_sha256: string; sections: { number: string; title: string; verdict: string | null; findings: string }[] };

const TEXT: Record<string, string> = {
  no_report: 'Tenmina has no report on this plot.', in_progress: 'A check is in progress.', report_exists: 'A report exists.',
  verified: 'Checked by Tenmina.', ambiguous: 'More than one plot matches. Send the plot reference.',
};

export default function PartnerStatus() {
  const { call } = usePartner();
  const act = useAct();
  const [mode, setMode] = useState<'ref' | 'point'>('ref');
  const [ref, setRef] = useState('');
  const [lat, setLat] = useState('');
  const [lng, setLng] = useState('');
  const [res, setRes] = useState<Status | null>(null);
  const [full, setFull] = useState<Full | null>(null);
  return (
    <div className="stack">
      <PartnerBar />
      <PageHead label="Partner" title="Plot status">Ask whether Tenmina has checked a plot. Each question is metered.</PageHead>
      <Card className="stack">
        <div className="seg" role="group" aria-label="Look up by">
          <button type="button" aria-pressed={mode === 'ref'} onClick={() => setMode('ref')}>Plot reference</button>
          <button type="button" aria-pressed={mode === 'point'} onClick={() => setMode('point')}>Location</button>
        </div>
        {mode === 'ref' ? <Field label="Plot reference or site plan number"><Input value={ref} onChange={(e) => setRef(e.target.value)} /></Field> : (
          <div className="grid2" style={{ gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <Field label="Latitude"><Input inputMode="decimal" value={lat} onChange={(e) => setLat(e.target.value)} /></Field>
            <Field label="Longitude"><Input inputMode="decimal" value={lng} onChange={(e) => setLng(e.target.value)} /></Field>
          </div>
        )}
        <Button variant="primary" busy={act.busy === 'q'} disabled={mode === 'ref' ? !ref.trim() : !lat || !lng} onClick={() => act.run('q', async () => {
          setFull(null);
          setRes(await call<Status>('POST', '/v1/partner/plot-status-queries', mode === 'ref' ? { plot_reference: ref } : { point: { lat: Number(lat), lng: Number(lng) } }));
        })}>Check</Button>
      </Card>
      {res ? (
        <Section title="Result">
          <Card className="stack">
            <strong>{TEXT[res.status] ?? words(res.status)}</strong>
            {res.verdict ? <Verdict value={res.verdict} /> : null}
            <KV items={[['Report', res.report_reference ? <span key="r" className="mono">{res.report_reference}</span> : '—'], ['Released', res.report_date ? <When key="d" value={res.report_date} /> : '—'], ['Full report', res.full_report_available ? 'Shared with you by the client' : 'Not shared with you']]} />
            {res.full_report_available && res.report_id ? <Button variant="dark" busy={act.busy === 'f'} onClick={() => act.run('f', async () => setFull(await call<Full>('GET', `/v1/partner/reports/${res.report_id}`)))}>Open the full report</Button> : null}
          </Card>
        </Section>
      ) : null}
      {full ? (
        <div className="card-ink stack">
          <div className="spread"><span className="mono">{full.report_reference}</span><Verdict value={full.verdict} /></div>
          <span>Released <When value={full.report_date} /></span>
          {full.sections.map((s) => <div key={s.number} className="stack" style={{ gap: 2, borderBottom: '1px solid #2c2c2c', paddingBottom: 8 }}><div className="spread"><strong>{s.number}. {s.title}</strong>{s.verdict ? <Verdict value={s.verdict} /> : null}</div><span style={{ fontSize: 14 }}>{s.findings}</span></div>)}
          <span className="mono" style={{ fontSize: 12, overflowWrap: 'anywhere' }}>SHA-256 {full.pdf_sha256}</span>
        </div>
      ) : null}
      <ProblemBox error={act.error} />
    </div>
  );
}
