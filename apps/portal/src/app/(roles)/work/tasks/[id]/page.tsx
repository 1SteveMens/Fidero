'use client';
/* One task on a phone browser (FR-CASE-006): evidence, start, finish. Search tasks never take a
   result from the professional (RUL-30). Site visits have a risk screen (RUL-17) and a safety log. */
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { Blocked, Button, Card, Field, Input, KV, ProblemBox, Select, Skeleton, Status, Textarea, When, useGet, useSession } from '@tenmina/web-ui';
import { FilePick, PageHead, Section, useAct, useApi, words } from '@/components/roles/kit';
import { postForm } from '@/components/roles/files';
import type { Task } from '@/components/roles/work';

export default function TaskDetail() {
  const { id } = useParams<{ id: string }>();
  const q = useGet<Task>(`/v1/tasks/${id}`);
  const api = useApi();
  const act = useAct();
  const t = q.data;
  const [kind, setKind] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [note, setNote] = useState('');

  if (q.isLoading) return <Skeleton lines={6} />;
  if (q.error || !t) return <ProblemBox error={q.error ?? 'Task not found.'} />;
  const isSearch = !!t.search_kind;
  const closed = t.status === 'done' || t.status === 'cancelled';
  const kinds = t.required_evidence.length ? t.required_evidence : [];

  async function upload() {
    if (!file) return;
    await act.run('upload', async () => {
      await postForm(`/v1/tasks/${id}/evidence`, { kind: kind || kinds[0] || 'supporting', file });
      setFile(null);
      await q.mutate();
    }, 'File added. Its fingerprint is recorded.');
  }

  return (
    <div className="stack">
      <PageHead back={{ href: '/work/tasks', label: 'Tasks' }} label={t.case_reference} title={t.title} />
      <div className="row"><Status value={t.is_overdue && !closed ? 'overdue' : t.status} />{t.site_visit ? <span className="chip">Site visit</span> : null}</div>
      {isSearch ? (
        <Blocked title="Search results come from Tenmina's office, not from you.">
          Tenmina asks the registry from its own account and records the result itself (RUL-30). Do not upload a search result, even if someone gives you one.
        </Blocked>
      ) : null}
      {t.notice && !isSearch ? <div className="banner-info">{t.notice}</div> : null}
      <Card>
        <KV items={[
          ['Case', <span className="mono" key="c">{t.case_reference}</span>],
          ['Due', t.due_at ? <When value={t.due_at} withTime /> : 'No date'],
          ['Waiting for', t.waiting_for.length ? t.waiting_for.map(words).join(', ') : 'Nothing'],
          ['Done', t.completed_at ? <When value={t.completed_at} withTime /> : '—'],
        ]} />
      </Card>

      {kinds.length ? (
        <Section title="Evidence needed">
          <Card>
            {kinds.map((k) => {
              const missing = t.missing_evidence.includes(k);
              return (
                <div key={k} className="check-row">
                  <span className={`tick ${missing ? '' : 'done'}`} aria-hidden>{missing ? '' : '✓'}</span>
                  <span>{words(k)}</span>
                  <span className="muted" style={{ marginLeft: 'auto', fontSize: 13 }}>{missing ? 'Still needed' : 'Received'}</span>
                </div>
              );
            })}
          </Card>
        </Section>
      ) : null}

      {!closed && !isSearch ? (
        <Section title="Add evidence">
          <Card className="stack">
            {kinds.length ? (
              <Field label="What is this file?">
                <Select value={kind || kinds[0]} onChange={(e) => setKind(e.target.value)}>
                  {kinds.map((k) => <option key={k} value={k}>{words(k)}</option>)}
                  <option value="supporting">Something else</option>
                </Select>
              </Field>
            ) : null}
            <FilePick label="File or photo" file={file} onFile={setFile} accept="image/*,video/*,application/pdf" hint="Tenmina records the file's fingerprint so nobody can change it later." />
            <Button variant="dark" onClick={upload} busy={act.busy === 'upload'} disabled={!file}>Upload</Button>
          </Card>
        </Section>
      ) : null}

      {!closed ? (
        <Section title="Finish">
          <Card className="stack">
            {t.status === 'open' ? <Button variant="ghost" busy={act.busy === 'start'} onClick={() => act.run('start', async () => { await api('POST', `/v1/tasks/${id}/start`); await q.mutate(); }, 'Started.')}>I have started</Button> : null}
            <Field label="Note for the case manager (optional)"><Textarea value={note} onChange={(e) => setNote(e.target.value)} /></Field>
            {t.missing_evidence.length ? <p className="muted">Add the evidence above before you mark this done.</p> : null}
            <Button variant="primary" block busy={act.busy === 'done'} disabled={t.missing_evidence.length > 0}
              onClick={() => act.run('done', async () => { await api('POST', `/v1/tasks/${id}/complete`, { note }); await q.mutate(); }, 'Marked done.')}>Mark done</Button>
          </Card>
        </Section>
      ) : null}
      <ProblemBox error={act.error} />
      {t.site_visit && !closed ? <SiteSafety task={t} /> : null}
      {act.toast}
    </div>
  );
}

function SiteSafety({ task }: { task: Task }) {
  const { hasRole } = useSession();
  const api = useApi();
  const act = useAct();
  const [outcome, setOutcome] = useState('proceed');
  const [people, setPeople] = useState('1');
  const [hazards, setHazards] = useState('');
  const [severity, setSeverity] = useState('medium');
  const [narrative, setNarrative] = useState('');
  const [where, setWhere] = useState('');
  return (
    <>
      {hasRole('SV', 'LW', 'IN') ? (
        <Section title="Risk screen before the visit">
          <Card className="stack">
            <p className="muted" style={{ margin: 0 }}>A disputed plot needs at least two people on site (RUL-17).</p>
            <Field label="Outcome">
              <Select value={outcome} onChange={(e) => setOutcome(e.target.value)}>
                <option value="proceed">Go ahead</option>
                <option value="proceed_with_two">Go only with two people or more</option>
                <option value="do_not_visit">Do not visit</option>
              </Select>
            </Field>
            <Field label="People needed"><Input type="number" min={1} value={people} onChange={(e) => setPeople(e.target.value)} /></Field>
            <Field label="Hazards"><Textarea value={hazards} onChange={(e) => setHazards(e.target.value)} /></Field>
            <Button variant="dark" busy={act.busy === 'risk'} onClick={() => act.run('risk', () => api('POST', `/v1/cases/${task.case}/risk-screens`, { task_id: task.id, outcome, hazards, people_required: Number(people) || 1 }), 'Risk screen recorded.')}>Record risk screen</Button>
          </Card>
        </Section>
      ) : null}
      <Section title="Report a safety incident">
        <Card className="stack">
          <p className="muted" style={{ margin: 0 }}>Threats, attacks or anything that put you in danger. A reviewer reads it today.</p>
          <Field label="How serious">
            <Select value={severity} onChange={(e) => setSeverity(e.target.value)}>
              <option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option>
            </Select>
          </Field>
          <Field label="What happened"><Textarea value={narrative} onChange={(e) => setNarrative(e.target.value)} /></Field>
          <Field label="Where"><Input value={where} onChange={(e) => setWhere(e.target.value)} /></Field>
          <Button variant="dark" disabled={!narrative.trim()} busy={act.busy === 'inc'} onClick={() => act.run('inc', async () => { await api('POST', `/v1/cases/${task.case}/safety-incidents`, { severity, narrative, location_note: where }); setNarrative(''); }, 'Incident logged. Tenmina will contact you.')}>Log incident</Button>
        </Card>
      </Section>
      <ProblemBox error={act.error} />
      {act.toast}
    </>
  );
}
