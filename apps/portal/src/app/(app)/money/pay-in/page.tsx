'use client';
import Link from 'next/link';
import { ProblemBox, Skeleton } from '@tenmina/web-ui';
import { Copy, Ink, PageHead, type Any } from '@/components/kit';
import { useAccount } from '@/components/account-card';

function Row({ k, v, copy, note }: { k: string; v?: string | null; copy?: boolean; note?: string }) {
  if (!v) return null;
  return (
    <div className="check-row" style={{ gridTemplateColumns: '1fr auto' }}>
      <div><div className="label">{k}</div><div className="mono" style={{ fontSize: 17, overflowWrap: 'anywhere' }}>{v}</div>{note ? <div className="muted" style={{ fontSize: 13 }}>{note}</div> : null}</div>
      {copy ? <Copy value={v} /> : <span />}
    </div>
  );
}

/** W-10 · SCR-PTL-18: how to pay in. One set of details for the whole account (FR-ESC-025), the bank's only.
 * Never Tenmina's account (RUL-01). A commitment has no pay-in details of its own. */
export default function PayIn() {
  const acc = useAccount();
  if (acc.isLoading) return <Ink><Skeleton lines={6} /></Ink>;
  if (acc.missing) {
    return (
      <Ink>
        <PageHead back={{ href: '/money', label: 'Your account' }} label="Pay into your account" title="Open your account first" />
        <p>Your Tenmina account is opened at the partner bank. Then you see its pay-in details here.</p>
        <Link className="btn btn-primary" href="/money">Open my account</Link>
      </Ink>
    );
  }
  if (!acc.data) return <Ink><ProblemBox error={acc.error} /></Ink>;
  const pi = acc.data.pay_in ?? {};
  const free = acc.data.free_balance_lines?.[0];
  return (
    <Ink>
      <PageHead back={{ href: '/money', label: 'Your account' }} label="Pay into your Tenmina account" title="Pay the bank" />
      <div className="card" style={{ display: 'flex', gap: 10 }}>
        <span aria-hidden style={{ fontSize: 22 }}>🛡</span>
        <div>These are the bank&apos;s details, not Tenmina&apos;s. Tenmina never asks you to pay money to Tenmina.</div>
      </div>
      {!pi.available ? <p>{pi.message ?? 'The bank is opening your account. We will tell you when you can pay in.'}</p> : (
        <>
          <section className="card" style={{ paddingTop: 4, paddingBottom: 4 }}>
            <Row k="Bank" v={pi.bank_name?.replace(/\s*\[TO VERIFY\]/, '')} />
            <Row k="Your reference" v={pi.reference} copy note="Always use it. It is the same for every currency. Without it the bank cannot credit your account." />
          </section>
          {(pi.lines ?? []).map((l: Any) => (
            <section key={`${l.currency}-${l.account_number}`} className="card" style={{ paddingTop: 4, paddingBottom: 4 }}>
              <div className="label" style={{ paddingTop: 8 }}>To pay in {l.currency}</div>
              <Row k="Account name" v={l.account_name} copy />
              <Row k="Account number" v={l.account_number} copy />
              {l.virtual_account_ref !== pi.reference ? <Row k="Reference for this currency" v={l.virtual_account_ref} copy /> : null}
            </section>
          ))}
        </>
      )}
      <p style={{ margin: 0 }}>Everything is paid from this one account: school fees, care, errands, cover, building stages, events, repairs and land purchases. After the bank confirms your payment, you set money aside for a deal from your free balance.</p>
      <p style={{ margin: 0 }}>If anyone sends you different details, do not pay. Call us first.</p>
      <div className="row">
        {free ? <Link href={`/property/escrows/${free.id}/pay-in`} className="btn btn-ghost">Sending from abroad? Compare ways to send</Link> : null}
        <button className="btn btn-ghost" onClick={() => window.print()}>Save as PDF</button>
      </div>
    </Ink>
  );
}
