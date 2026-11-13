'use client';
/* The institution's record at Tenmina (CMP-26): verification status with its date, the checks done, and
   the only account Tenmina pays. */
import { Card, Chip, KV, When, useGet } from '@tenmina/web-ui';
import { EmptyText, Loaded, PageHead, Section, items, words, type Page } from '@/components/roles/kit';
import type { Institution } from '@/components/roles/fees';

export default function InstitutionProfile() {
  const q = useGet<Page<Institution>>('/v1/institutions');
  return (
    <div className="stack">
      <PageHead label="Institution" title="Our record">What Tenmina checked about you. To change your bank account, call Tenmina: we never change it because of a message or email.</PageHead>
      <Loaded q={q}>{(d) => items(d).length ? items(d).map((i) => (
        <div key={i.id} className="stack">
          <Card className="stack">
            <div className="spread"><h2 style={{ margin: 0 }}>{i.legal_name}</h2>{i.status === 'verified' ? <Chip tone="lime">✓ Verified{i.verified_at ? ` ${new Date(i.verified_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}` : ''}</Chip> : <Chip>{words(i.status)}</Chip>}</div>
            <span>{i.status_text}</span>
            <KV items={[['Type', words(i.type)], ['Registration', i.registration_number || '—'], ['Address', i.address || '—'], ['Bills come by', words(i.invoice_channel)], ['Direct payment', i.eligible_for_direct_payment ? 'Yes' : `Not eligible. ${i.not_eligible_reason}`]]} />
          </Card>
          {i.payee ? (
            <div className="card-ink stack">
              <div className="label">The only account Tenmina pays</div>
              <strong>{i.payee.account_name}</strong>
              <span>Account ending <span className="mono">{i.payee.account_last4}</span> at {i.payee.bank_name}</span>
              <span>{words(i.payee.verification_status)}</span>
            </div>
          ) : null}
          <Section title="Checks">
            <Card>{i.checklist.map((c) => <div key={c.key} className="check-row"><span className={`tick ${c.done ? 'done' : ''}`} aria-hidden>{c.done ? '✓' : ''}</span><span>{c.label}{c.detail && c.detail !== 'verified' ? <span className="muted"> · {c.detail}</span> : null}</span></div>)}</Card>
          </Section>
          {i.verified_at ? <p className="muted">Verified on <When value={i.verified_at} />.</p> : null}
        </div>
      )) : <EmptyText>You are not a named contact for an institution yet.</EmptyText>}</Loaded>
    </div>
  );
}
