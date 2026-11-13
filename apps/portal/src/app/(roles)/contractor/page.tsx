'use client';
/* Contractor home: the projects you build (J-03). Milestone evidence is captured in Tenmina Field (RUL-08). */
import { Money, NeedsYou, Status, useGet } from '@tenmina/web-ui';
import { EmptyText, Loaded, PageHead, RowLink, Section, items, words, type Page } from '@/components/roles/kit';
import type { Defect, Project, Variation } from '@/components/roles/build';

export default function ContractorHome() {
  const q = useGet<Page<Project>>('/v1/projects');
  const defects = useGet<Page<Defect>>('/v1/defects', { status: 'open' });
  const openDefects = items(defects.data).filter((d) => d.status === 'open');
  return (
    <div className="stack">
      <PageHead label="Building" title="Your projects">Paid stage by stage by the partner bank, after evidence, an independent inspection and the client&apos;s approval.</PageHead>
      {openDefects.length ? <NeedsYou title={`${openDefects.length} ${openDefects.length === 1 ? 'defect' : 'defects'} to fix`} detail="Their value is held back until fixed." href="/contractor/defects" /> : null}
      <Loaded q={q}>
        {(d) => items(d).length ? (
          <Section title="Projects">
            {items(d).map((p) => <ProjectRow key={p.id} p={p} />)}
          </Section>
        ) : <EmptyText>No projects yet. Tenmina adds you when a client chooses you.</EmptyText>}
      </Loaded>
    </div>
  );
}

function ProjectRow({ p }: { p: Project }) {
  const v = useGet<Variation[]>(`/v1/projects/${p.id}/variations`);
  const waiting = (v.data ?? []).filter((x) => x.status === 'proposed' && !x.contractor_agreed_at).length;
  return <RowLink href={`/contractor/projects/${p.id}`} meta={words(p.type)} title={p.title} sub={p.budget ? <>Budget <Money value={p.budget} /></> : undefined} right={<Status value={waiting ? 'variation to agree' : p.status} needsYou={!!waiting} />} />;
}
