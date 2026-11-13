'use client';
/* Claim an expense with a receipt photo (US-PRO-004, SCR-BO-35 content). Against work you were assigned.
   One receipt pays once. Pay screens use only black, white and lime (RUL-26). */
import { useRouter } from 'next/navigation';
import { useMemo, useState } from 'react';
import { Button, Field, Input, ProblemBox, Select, Textarea, useGet, useSession } from '@tenmina/web-ui';
import { FilePick, PageHead, items, useAct, useApi, type Page } from '@/components/roles/kit';
import { uploadEvidence } from '@/components/roles/files';
import type { Task } from '@/components/roles/work';

type Job = { case_id: string | null; case_reference: string | null };
type Errand = { id: string; reference: string; name: string };
type Project = { id: string; title: string };

export default function NewClaim() {
  const router = useRouter();
  const { hasRole } = useSession();
  const api = useApi();
  const act = useAct();
  const jobs = useGet<Job[]>('/v1/me/pro/jobs');
  const tasks = useGet<Page<Task>>('/v1/tasks');
  const errands = useGet<Page<Errand>>(hasRole('CE') ? '/v1/mobile/errands' : null);
  const projects = useGet<Page<Project>>(hasRole('IN', 'QS') ? '/v1/projects' : null);
  const [kind, setKind] = useState('travel');
  const [description, setDescription] = useState('');
  const [amount, setAmount] = useState('');
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [target, setTarget] = useState('');
  const [file, setFile] = useState<File | null>(null);

  const options = useMemo(() => {
    const m = new Map<string, string>();
    for (const j of jobs.data ?? []) if (j.case_id) m.set(`case:${j.case_id}`, `Case ${j.case_reference}`);
    for (const t of items(tasks.data)) m.set(`case:${t.case}`, `Case ${t.case_reference}`);
    for (const e of items(errands.data)) m.set(`errand:${e.id}`, `Errand ${e.reference}, ${e.name}`);
    for (const p of items(projects.data)) m.set(`project:${p.id}`, `Project ${p.title}`);
    return [...m.entries()];
  }, [jobs.data, tasks.data, errands.data, projects.data]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const [type, id] = (target || options[0]?.[0] || '').split(':');
    await act.run('save', async () => {
      const subject = type === 'case' ? 'case' : type === 'errand' ? 'errand' : 'bld_project';
      const ev = await uploadEvidence(file!, { type: subject, id, role: 'expense_receipt' });
      await api('POST', '/v1/me/pro/expense-claims', {
        kind, description, amount, incurred_on: date, receipt_evidence_id: ev.id,
        ...(type === 'case' ? { case_id: id } : type === 'errand' ? { errand_id: id } : { project_id: id }),
      });
      router.push('/work/pay');
    });
  }

  return (
    <form className="stack" onSubmit={submit}>
      <PageHead back={{ href: '/work/pay', label: 'My pay' }} label="My pay" title="Claim an expense">For money you spent on Tenmina&apos;s work. Tenmina pays it back with your next payment, within the limit for your role.</PageHead>
      <Field label="What for">
        <Select value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="travel">Travel</option>
          <option value="official_search_fee">Official fee you paid</option>
          <option value="approved_cost">A cost Tenmina approved</option>
        </Select>
      </Field>
      <Field label="Which work">
        <Select value={target || options[0]?.[0] || ''} onChange={(e) => setTarget(e.target.value)}>
          {options.length ? options.map(([k, l]) => <option key={k} value={k}>{l}</option>) : <option value="">No assigned work found</option>}
        </Select>
      </Field>
      <Field label="Description"><Textarea value={description} onChange={(e) => setDescription(e.target.value)} required /></Field>
      <Field label="Amount"><Input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} required /></Field>
      <Field label="Date you paid"><Input type="date" value={date} max={new Date().toISOString().slice(0, 10)} onChange={(e) => setDate(e.target.value)} required /></Field>
      <FilePick label="Photo of the receipt" file={file} onFile={setFile} accept="image/*,application/pdf" hint="One receipt pays once." />
      <ProblemBox error={act.error} />
      <Button variant="primary" type="submit" block busy={act.busy === 'save'} disabled={!file || !amount || !description.trim() || !options.length}>Send claim</Button>
    </form>
  );
}
