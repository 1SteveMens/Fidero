'use client';
/* Confirm a visit or delivery from the one-time link (SCR-PTL-45, W-31). No account needed (DA-07).
   Opening the link never confirms; only a tap does. Large text and 56 px buttons for a basic phone. */
import { useParams } from 'next/navigation';
import { useEffect, useState } from 'react';
import { ProblemBox, Skeleton } from '@tenmina/web-ui';
import { ApiError } from '@tenmina/api-client';
import { send } from '@/components/roles/files';

type Info = { status: string; purpose: string; summary: string; expires_at: string };

export default function ConfirmLink() {
  const { token } = useParams<{ token: string }>();
  const [info, setInfo] = useState<Info | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [answer, setAnswer] = useState<string | null>(null);
  useEffect(() => {
    send<Info>('GET', `/v1/family-confirmations/${encodeURIComponent(token)}`).then(setInfo).catch(setError);
  }, [token]);

  async function decide(decision: 'confirm' | 'dispute') {
    setBusy(decision); setError(null);
    try {
      const r = await send<{ status: string }>('POST', `/v1/family-confirmations/${encodeURIComponent(token)}`, JSON.stringify({ decision }), { 'Content-Type': 'application/json' });
      setAnswer(r.status);
    } catch (e) { setError(e); } finally { setBusy(null); }
  }

  const what = info?.purpose === 'care_visit' ? 'the visit' : 'the delivery';
  const notFound = error instanceof ApiError && error.problem.status === 404;
  const status = answer ?? info?.status;
  return (
    <div className="stack confirm-page" style={{ maxWidth: 520, margin: '0 auto' }}>
      {!info && !error ? <Skeleton lines={3} /> : null}
      {notFound ? <><h1>This link does not work</h1><p>Check the message we sent you, or call Tenmina.</p></> : null}
      {info ? (
        <>
          <h1 style={{ fontSize: 28 }}>Did {what} happen?</h1>
          {info.summary ? <p className="big-q" style={{ fontWeight: 600 }}>{info.summary.charAt(0).toUpperCase() + info.summary.slice(1)}</p> : null}
          {status === 'pending' ? (
            <>
              <button type="button" className="btn btn-action btn-block" disabled={!!busy} onClick={() => decide('confirm')}>{busy === 'confirm' ? 'Working…' : `Yes, ${what} happened`}</button>
              <button type="button" className="btn btn-ghost btn-block" disabled={!!busy} onClick={() => decide('dispute')}>{busy === 'dispute' ? 'Working…' : 'No, it did not happen'}</button>
              <p className="muted">This link works until {new Date(info.expires_at).toLocaleString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' })}. The family member abroad sees your answer.</p>
            </>
          ) : status === 'confirmed' ? (
            <div className="result-yes" role="status"><strong>✓ Thank you.</strong> {answer ? 'Confirmed.' : 'This was already confirmed.'}</div>
          ) : status === 'disputed' ? (
            <div className="result-no" role="status">We are sorry. Tenmina will call you today. Nobody is paid for this.</div>
          ) : status === 'expired' ? (
            <div className="result-no" role="status">This link has expired. Tenmina will call you.</div>
          ) : status === 'locked' ? (
            <div className="result-no" role="status">This confirmation is locked. Tenmina will call you to confirm.</div>
          ) : (
            <div className="result-no" role="status">There is nothing to answer here any more.</div>
          )}
        </>
      ) : null}
      {!notFound ? <ProblemBox error={error} /> : null}
    </div>
  );
}
