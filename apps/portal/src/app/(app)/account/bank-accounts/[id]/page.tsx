'use client';
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { Button, Chip, KV, ProblemBox, Skeleton, When, useGet, useSession } from '@tenmina/web-ui';
import { EvidenceLink, Ink, PageHead, Proof, Upload, useAction, words, type Any } from '@/components/kit';

const TEXT: Record<string, string> = {
  unverified: 'Send a letter from your bank so we can verify it.',
  pending: 'Tenmina is checking this account.',
  rejected: 'We could not verify this account. Send a new bank letter.',
  suspended: 'This account is suspended. Contact your case manager.',
  verified: 'Verified.',
};

export default function BankAccount() {
  const { id } = useParams<{ id: string }>();
  const { me } = useSession();
  const q = useGet<Any>(`/v1/bank-accounts/${id}`);
  const a = useAction();
  const [letter, setLetter] = useState<Any>(null);
  if (q.isLoading) return <Ink><Skeleton /></Ink>;
  if (!q.data) return <Ink><ProblemBox error={q.error} /></Ink>;
  const b = q.data;
  return (
    <Ink>
      <PageHead back={{ href: '/account/bank-accounts', label: 'Bank accounts' }} label={words(b.purpose)} title={`${b.bank_name} · ending ${b.account_number_last4}`} sub={TEXT[b.verification_status]} />
      {b.verification_status === 'verified' ? <Proof>Verified <When value={b.verified_at} /></Proof> : <Chip tone={['unverified', 'rejected'].includes(b.verification_status) ? 'orange' : undefined}>{words(b.verification_status)}</Chip>}
      <KV items={[['Name on the account', b.account_name], ['Branch', b.branch || '—'], ['Bank name check', b.name_match === 'matched' ? 'Matched' : b.name_match === 'mismatch' ? <span key="m" className="unmatched">Name not matched</span> : words(b.name_match)], ['Bank letter', b.evidence ? <EvidenceLink key="e" id={typeof b.evidence === 'string' ? b.evidence : b.evidence.id} label="Open" /> : 'None yet']]} />
      {['unverified', 'rejected'].includes(b.verification_status) && me ? (
        <div className="card stack">
          <Upload subject={{ type: 'pmg_owner_document', id: me.id, role: 'bank_letter' }} label={letter ? 'Letter attached' : 'Attach the bank letter'} onDone={setLetter} />
          <Button variant="action" disabled={!letter} busy={!!a.busy} onClick={() => a.run('s', () => a.post(`/v1/bank-accounts/${id}`, { evidence: letter.id }, 'PATCH'), 'Sent to Tenmina', () => q.mutate())}>Send for checking</Button>
        </div>
      ) : null}
      <ProblemBox error={a.error} />
      {a.toast}
    </Ink>
  );
}
