'use client';
import { useState } from 'react';
import { Status, When, useGet } from '@tenmina/web-ui';
import { EmptyText, Loaded, PageHead, RowLink, items, type Page } from '@/components/roles/kit';
import type { Task } from '@/components/roles/work';

const FILTERS = [
  { key: 'open', label: 'To do', match: (t: Task) => t.status === 'open' || t.status === 'in_progress' },
  { key: 'done', label: 'Done', match: (t: Task) => t.status === 'done' },
  { key: 'all', label: 'All', match: () => true },
];

export default function Tasks() {
  const q = useGet<Page<Task>>('/v1/tasks');
  const [f, setF] = useState('open');
  const filter = FILTERS.find((x) => x.key === f)!;
  return (
    <div className="stack">
      <PageHead label="My work" title="Tasks">Your assigned steps on cases. Tap one to add evidence and finish it.</PageHead>
      <div className="seg" role="group" aria-label="Show">
        {FILTERS.map((x) => <button key={x.key} type="button" aria-pressed={f === x.key} onClick={() => setF(x.key)}>{x.label}</button>)}
      </div>
      <Loaded q={q}>
        {(d) => {
          const rows = items(d).filter(filter.match);
          if (!rows.length) return <EmptyText>No tasks here.</EmptyText>;
          return rows.map((t) => (
            <RowLink key={t.id} href={`/work/tasks/${t.id}`} meta={t.case_reference} title={t.title}
              sub={t.status === 'done' ? <>Done <When value={t.completed_at} /></> : t.due_at ? <>Due <When value={t.due_at} /></> : undefined}
              right={<Status value={t.is_overdue && t.status !== 'done' ? 'overdue' : t.status} />} />
          ));
        }}
      </Loaded>
    </div>
  );
}
