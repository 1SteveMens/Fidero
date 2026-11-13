'use client';
/* Visits and field work for people without Tenmina Field installed. Check-in, check-out and photos that
   must come from the app's own camera stay in the app (RUL-08, RUL-23); everything else works here. */
import Link from 'next/link';
import { When, useGet, useSession } from '@tenmina/web-ui';
import { EmptyText, Loaded, PageHead, RowLink, Section } from '@/components/roles/kit';
import { inboxHref, type InboxItem } from '@/components/roles/work';

export default function Field() {
  const { hasRole } = useSession();
  const q = useGet<InboxItem[]>('/v1/mobile/inbox');
  return (
    <div className="stack">
      <PageHead label="My work" title="Visits and field work">Inspections, care visits, errands and site tasks assigned to you.</PageHead>
      <div className="banner-info">Check in, check out and take sealed photos in the Tenmina Field app. This page shows your work and the steps you can do from a browser.</div>
      {hasRole('QS') ? <Link href="/work/boq" className="card card-link"><div className="label">Quantity surveyor</div><div style={{ fontWeight: 700 }}>Bills of quantities to review</div></Link> : null}
      <Loaded q={q}>
        {(d) => (
          <Section title="Assigned to you">
            {d.length ? d.map((i) => (
              <RowLink key={i.subject_type + i.subject_id} href={inboxHref(i)} meta={i.kind.replace(/_/g, ' ')} title={i.title}
                sub={i.state_reason || i.address} right={i.due_at ? <When value={i.due_at} /> : undefined} />
            )) : <EmptyText>Nothing assigned to you right now.</EmptyText>}
          </Section>
        )}
      </Loaded>
    </div>
  );
}
