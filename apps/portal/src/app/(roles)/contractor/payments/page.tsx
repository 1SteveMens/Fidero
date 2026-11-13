'use client';
/* Stage payments to you across projects. On black: money (03, 6.1a). */
import { useGet } from '@tenmina/web-ui';
import { EmptyText, Loaded, PageHead, items, type Page } from '@/components/roles/kit';
import { PaymentCard } from '@/components/roles/PaymentCard';
import type { ProjectPayment } from '@/components/roles/build';

export default function ContractorPayments() {
  const q = useGet<Page<ProjectPayment>>('/v1/project-payments');
  return (
    <div className="stack">
      <PageHead label="Building" title="Payments">Paid by the partner bank to your verified account. Tenmina never holds the money.</PageHead>
      <Loaded q={q}>{(d) => items(d).length ? items(d).map((x) => <PaymentCard key={x.id} x={x} onDone={() => q.mutate()} />) : <EmptyText>No payments yet.</EmptyText>}</Loaded>
    </div>
  );
}
