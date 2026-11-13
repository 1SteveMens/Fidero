'use client';
import Link from 'next/link';
import { Empty, Skeleton, Status, useGet, useSession, When, type Page } from '@tenmina/web-ui';

type Approval = { id: string; subject_type: string; subject_id: string; summary: string; status: string; created_at: string; approvals: unknown[]; required: number };

export default function MyWork() {
  const { me } = useSession();
  const approvals = useGet<Page<Approval>>('/v1/approvals');
  return (
    <div className="stack">
      <p className="label">My work</p>
      <h1>Good to see you, {me?.full_name.split(' ')[0]}.</h1>
      <section className="stack">
        <div className="spread"><h2>Waiting for your approval</h2><Link href="/approvals" className="btn btn-ghost btn-sm">All approvals</Link></div>
        {approvals.isLoading ? <Skeleton /> : approvals.data?.items.length ? (
          approvals.data.items.slice(0, 8).map((a) => (
            <Link key={a.id} href={`/approvals/${a.id}`} className="card card-link spread">
              <div>
                <div className="label">{a.subject_type.replace(/_/g, ' ')}</div>
                <div style={{ fontWeight: 700 }}>{a.summary || a.subject_id}</div>
              </div>
              <div className="row"><Status value={`${a.approvals.length} of ${a.required}`} needsYou /><When value={a.created_at} /></div>
            </Link>
          ))
        ) : <Empty>No approvals are waiting for you.</Empty>}
      </section>
    </div>
  );
}
