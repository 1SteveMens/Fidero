'use client';
import Link from 'next/link';
import { Empty, NeedsYou, Skeleton, useGet } from '@tenmina/web-ui';
import { Item, PageHead, Section, list, words, type Any } from '@/components/kit';
import { familyOf, toPortal } from '@/lib/links';

const TYPE: Record<string, string> = { construction: 'Build', completion: 'Finish a build', offplan: 'Off-plan', funds: 'Project fund' };

/** The Projects tab: builds with milestone payments, project funds and managed properties (03, 2.1). */
export default function Projects() {
  const home = useGet<Any>('/v1/home');
  const projects = useGet<Any>('/v1/projects');
  const props = useGet<Any>('/v1/managed-properties');
  const repairs = useGet<Any>('/v1/repairs');
  const needs = (home.data?.items ?? []).filter((i: Any) => i.needs_action && familyOf(i.line, i.kind) === 'projects');
  const sentence = (p: Any) => (home.data?.items ?? []).find((i: Any) => i.id === p.id)?.status_text || words(p.status);
  return (
    <div className="stack" style={{ gap: 18 }}>
      <PageHead label="Projects" title="Building and managing at home" sub="Every stage is inspected before it is paid. Money goes only to verified contractors and suppliers." />
      {needs.map((n: Any) => <NeedsYou key={`${n.kind}-${n.id}`} title={n.title} detail={n.status_text} href={toPortal(n.link)} />)}
      <div className="pt-chooser">
        <Link className="btn btn-primary" href="/projects/new">Start a project</Link>
        <Link className="btn btn-ghost" href="/projects/properties/new">Register a property</Link>
      </div>
      <Section title="Projects" count={list(projects.data).length}>
        {projects.isLoading ? <Skeleton /> : list(projects.data).length ? list(projects.data).map((p: Any) => (
          <Item key={p.id} href={`/projects/${p.id}`} meta={`${TYPE[p.type] ?? words(p.type)} · ${words(p.status)}`} title={p.title} sentence={sentence(p)} amount={p.budget} />
        )) : <Empty>No projects yet.</Empty>}
      </Section>
      <Section title="Managed properties" count={list(props.data).length}>
        {list(props.data).length ? list(props.data).map((p: Any) => <Item key={p.id} href={`/projects/properties/${p.id}`} meta={words(p.status)} title={p.title} sentence={(home.data?.items ?? []).find((i: Any) => i.id === p.id)?.status_text || p.locality} />) : <Empty>No managed properties.</Empty>}
      </Section>
      {list(repairs.data).length ? (
        <Section title="Repairs">
          {list(repairs.data).map((r: Any) => <Item key={r.id} href={`/projects/repairs/${r.id}`} meta={`${r.property_title} · ${words(r.status)}`} title={r.title} sentence={r.status === 'quotes_ready' ? 'Choose a quote.' : undefined} needs={r.status === 'quotes_ready'} />)}
        </Section>
      ) : null}
    </div>
  );
}
