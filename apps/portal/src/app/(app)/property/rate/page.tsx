'use client';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useState } from 'react';
import { Button, Field, ProblemBox, Skeleton, Textarea, useGet } from '@tenmina/web-ui';
import { PageHead, list, useAction, words, type Any } from '@/components/kit';

/** SCR-PTL-33: rate a seller, contractor or professional after a completed step (FR-RAT-002). */
function Rate() {
  const id = useSearchParams().get('opportunity');
  const router = useRouter();
  const q = useGet<Any>('/v1/rating-opportunities');
  const o = list(q.data).find((x: Any) => x.id === id);
  const [score, setScore] = useState(0);
  const [comment, setComment] = useState('');
  const a = useAction();
  if (q.isLoading) return <Skeleton lines={4} />;
  if (!o) return <p className="muted">This rating is not open any more.</p>;
  return (
    <form className="stack" style={{ gap: 16 }} onSubmit={(e) => { e.preventDefault(); a.run('go', () => a.post('/v1/ratings', { opportunity_id: id, score, comment }), 'Thank you', () => router.push('/')); }}>
      <PageHead back={{ href: '/', label: 'Home' }} label={o.context_label} title={`How did ${o.subject_name} do?`} sub={words(o.subject_role)} />
      {o.rated ? <p>You already rated this.</p> : <>
        <div className="row" role="radiogroup" aria-label="Score from 1 to 5">
          {[1, 2, 3, 4, 5].map((n) => <button type="button" key={n} role="radio" aria-checked={score === n} className={`btn ${score >= n ? 'btn-dark' : 'btn-ghost'}`} style={{ width: 52 }} onClick={() => setScore(n)}>{n}</button>)}
        </div>
        <Field label="Comment (optional)" hint="Tenmina checks comments before anyone else sees them."><Textarea value={comment} onChange={(e) => setComment(e.target.value)} /></Field>
        <ProblemBox error={a.error} />
        <Button variant="primary" type="submit" disabled={!score} busy={!!a.busy}>Send rating</Button>
      </>}
    </form>
  );
}

export default function Page() { return <Suspense><Rate /></Suspense>; }
