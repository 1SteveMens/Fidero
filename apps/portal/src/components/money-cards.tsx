'use client';
import { useGet } from '@tenmina/web-ui';
import { AcctCard, AcctRow, list, money, type Any } from './kit';

const HOLDING = ['funded', 'ready_to_release', 'client_approved', 'release_approved', 'partly_released', 'frozen'];

function EscrowCard({ e, holder }: { e: Any; holder: string }) {
  const d = useGet<Any>(`/v1/escrows/${e.id}`);
  const f = d.data?.funds?.[0];
  if (!d.data || !f || Number(f.held_at_bank) <= 0) return null;
  return (
    <AcctCard href={`/property/escrows/${e.id}`} title={e.kind === 'held_funds' ? 'Held for your family' : e.title} reference={d.data.payment_instructions?.virtual_account_ref || e.reference}
      amount={money(f.held_at_bank, f.currency)} holder={holder} bank={d.data.payment_instructions?.bank_name}
      note={e.status === 'frozen' ? 'No money can move until the check is done.' : Number(f.instructed_awaiting_bank) > 0 ? `${f.currency} ${f.instructed_awaiting_bank} instructed, waiting for the bank` : undefined} />
  );
}

/** Every account the bank holds for this client, side by side (W-25, FR-ESC-014). */
export function HeldAtBank({ holder, kinds }: { holder: string; kinds?: string[] }) {
  const esc = useGet<Any>('/v1/escrows');
  const held = useGet<Any[]>('/v1/held-funds');
  const rows = [...list(held.data), ...list(esc.data).filter((e: Any) => e.kind !== 'held_funds' && HOLDING.includes(e.status))]
    .filter((e: Any) => !kinds || kinds.includes(e.kind));
  if (!rows.length) return null;
  return (
    <section className="stack" style={{ gap: 8 }}>
      <h2 style={{ margin: 0 }}>Held at the bank for you</h2>
      <p className="muted" style={{ margin: 0 }}>A licensed bank holds this money, not Tenmina. It is paid out only on proof, after you approve.</p>
      <AcctRow>{rows.map((e: Any) => <EscrowCard key={e.id} e={e} holder={holder} />)}</AcctRow>
    </section>
  );
}
