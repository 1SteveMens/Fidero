'use client';
/* Risk screen and assignment · SCR-BO-05 · W-13 (FR-CASE-003, FR-CASE-009, RUL-17, RUL-20). Short risk
 * questions, the computed result in words and icon, then named visitors. A disputed plot needs two people;
 * licensed roles need a valid licence. The API checks both again. */
import { useParams, useRouter } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';
import { Button, call, Field, Input, ProblemBox, Select, Skeleton, Textarea, useGet, useSession } from '@tenmina/web-ui';
import { day, Head, Panel, useAct, words } from '@/components/core/kit';
import type { Candidates, CaseDetail, RiskScreen } from '@/components/core/types';

type YN = 'yes' | 'no' | '';

function YesNo({ q, value, onChange }: { q: string; value: YN; onChange: (v: YN) => void }) {
  return (
    <fieldset style={{ border: 0, padding: 0, margin: 0 }} className="spread">
      <legend className="sr-only">{q}</legend>
      <span style={{ flex: '1 1 200px' }}>{q}</span>
      <span className="row" style={{ gap: 6 }}>
        {(['yes', 'no'] as const).map((v) => (
          <button key={v} type="button" className={`btn btn-sm ${value === v ? 'btn-dark' : 'btn-ghost'}`} style={{ minHeight: 44, minWidth: 64 }} aria-pressed={value === v} onClick={() => onChange(v)}>{v === 'yes' ? 'Yes' : 'No'}</button>
        ))}
      </span>
    </fieldset>
  );
}

export default function Assign() {
  const { id, taskId } = useParams<{ id: string; taskId: string }>();
  const router = useRouter();
  const { client } = useSession();
  const c = useGet<CaseDetail>(`/v1/cases/${id}`);
  const cand = useGet<Candidates>(`/v1/tasks/${taskId}/candidates`);
  const screens = useGet<RiskScreen[]>(`/v1/cases/${id}/risk-screens`);
  const t = c.data?.tasks?.find((x) => x.id === taskId);
  const latest = (screens.data ?? []).find((s) => s.task === taskId);
  const valid = latest && new Date(latest.valid_until).getTime() > Date.now() && latest.outcome !== 'do_not_visit';
  const [threats, setThreats] = useState<YN>('');
  const [occupied, setOccupied] = useState<YN>('');
  const [disputeArea, setDisputeArea] = useState<YN>('');
  const [stop, setStop] = useState(false);
  const [hazards, setHazards] = useState('');
  const [days, setDays] = useState('14');
  const [main, setMain] = useState('');
  const [second, setSecond] = useState('');
  const act = useAct();
  useEffect(() => { if (cand.data?.disputed) setDisputeArea('yes'); }, [cand.data?.disputed]);
  useEffect(() => { if (t) { setMain(t.assignee?.id ?? ''); setSecond(t.second_assignee?.id ?? ''); } }, [t]);

  const anyYes = threats === 'yes' || occupied === 'yes' || disputeArea === 'yes';
  const answered = threats && occupied && disputeArea;
  const outcome = stop ? 'do_not_visit' : anyYes ? 'proceed_with_two' : 'proceed';
  const need = cand.data ? (t?.site_visit ? Math.max(cand.data.people_required, valid && latest ? latest.people_required : 1) : 1) : 1;
  const people = [main, second].filter(Boolean).length;
  const mains = useMemo(() => (cand.data?.people ?? []).filter((p) => p.roles.includes(cand.data!.owner_role)), [cand.data]);
  const seconds = useMemo(() => (cand.data?.people ?? []).filter((p) => p.can_be_second && p.id !== main), [cand.data, main]);
  const mainPerson = mains.find((p) => p.id === main);
  const blockReason = !main ? 'Choose the person who does this step.'
    : mainPerson && !mainPerson.can_be_main ? (mainPerson.licence?.message ? `${mainPerson.name}: ${mainPerson.licence.message} (RUL-20)` : `${mainPerson.name} cannot take this step.`)
      : t?.site_visit && !valid ? 'Record a risk screen for this visit first (RUL-17).'
        : people < need ? (cand.data?.disputed ? 'Disputed plot: add a second person (RUL-17).' : `This visit needs ${need} people. Add a second person (RUL-17).`) : '';

  if (c.isLoading || cand.isLoading) return <Skeleton lines={8} />;
  if (!t || !cand.data) return <ProblemBox error={c.error ?? cand.error ?? 'Task not found.'} />;

  async function saveScreen() {
    const ok = await act.run(() => call(client, 'POST', `/v1/cases/${id}/risk-screens`, {
      task_id: taskId, outcome, hazards: [threats === 'yes' ? 'Reports of threats on this plot.' : '', occupied === 'yes' ? 'Occupied by someone claiming it.' : '', disputeArea === 'yes' ? 'Known dispute area.' : '', hazards].filter(Boolean).join(' '),
      people_required: outcome === 'proceed_with_two' ? 2 : 1, valid_days: Number(days) || 14,
    }), 'Risk screen saved.');
    if (ok !== undefined) { screens.mutate(); cand.mutate(); }
  }
  async function assign() {
    const ok = await act.run(() => call(client, 'PATCH', `/v1/tasks/${taskId}`, { assignee_id: main || null, second_assignee_id: second || null }), 'Assigned. They are told now.');
    if (ok !== undefined) { c.mutate(); router.push(`/cases/${id}?tab=tasks&task=${taskId}`); }
  }

  return (
    <div className="stack" style={{ gap: 18, maxWidth: 760 }}>
      <Head crumb={{ href: `/cases/${id}?tab=tasks&task=${taskId}`, label: c.data?.reference ?? 'Case' }} title={t.site_visit ? `${t.title}: risk screen` : `Assign: ${t.title}`}
        chips={<><span className="chip">Needs {t.owner_role}</span><span className="chip">Due {day(t.due_at)}</span>{cand.data.disputed ? <span className="chip chip-ink">! Disputed plot</span> : null}</>} />
      {t.site_visit ? (
        <Panel title="Risk screen">
          {latest ? (
            <div className="notice">
              Latest screen: <strong>{latest.outcome === 'do_not_visit' ? '✕ Do not visit' : latest.outcome === 'proceed_with_two' ? '! Two people needed' : '✓ Clear'}</strong>, by {latest.screened_by?.name}, valid until {day(latest.valid_until)}{valid ? '' : ' (no longer valid)'}.
            </div>
          ) : null}
          <YesNo q="1. Any report of threats on this plot?" value={threats} onChange={setThreats} />
          <YesNo q="2. Occupied by someone claiming it?" value={occupied} onChange={setOccupied} />
          <YesNo q="3. Known dispute area (overlay)?" value={disputeArea} onChange={setDisputeArea} />
          {answered ? (
            <div className={stop || anyYes ? 'strip-ink' : 'notice'} role="status">
              {stop ? '✕ Do not visit. No one is sent.' : anyYes ? '! Disputed. Two people needed.' : '✓ Clear. One person may visit.'}
            </div>
          ) : null}
          <label className="row" style={{ gap: 10, minHeight: 44 }}><input type="checkbox" checked={stop} onChange={(e) => setStop(e.target.checked)} style={{ width: 22, height: 22 }} /><span>No one should visit for now</span></label>
          <Field label="Anything else the visitors must know"><Textarea value={hazards} onChange={(e) => setHazards(e.target.value)} /></Field>
          <Field label="Valid for (days)" hint="Working assumption [TO VERIFY]."><Input type="number" min={1} max={90} value={days} onChange={(e) => setDays(e.target.value)} /></Field>
          <div><Button variant="dark" onClick={saveScreen} busy={act.busy} disabled={!answered}>Save risk screen</Button></div>
        </Panel>
      ) : null}
      <Panel title={t.site_visit ? 'Visitors' : 'Assign'}>
        <Field label={`Main person (${t.owner_role})`}>
          <Select value={main} onChange={(e) => setMain(e.target.value)}>
            <option value="">Choose…</option>
            {mains.map((p) => <option key={p.id} value={p.id} disabled={!p.can_be_main}>{p.name}{p.licence ? (p.licence.valid ? ` · licence ${p.licence.number}` : ` · ${p.licence.message}`) : ''}</option>)}
          </Select>
        </Field>
        {t.site_visit ? (
          <Field label="Second person" hint={cand.data.disputed ? 'Required on a disputed plot (RUL-17).' : 'Needed when the risk screen says two.'}>
            <Select value={second} onChange={(e) => setSecond(e.target.value)}>
              <option value="">No second person</option>
              {seconds.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.roles.map(words).join(', ')}</option>)}
            </Select>
          </Field>
        ) : null}
        {!mains.length ? <p className="muted" style={{ margin: 0 }}>No one in this country holds the role {t.owner_role}.</p> : null}
        {blockReason ? <p style={{ margin: 0, fontWeight: 700 }}>{blockReason}</p> : null}
        <ProblemBox error={act.error} />
        <div><Button variant="primary" onClick={assign} busy={act.busy} disabled={!!blockReason}>{t.site_visit ? 'Assign visit' : 'Assign'}</Button></div>
        <p className="muted" style={{ margin: 0, fontSize: 13 }}>Assigned people get access to the plot for this case only. The incident link sits on every field task.</p>
      </Panel>
      {act.toast}
    </div>
  );
}
