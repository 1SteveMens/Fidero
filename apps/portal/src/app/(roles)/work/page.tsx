'use client';
/* My work today for professionals on a phone browser (FR-CASE-006, US-CASE-006): tasks, report
   sections to fill and sign, field visits, and a link to My pay. Orange only for this person's step. */
import Link from 'next/link';
import { NeedsYou, Skeleton, Status, When, useGet, useSession } from '@tenmina/web-ui';
import { EmptyText, PageHead, RowLink, Section, items, type Page } from '@/components/roles/kit';
import { inboxHref, type InboxItem, type ReportRow, type Task } from '@/components/roles/work';

export default function WorkToday() {
  const { me, hasRole } = useSession();
  const tasks = useGet<Page<Task>>('/v1/tasks');
  const writer = hasRole('LW', 'SV');
  const reports = useGet<Page<ReportRow>>(writer ? '/v1/reports' : null);
  const field = hasRole('IN', 'QS', 'CE', 'RN', 'SV');
  const inbox = useGet<InboxItem[]>(field ? '/v1/mobile/inbox' : null);

  const open = items(tasks.data).filter((t) => t.status === 'open' || t.status === 'in_progress');
  const drafts = items(reports.data).filter((r) => r.status !== 'released' && r.status !== 'superseded');
  const visits = items(inbox.data).filter((i) => i.subject_type !== 'task');
  const loading = tasks.isLoading || reports.isLoading || inbox.isLoading;

  return (
    <div className="stack">
      <PageHead label="My work" title={`Hello, ${me?.full_name.split(' ')[0] ?? ''}.`}>Work Tenmina has given you. Only your own.</PageHead>
      {loading ? <Skeleton lines={4} /> : null}
      {open.filter((t) => t.status === 'open').slice(0, 3).map((t) => (
        <NeedsYou key={t.id} title={t.title} detail={`${t.case_reference}${t.due_at ? ` · due ${new Date(t.due_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}` : ''}`} href={`/work/tasks/${t.id}`} />
      ))}
      {drafts.length ? (
        <Section title="Reports to fill and sign">
          {drafts.map((r) => <RowLink key={r.id} href={`/work/reports/${r.id}`} meta={r.case_reference} title={r.reference} right={<Status value={r.status} />} />)}
        </Section>
      ) : null}
      <Section title="Tasks" action={<Link href="/work/tasks" className="btn btn-ghost btn-sm">All tasks</Link>}>
        {!tasks.isLoading && !open.length ? <EmptyText>No open tasks. New work shows here.</EmptyText> : null}
        {open.map((t) => (
          <RowLink key={t.id} href={`/work/tasks/${t.id}`} meta={t.case_reference} title={t.title}
            sub={t.due_at ? <>Due <When value={t.due_at} /></> : undefined}
            right={<Status value={t.is_overdue ? 'overdue' : t.status} />} />
        ))}
      </Section>
      {field ? (
        <Section title="Visits and field work">
          {!inbox.isLoading && !visits.length ? <EmptyText>No visits assigned to you.</EmptyText> : null}
          {visits.map((i) => (
            <RowLink key={i.subject_type + i.subject_id} href={inboxHref(i)} meta={i.kind.replace(/_/g, ' ')} title={i.title}
              sub={i.address} right={i.due_at ? <When value={i.due_at} /> : undefined} />
          ))}
        </Section>
      ) : null}
      <Link href="/work/pay" className="card card-link">
        <div className="label">My pay</div>
        <div style={{ fontWeight: 700 }}>Jobs, payments, expenses and statements</div>
        <div className="muted" style={{ fontSize: 14 }}>Paid by Tenmina from its own account.</div>
      </Link>
    </div>
  );
}
