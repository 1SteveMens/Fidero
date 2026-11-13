'use client';
/* Your track record on Tenmina's panel (US-RAT-001, US-RAT-003): what clients see when they choose. */
import { Card, Skeleton, useGet } from '@tenmina/web-ui';
import { EmptyText, PageHead, Section, items, type Page } from '@/components/roles/kit';
import type { Project } from '@/components/roles/build';

type Record = { projects: number; projects_completed: number; milestones_paid: number; inspections: number; inspections_passed: number; inspections_failed: number; defects_recorded: number; removed: boolean };

export default function Ratings() {
  const q = useGet<Page<Project>>('/v1/projects');
  const ids = [...new Set(items(q.data).map((p) => p.contractor_id).filter(Boolean))] as string[];
  return (
    <div className="stack">
      <PageHead label="Building" title="Track record">Counted from inspections and payments, not from opinions. Clients see this when they choose a contractor.</PageHead>
      {q.isLoading ? <Skeleton /> : null}
      {!q.isLoading && !ids.length ? <EmptyText>Your track record starts with your first project.</EmptyText> : null}
      {ids.map((id) => <TrackRecord key={id} id={id} name={items(q.data).find((p) => p.contractor_id === id)?.contractor_name ?? 'You'} />)}
    </div>
  );
}

function TrackRecord({ id, name }: { id: string; name: string }) {
  const q = useGet<Record>(`/v1/panel-members/${id}/track-record`);
  const r = q.data;
  return (
    <Section title={name}>
      {r ? (
        <Card>
          {([['Projects', r.projects], ['Projects completed', r.projects_completed], ['Milestones paid', r.milestones_paid], ['Inspections', r.inspections], ['Passed', r.inspections_passed], ['Failed', r.inspections_failed], ['Defects recorded', r.defects_recorded]] as [string, number][]).map(([k, v]) => (
            <div key={k} className="statline"><span>{k}</span><span className="v">{v}</span></div>
          ))}
        </Card>
      ) : <Skeleton />}
    </Section>
  );
}
