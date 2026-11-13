'use client';
/* W-12 tasks: steps as tasks, owners, due dates, evidence. Mark done stays disabled with the reason until the
 * required evidence is attached (FR-CASE-004). Search results close only from an official search record (RUL-30). */
import Link from 'next/link';
import { Button, call, ProblemBox, useSession } from '@tenmina/web-ui';
import { ActionForm, day, iso, Panel, useAct, words } from '../kit';
import type { CaseDetail, Task } from '../types';

export function CaseTasks({ c, selected, onSelect, reload }: { c: CaseDetail; selected?: string | null; onSelect: (id: string) => void; reload: () => void }) {
  const { client, me } = useSession();
  const act = useAct();
  const tasks = c.tasks ?? [];
  const t = tasks.find((x) => x.id === selected) ?? tasks.find((x) => x.status === 'open' || x.status === 'in_progress') ?? tasks[0];
  const open = ['in_progress', 'on_hold', 'in_review'].includes(c.status);
  const isMine = (x: Task) => x.assignee?.id === me?.id || x.second_assignee?.id === me?.id;
  if (!tasks.length) return <Panel title="Tasks"><p className="muted" style={{ margin: 0 }}>{c.status === 'paid' ? 'Accept the case to create its tasks from the template.' : 'No tasks.'}</p></Panel>;
  const doneBlock = t ? (t.status === 'done' ? 'Done.' : t.status === 'cancelled' ? 'Cancelled.'
    : t.waiting_for.length ? `Waiting for ${t.waiting_for.map(words).join(', ').toLowerCase()}.`
      : t.search_kind && t.step_key.includes('result') ? 'Closes only from an official search record (RUL-30). Record the result under Searches.'
        : t.missing_evidence.length ? `Disabled: ${t.missing_evidence.length} evidence item${t.missing_evidence.length === 1 ? '' : 's'} missing (${t.missing_evidence.map(words).join(', ').toLowerCase()}).` : '') : '';
  return (
    <div className="cols">
      <Panel title={`Tasks (${tasks.filter((x) => x.status === 'done').length} of ${tasks.length} done)`}>
        <div className="rows">
          {tasks.map((x) => (
            <button key={x.id} type="button" onClick={() => onSelect(x.id)} className={`rowlink ${x.is_overdue && isMine(x) ? 'late' : ''}`}
              style={{ border: 0, textAlign: 'left', cursor: 'pointer', font: 'inherit', outline: x.id === t?.id ? '2px solid var(--ink)' : undefined }} aria-pressed={x.id === t?.id}>
              <div className="main">
                <div className="title">{x.position}. {x.title}</div>
                <div className="meta">{x.assignee ? `${x.assignee.name}${x.second_assignee ? ` + ${x.second_assignee.name}` : ''}` : `Needs ${x.owner_role}`} · due {day(x.due_at)}</div>
              </div>
              <span className={`chip ${x.is_overdue && isMine(x) ? 'chip-orange' : x.status === 'done' ? 'chip-lime' : ''}`}>{x.status === 'done' ? '✓ Done' : x.is_overdue ? '! Late' : words(x.status)}</span>
            </button>
          ))}
        </div>
      </Panel>
      {t ? (
        <Panel title={`Task: ${t.title}`}>
          <div className="row" style={{ gap: 6 }}>
            <span className="chip">{words(t.status)}</span><span className="chip">Owner role {t.owner_role}</span>
            {t.site_visit ? <span className="chip chip-ink">Site visit</span> : null}
            {t.review_step ? <span className="chip">Review step</span> : null}
          </div>
          {t.notice ? <div className="notice">{t.notice}</div> : null}
          <dl className="facts">
            <div><dt>Assigned</dt><dd>{t.assignee ? `${t.assignee.name}${t.second_assignee ? ` and ${t.second_assignee.name}` : ''}` : 'No one yet'}</dd></div>
            <div><dt>Due</dt><dd className="mono">{day(t.due_at)}</dd></div>
            {t.due_change_reason ? <div><dt>Due date changed</dt><dd>{t.due_change_reason}</dd></div> : null}
            <div><dt>Completed</dt><dd className="mono">{day(t.completed_at)}</dd></div>
          </dl>
          <div>
            <div className="label">Required evidence</div>
            {t.required_evidence.length ? (
              <ul style={{ margin: '6px 0 0', paddingLeft: 0, listStyle: 'none' }}>
                {t.required_evidence.map((k) => {
                  const missing = t.missing_evidence.includes(k) && t.status !== 'done';
                  return <li key={k} className="row" style={{ gap: 8, minHeight: 32 }}><span className={missing ? 'gate-mark gate-no' : 'gate-mark'} aria-hidden>{missing ? '' : '✓'}</span>{words(k)}<span className="sr-only">{missing ? 'missing' : 'attached'}</span></li>;
                })}
              </ul>
            ) : <p className="muted" style={{ margin: 0 }}>None.</p>}
          </div>
          {open && t.status !== 'done' && t.status !== 'cancelled' ? (
            <div className="stack">
              {doneBlock ? <p className="muted" style={{ margin: 0 }}>{doneBlock}</p> : null}
              <div className="row">
                <ActionForm label="Mark done" variant="primary" size="md" path={`/v1/tasks/${t.id}/complete`} disabled={!!doneBlock}
                  fields={[{ name: 'note', label: 'Note (optional)', type: 'textarea' }]} onDone={reload} submitLabel="Mark done" />
                {t.status === 'open' ? <Button variant="ghost" size="sm" busy={act.busy} onClick={() => act.run(() => call(client, 'POST', `/v1/tasks/${t.id}/start`).then(reload), 'Task started.')}>Start</Button> : null}
                <Link className="btn btn-dark btn-sm" href={`/cases/${c.id}/assign/${t.id}`}>{t.assignee ? 'Reassign' : 'Assign'}{t.site_visit ? ' and risk screen' : ''}</Link>
                {t.required_evidence.length ? (
                  <ActionForm label="Attach evidence" path={`/v1/tasks/${t.id}/evidence`} upload={{ subject_type: 'case', subject_id: c.id, role: 'task_evidence' }}
                    fields={[{ name: 'kind', label: 'What it is', type: 'select', required: true, options: t.required_evidence.map((k) => ({ value: k, label: words(k) })) }, { name: 'evidence_id', label: 'File', type: 'file', required: true }]}
                    onDone={reload} submitLabel="Attach" intro="The file is fingerprinted and stored. It cannot be changed afterwards." />
                ) : null}
                <ActionForm label="Change due date" path={`/v1/tasks/${t.id}`} method="PATCH" title="Change the due date"
                  fields={[{ name: 'due_at', label: 'New due date and time', type: 'datetime', required: true }, { name: 'reason', label: 'Reason', type: 'textarea', required: true }]}
                  body={(v) => ({ due_at: iso(v.due_at), reason: v.reason })} onDone={reload} />
              </div>
              <ProblemBox error={act.error} />
            </div>
          ) : null}
          {act.toast}
        </Panel>
      ) : null}
    </div>
  );
}
