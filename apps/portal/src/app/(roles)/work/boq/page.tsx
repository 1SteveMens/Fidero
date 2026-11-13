'use client';
import { Status, useGet } from '@tenmina/web-ui';
import { EmptyText, Loaded, PageHead, RowLink, items, type Page } from '@/components/roles/kit';

type Project = { id: string; title: string; type: string; status: string; contractor_name: string | null; budget_approved_at: string | null };

export default function BoqList() {
  const q = useGet<Page<Project>>('/v1/projects');
  return (
    <div className="stack">
      <PageHead back={{ href: '/work/field', label: 'Visits' }} label="Quantity surveyor" title="Bills of quantities">Projects you are assigned to. Upload the bill and set the milestone split (US-BLD-002).</PageHead>
      <Loaded q={q}>
        {(d) => items(d).length ? items(d).map((p) => (
          <RowLink key={p.id} href={`/work/boq/${p.id}`} meta={p.type.replace(/_/g, ' ')} title={p.title} sub={p.contractor_name ?? 'No contractor yet'}
            right={<Status value={p.budget_approved_at ? 'budget approved' : 'needs bill'} needsYou={!p.budget_approved_at} />} />
        )) : <EmptyText>No projects assigned to you.</EmptyText>}
      </Loaded>
    </div>
  );
}
