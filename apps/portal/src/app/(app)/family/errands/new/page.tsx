'use client';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useState } from 'react';
import { Button, Empty, Field, Money, ProblemBox, Select, Skeleton, Textarea, useGet } from '@tenmina/web-ui';
import { PageHead, RadioCard, list, useAction, useCountry, type Any } from '@/components/kit';

/** SCR-PTL-49: the errand catalogue for the country: checklist, official fees, Tenmina's charge and target time. */
function NewErrand() {
  const sp = useSearchParams();
  const router = useRouter();
  const country = useCountry();
  const cat = useGet<Any>('/v1/errand-catalogue', { country: country.code });
  const fams = useGet<Any>('/v1/family-members');
  const [code, setCode] = useState('');
  const [fm, setFm] = useState(sp.get('member') || '');
  const [notes, setNotes] = useState('');
  const a = useAction();
  const items = list(cat.data).filter((c: Any) => c.orderable !== false);
  const pick = items.find((c: Any) => c.code === code);
  return (
    <form className="stack" style={{ gap: 16 }} onSubmit={(e) => { e.preventDefault(); a.run('go', () => a.post<Any>('/v1/errands', { code, country: country.code, for_family_member_id: fm || null, notes }), undefined, (r) => router.push(`/family/errands/${r.id}`)); }}>
      <PageHead back={{ href: '/family', label: 'Family' }} label="Paperwork and errands" title="What do you need done?" sub="A vetted agent does it. Official fees are paid from money held at the partner bank, step by step, against receipts." />
      {cat.isLoading ? <Skeleton lines={4} /> : items.length ? items.map((c: Any) => (
        <RadioCard key={c.code} name="errand" checked={code === c.code} onChange={() => setCode(c.code)}>
          <strong>{c.name}</strong>
          <div className="muted" style={{ fontSize: 14 }}>{c.agency}{c.target_days ? ` · about ${c.target_days} days` : ''}</div>
          <div style={{ fontSize: 14 }}>Official fees <Money value={c.official_fees} /> · Tenmina&apos;s charge <Money value={c.tenmina_charge} /></div>
          {code === c.code ? (
            <div className="stack" style={{ gap: 4, marginTop: 8 }}>
              <div style={{ fontSize: 14 }}>{c.description}</div>
              <div className="label">You will need</div>
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 14 }}>{(c.checklist ?? []).map((d: Any) => <li key={d.key}>{d.label}{d.required ? '' : ' (if you have it)'}</li>)}</ul>
              <div className="label">Steps</div>
              <ol style={{ margin: 0, paddingLeft: 18, fontSize: 14 }}>{(c.steps ?? []).map((s: Any) => <li key={s.seq}>{s.description}{Number(s.official_fee) > 0 ? ` (${c.official_fees.currency} ${s.official_fee})` : ''}</li>)}</ol>
            </div>
          ) : null}
        </RadioCard>
      )) : <Empty>No errands are offered here yet.</Empty>}
      <Field label="For"><Select value={fm} onChange={(e) => setFm(e.target.value)}><option value="">Me</option>{list(fams.data).map((m: Any) => <option key={m.id} value={m.id}>{m.full_name}</option>)}</Select></Field>
      <Field label="Anything the agent should know"><Textarea value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
      <ProblemBox error={a.error} />
      <Button variant="primary" type="submit" disabled={!pick} busy={!!a.busy}>Start {pick ? pick.name : 'the errand'}</Button>
    </form>
  );
}

export default function Page() { return <Suspense><NewErrand /></Suspense>; }
