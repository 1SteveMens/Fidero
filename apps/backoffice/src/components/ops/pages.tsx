'use client';
/* A section (tabs of lists) and a detail screen (header, actions, fields, related lists). */
import React, { Suspense } from 'react';
import Link from 'next/link';
import { useParams, usePathname, useRouter, useSearchParams } from 'next/navigation';
import { Empty, ProblemBox, Skeleton, Status, Verdict, useGet, useSession } from '@tenmina/web-ui';
import { ActionButton, OpsToasts } from './actions';
import { humanize, titleOf, Value, isMoney } from './fmt';
import { ResourceList, SubList } from './lists';
import type { ResourceSpec, Row, SectionSpec } from './spec';
import './ops.css';

function visible(section: SectionSpec, hasRole: (...r: string[]) => boolean) {
  return section.resources.filter((r) => !r.hidden && (!r.roles || hasRole(...r.roles)));
}

function SectionInner({ section, children }: { section: SectionSpec; children?: React.ReactNode }) {
  const { hasRole } = useSession();
  const sp = useSearchParams();
  const router = useRouter();
  const path = usePathname();
  const list = visible(section, hasRole);
  const tab = sp.get('tab') ?? list[0]?.key;
  const res = list.find((r) => r.key === tab) ?? list[0];
  return (
    <div className="stack ops">
      <div>
        <p className="label">{section.screens ?? 'Back office'}</p>
        <h1>{section.title}</h1>
        <p className="muted" style={{ maxWidth: 720 }}>{section.intro}</p>
      </div>
      {children}
      {list.length > 1 ? (
        <nav className="ops-tabs" aria-label={`${section.title} lists`}>
          {list.map((r) => (
            <button key={r.key} className={`tab ${r.key === res?.key ? 'active' : ''}`} aria-current={r.key === res?.key ? 'page' : undefined}
              onClick={() => router.replace(`${path}?tab=${r.key}`, { scroll: false })}>
              {r.label}
            </button>
          ))}
        </nav>
      ) : null}
      {res ? (
        <section className="stack" key={res.key}>
          <div className="row" style={{ gap: 8 }}>
            <h2 style={{ margin: 0 }}>{res.label}</h2>
            {res.screen ? <span className="label">{res.screen}</span> : null}
          </div>
          <ResourceList section={section} res={res} />
        </section>
      ) : <Empty>You do not have access to any list in this section.</Empty>}
    </div>
  );
}

export function SectionPage({ section, children }: { section: SectionSpec; children?: React.ReactNode }) {
  return (
    <OpsToasts>
      <Suspense fallback={<Skeleton lines={6} />}>
        <SectionInner section={section}>{children}</SectionInner>
      </Suspense>
    </OpsToasts>
  );
}

const HIDE = new Set(['id', 'status_text', 'row_version', 'country_id']);
const HEAD = ['reference', 'name', 'legal_name', 'full_name', 'title', 'status', 'verdict'];

function linkFor(section: SectionSpec, res: ResourceSpec, k: string, v: unknown) {
  const to = res.links?.[k];
  if (!to || v == null || v === '') return null;
  const id = typeof v === 'object' ? (v as Row).id : v;
  if (!id) return null;
  const href = to.startsWith('/') ? `${to}/${id}` : `${section.href}/${to}/${id}`;
  return <> <Link href={href} className="btn btn-sm btn-ghost">Open</Link></>;
}

export function DetailView({ section, res, id }: { section: SectionSpec; res: ResourceSpec; id: string }) {
  const path = (res.detail ?? `${res.list}/{id}`).replace('{id}', encodeURIComponent(id));
  const { data, error, isLoading, mutate } = useGet<Row>(path);
  if (error) return <ProblemBox error={error} />;
  if (isLoading || !data) return <Skeleton lines={8} />;
  const row = data;
  const title = res.title ? res.title(row) : titleOf(row);
  const hide = new Set([...(res.hide ?? []), ...HIDE]);
  const entries = Object.entries(row).filter(([k, v]) => !hide.has(k) && !(HEAD.includes(k) && v === title));
  const isSimple = (v: unknown) => v === null || typeof v !== 'object' || isMoney(v) ||
    (!Array.isArray(v) && Object.keys(v as Row).length <= 4 && ('name' in (v as Row) || 'full_name' in (v as Row) || 'reference' in (v as Row))) ||
    (Array.isArray(v) && v.every((x) => typeof x !== 'object' || x === null));
  const simple = entries.filter(([, v]) => isSimple(v));
  const complex = entries.filter(([k, v]) => !isSimple(v) && !(Array.isArray(v) && !v.length) && !(res.subs ?? []).some((s) => s.from === k));
  const actions = (res.actions ?? []);
  return (
    <div className="stack ops">
      <div className="stack" style={{ gap: 6 }}>
        <Link href={`${section.href}?tab=${res.key}`} className="label ops-back">← {section.title} · {res.label}</Link>
        <div className="spread" style={{ alignItems: 'flex-start' }}>
          <div style={{ minWidth: 0 }}>
            <h1 style={{ marginBottom: 6, overflowWrap: 'anywhere' }}>{title}</h1>
            <div className="row" style={{ gap: 8 }}>
              {row.status ? <Status value={row.status} /> : null}
              {row.verdict ? <Verdict value={row.verdict} /> : null}
              {row.reference && title !== row.reference ? <span className="mono">{row.reference}</span> : null}
              {res.screen ? <span className="label">{res.screen}</span> : null}
            </div>
          </div>
        </div>
        {row.status_text ? <p style={{ margin: 0, maxWidth: 720 }}>{row.status_text}</p> : null}
      </div>
      {actions.length ? (
        <div className="row ops-actions" aria-label="Actions">
          {actions.map((a) => <ActionButton key={a.label} a={a} row={row} onDone={() => mutate()} subject={res.subject} size="md" />)}
        </div>
      ) : null}
      <div className="card">
        <dl className="kv">
          {simple.map(([k, v]) => (
            <React.Fragment key={k}><dt>{humanize(k)}</dt><dd><Value k={k} v={v} />{linkFor(section, res, k, v)}</dd></React.Fragment>
          ))}
        </dl>
      </div>
      {complex.map(([k, v]) => (
        <section key={k} className="stack" style={{ gap: 8 }}>
          <h2 style={{ margin: 0 }}>{humanize(k)}</h2>
          <Value k={k} v={v} />
        </section>
      ))}
      {(res.subs ?? []).filter((s) => !s.when || s.when(row)).map((s) => (
        <SubList key={s.label} section={section} sub={s} parent={row} onParentChange={() => mutate()} subject={res.subject} />
      ))}
    </div>
  );
}

export function DetailPage({ section }: { section: SectionSpec }) {
  const p = useParams<{ res: string; id: string }>();
  const res = section.resources.find((r) => r.key === p.res);
  return (
    <OpsToasts>
      {res ? <DetailView section={section} res={res} id={decodeURIComponent(p.id)} /> : <Empty>This page does not exist.</Empty>}
    </OpsToasts>
  );
}
