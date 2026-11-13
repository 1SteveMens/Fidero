'use client';
import { Status, Verdict, When, useGet } from '@tenmina/web-ui';
import { EmptyText, Loaded, PageHead, RowLink, Section, items, type Page } from '@/components/roles/kit';
import type { ReportRow } from '@/components/roles/work';

export default function Reports() {
  const q = useGet<Page<ReportRow>>('/v1/reports');
  return (
    <div className="stack">
      <PageHead label="My work" title="Reports">Reports on cases you work on. Fill and sign your sections; the lawyer and a second reviewer approve before release (RUL-03).</PageHead>
      <Loaded q={q}>
        {(d) => {
          const all = items(d);
          const open = all.filter((r) => r.status === 'draft' || r.status === 'in_review' || r.status === 'approved');
          const done = all.filter((r) => !open.includes(r));
          return (
            <>
              <Section title="To fill, sign or approve">
                {open.length ? open.map((r) => <RowLink key={r.id} href={`/work/reports/${r.id}`} meta={r.case_reference} title={r.reference} right={<Status value={r.status} needsYou={r.status === 'draft'} />} />) : <EmptyText>Nothing to fill or sign.</EmptyText>}
              </Section>
              <Section title="Released">
                {done.length ? done.map((r) => <RowLink key={r.id} href={`/work/reports/${r.id}`} meta={r.case_reference} title={r.reference} sub={r.released_at ? <>Released <When value={r.released_at} /></> : undefined} right={<Verdict value={r.overall_verdict} />} />) : <EmptyText>No released reports yet.</EmptyText>}
              </Section>
            </>
          );
        }}
      </Loaded>
    </div>
  );
}
