'use client';
import Link from 'next/link';
import { Button, Empty, ProblemBox, Skeleton, useGet, useSession } from '@tenmina/web-ui';
import { AcctCard, AcctRow, PageHead, list, money, useAction, useCountry, type Any } from '@/components/kit';

/** Money held at the bank for family payments (FR-ESC-014). Never a wallet: the bank holds it, released on proof. */
export default function HeldFunds() {
  const { me } = useSession();
  const country = useCountry();
  const q = useGet<Any[]>('/v1/held-funds');
  const a = useAction();
  const rows = list(q.data);
  return (
    <div className="stack" style={{ gap: 16 }}>
      <PageHead back={{ href: '/family', label: 'Family' }} label="Held at the bank" title="Money held for family payments" sub="A licensed bank holds it in an account with your own reference. It pays only verified institutions and vendors, after you approve and two Tenmina staff approve." />
      {q.isLoading ? <Skeleton /> : rows.length ? (
        <AcctRow>
          {rows.flatMap((e: Any) => (e.funds ?? []).map((f: Any) => <AcctCard key={`${e.id}-${f.currency}`} href={`/property/escrows/${e.id}`} title="Held for your family" reference={f.virtual_account_ref || e.reference} amount={money(f.held_at_bank, f.currency)} holder={me?.full_name ?? ''} bank={e.payment_instructions?.bank_name} />))}
        </AcctRow>
      ) : <Empty>Nothing held yet.</Empty>}
      {rows.map((e: Any) => <Link key={e.id} href={`/property/escrows/${e.id}/pay-in`} className="btn btn-primary">Add money</Link>)}
      {!rows.length ? <Button variant="primary" busy={!!a.busy} onClick={() => a.run('c', () => a.post('/v1/held-funds', { country: country.code, currency: country.currency }), 'Set up', () => q.mutate())}>Set up money held at the bank</Button> : null}
      <ProblemBox error={a.error} />
      {a.toast}
    </div>
  );
}
