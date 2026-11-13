'use client';
/* One approval. Dedicated kinds (releases, reports, payees, refunds…) are given on their own screen, where their
 * extra checks run; this page links there. Other kinds are given here with the second factor. */
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { call, ProblemBox, Skeleton, useGet, useSession } from '@tenmina/web-ui';
import { dayTime, DoneSlot, Facts, Head, MySlot, OpenSlot, Panel, words } from '@/components/core/kit';
import { dedicatedHref, SUBJECT_LABEL } from '@/components/core/approvalLinks';
import type { Approval } from '@/components/core/types';

export default function ApprovalDetail() {
  const { id } = useParams<{ id: string }>();
  const { client, me } = useSession();
  const a = useGet<Approval>(`/v1/approvals/${id}`);
  const probe = a.data && (a.data.subject_type === 'escrow_cancel' || a.data.subject_type === 'refund');
  const ins = useGet<{ id: string }>(probe ? `/v1/release-instructions/${a.data!.subject_id}` : null, undefined, { shouldRetryOnError: false });
  if (a.isLoading) return <Skeleton lines={6} />;
  if (!a.data) return <ProblemBox error={a.error ?? 'Approval not found.'} />;
  const x = a.data;
  const href = ins.data ? `/escrow/releases/${ins.data.id}` : dedicatedHref(x.subject_type, x.subject_id);
  const given = x.approvals.filter((p) => p.decision === 'approve');
  const iGave = x.approvals.some((p) => p.approver === me?.id);
  const iPrepared = x.prepared_by === me?.id;
  const slots = Array.from({ length: x.required }, (_, i) => i);
  return (
    <div className="stack" style={{ gap: 18 }}>
      <Head crumb={{ href: '/approvals', label: 'Approvals' }} title={x.summary || SUBJECT_LABEL[x.subject_type] || x.subject_type}
        chips={<><span className="chip">{SUBJECT_LABEL[x.subject_type] ?? x.subject_type}</span><span className="chip">{words(x.status)}</span><span className="chip">{given.length} of {x.required}</span></>} />
      <Panel title="What is being approved">
        <Facts items={[['Kind', SUBJECT_LABEL[x.subject_type] ?? x.subject_type], ['Asked', dayTime(x.created_at)], ['Closed', x.closed_at ? dayTime(x.closed_at) : '—'], ['Approvers needed', String(x.required)]]} />
      </Panel>
      {x.dedicated || href ? (
        <Panel title="Give this approval on its own screen">
          <p style={{ margin: 0 }}>This approval has extra checks (gates, rights, the client&apos;s approval first). It is given where those checks run.</p>
          {href ? <Link className="btn btn-dark" href={href}>Open the {SUBJECT_LABEL[x.subject_type]?.toLowerCase() ?? 'approval'} screen</Link> : null}
          {x.approvals.length ? (
            <div className="grid2">{x.approvals.map((p, i) => <DoneSlot key={i} title={`Approval ${i + 1} of ${x.required}`} name={p.approver_name} at={p.at} decision={p.decision} />)}</div>
          ) : null}
        </Panel>
      ) : (
        <Panel title="Approvals">
          <div className="grid2">
            {slots.map((i) => {
              const p = x.approvals[i];
              if (p) return <DoneSlot key={i} title={`Approval ${i + 1} of ${x.required}`} name={p.approver_name} at={p.at} decision={p.decision} />;
              if (x.status === 'open' && i === x.approvals.length && !iGave && !iPrepared) {
                return (
                  <MySlot key={i} title={`Approval ${i + 1} of ${x.required}`} confirmText="I checked what I am approving myself" holdLabel="Press and hold to approve"
                    onApprove={async () => { await call(client, 'POST', `/v1/approvals/${id}/decisions`, { decision: 'approve' }); await a.mutate(); }}
                    onReturn={async (note) => { await call(client, 'POST', `/v1/approvals/${id}/decisions`, { decision: 'reject', note }); await a.mutate(); }} returnLabel="Reject with a reason" />
                );
              }
              return <OpenSlot key={i} title={`Approval ${i + 1} of ${x.required}`} text={iPrepared ? 'You prepared this. A different person must approve it.' : iGave ? 'You gave an approval. A different person must give this one.' : x.status === 'open' ? 'Waiting' : '—'} />;
            })}
          </div>
        </Panel>
      )}
    </div>
  );
}
