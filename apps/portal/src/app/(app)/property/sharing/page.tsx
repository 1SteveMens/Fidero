'use client';
import { useState } from 'react';
import { Button, Chip, Empty, Field, ProblemBox, Select, Skeleton, When, useGet } from '@tenmina/web-ui';
import { Ink, PageHead, Section, list, useAction, type Any } from '@/components/kit';

const PURPOSE: Record<string, string> = {
  partner_status: 'See the status of my checks',
  partner_full_report: 'See my full report',
  case_study: 'Use my case, without my name, as a case study',
  marketing: 'Send me news from Tenmina',
};

/** W-24 · SCR-PTL-21: grant and withdraw sharing with partners; case study consent (FR-PTR-002, FR-RPT-011, RUL-16). */
export default function Sharing() {
  const q = useGet<Any>('/v1/consents');
  const partners = useGet<Any[]>('/v1/partner-directory');
  const reports = useGet<Any>('/v1/reports');
  const a = useAction();
  const [f, setF] = useState({ purpose: 'partner_status', partner_client_id: '', report_id: '' });
  const pname = (pid: string) => (partners.data ?? []).find((p: Any) => p.id === pid)?.name ?? 'A partner';
  const rows = list(q.data);
  const needsPartner = f.purpose.startsWith('partner');
  const needsReport = f.purpose === 'partner_full_report' || f.purpose === 'case_study';
  return (
    <Ink>
      <PageHead back={{ href: '/property', label: 'Property' }} label="Sharing and consent" title="Who can see what" sub="Nothing is shared without your consent. You can withdraw it at any time; sharing stops from then on." />
      <Section title="Your consents">
        {q.isLoading ? <Skeleton /> : rows.length ? rows.map((c: Any) => (
          <div key={c.id} className="card stack" style={{ gap: 6 }}>
            <div className="spread"><strong>{PURPOSE[c.purpose] ?? c.purpose}</strong>{c.withdrawn_at ? <Chip>Withdrawn</Chip> : <Chip tone="lime">✓ Given</Chip>}</div>
            {c.partner_client_id ? <div>{pname(c.partner_client_id)}</div> : null}
            <div className="mono muted" style={{ fontSize: 12 }}>Given <When value={c.given_at} withTime />{c.withdrawn_at ? <> · withdrawn <When value={c.withdrawn_at} withTime /></> : null} · text version {c.text_version}</div>
            {!c.withdrawn_at ? <Button variant="ghost" size="sm" busy={a.busy === c.id} onClick={() => a.run(c.id, () => a.post(`/v1/consents/${c.id}/withdraw`), 'Consent withdrawn', () => q.mutate())}>Withdraw</Button> : null}
          </div>
        )) : <Empty>You have not given any consent.</Empty>}
      </Section>
      <Section title="Give a consent">
        <form className="card stack" onSubmit={(e) => { e.preventDefault(); a.run('give', () => a.post('/v1/consents', { purpose: f.purpose, partner_client_id: needsPartner ? f.partner_client_id : undefined, report_id: needsReport && f.report_id ? f.report_id : undefined }), 'Consent recorded', () => q.mutate()); }}>
          <Field label="What"><Select value={f.purpose} onChange={(e) => setF({ ...f, purpose: e.target.value })}>{Object.entries(PURPOSE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></Field>
          {needsPartner ? <Field label="Partner"><Select value={f.partner_client_id} onChange={(e) => setF({ ...f, partner_client_id: e.target.value })} required><option value="">Choose</option>{(partners.data ?? []).map((p: Any) => <option key={p.id} value={p.id}>{p.name} ({p.partner_name})</option>)}</Select></Field> : null}
          {needsReport ? <Field label="Report"><Select value={f.report_id} onChange={(e) => setF({ ...f, report_id: e.target.value })}><option value="">Choose</option>{list(reports.data).filter((r: Any) => r.status === 'released').map((r: Any) => <option key={r.id} value={r.id}>{r.reference}</option>)}</Select></Field> : null}
          <ProblemBox error={a.error} />
          <Button variant="primary" type="submit" busy={a.busy === 'give'}>I agree</Button>
        </form>
      </Section>
      {a.toast}
    </Ink>
  );
}
