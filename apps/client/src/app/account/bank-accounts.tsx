import { useState } from 'react';
import { View } from 'react-native';
import { brand, space } from '@tenmina/tokens';
import { Button, Chip, Label, Panel, Rise, Screen, T, Tick, haptic, type ChipTone } from '@tenmina/ui';
import { Empty, Field, LoadState, ProblemBox, day, itemsOf, useAction, useGet, useSession } from '@tenmina/mobile';
import { AddFile, type StoredEvidence } from '../../components/files';
import { useCountry } from '../../components/country';

interface BankAccount {
  id: string;
  bank_name: string;
  branch: string;
  account_number_last4: string;
  account_name: string;
  name_match: string;
  verification_status: string;
  approval_status: string | null;
  purpose: string;
  verified_at: string | null;
  evidence: string | null;
  created_at: string;
}

/** Each verification state in plain words, and its colour: lime for proof, orange only when it needs you. */
const STATE: Record<string, { label: string; tone: ChipTone; detail: string }> = {
  unverified: { label: 'Needs your bank letter', tone: 'orange', detail: 'Add a letter from your bank that shows the name and number. Tenmina checks it.' },
  pending: { label: 'Being checked', tone: 'paper', detail: 'Tenmina staff are checking the letter. Two staff must agree.' },
  verified: { label: 'Verified', tone: 'lime', detail: 'Money for you can be paid here.' },
  rejected: { label: 'Not accepted', tone: 'orange', detail: 'The letter did not match. Add a new letter or contact Tenmina.' },
  suspended: { label: 'Stopped', tone: 'paper', detail: 'Payments to this account are stopped. Contact Tenmina.' },
};

/**
 * Your own bank accounts at home (SCR-PTL-21, FR-ACC-012, RUL-24): add one and
 * see its verification state. Each account is in your own name and is checked
 * with a letter from your bank before any money goes there. Tenmina never holds
 * the money.
 */
export default function BankAccounts() {
  const { me } = useSession();
  const country = useCountry();
  const list = useGet<{ items: BankAccount[] }>('/v1/bank-accounts');
  const act = useAction();
  const [adding, setAdding] = useState(false);
  const [f, setF] = useState({ bank_name: '', branch: '', account_number: '', account_name: me?.full_name ?? '' });
  const [letter, setLetter] = useState<StoredEvidence>();
  const [added, setAdded] = useState(false);
  const items = itemsOf(list.data);

  async function add() {
    const r = await act.run('POST', '/v1/bank-accounts', { ...f, country: country.code || undefined, evidence: letter?.id ?? null });
    if (r) {
      haptic('success');
      setAdding(false);
      setAdded(true);
      setLetter(undefined);
      setF({ bank_name: '', branch: '', account_number: '', account_name: me?.full_name ?? '' });
      list.reload();
    }
  }

  const ready = f.bank_name.trim().length > 1 && f.account_number.replace(/\s/g, '').length >= 6 && f.account_name.trim().length > 1;
  return (
    <Screen
      ground="paper"
      back
      title="Your bank accounts"
      footer={
        adding ? (
          <Button title="Add the account" icon="checkmark" disabled={!ready} loading={act.busy} onPress={() => void add()} />
        ) : (
          <Button title="Add a bank account" icon="add" onPress={() => { setAdding(true); setAdded(false); act.clear(); }} />
        )
      }
    >
      <T v="callout" muted>Accounts in your own name at home, for rent from a tenant and refunds. Money only goes to an account Tenmina has verified.</T>
      <LoadState loading={list.loading} problem={list.problem} onRetry={list.reload} hasData={!!list.data} />
      {added ? (
        <Panel style={{ flexDirection: 'row', alignItems: 'center' }}>
          <Tick size={26} />
          <T v="callout" style={{ flex: 1 }}>Added. Tenmina checks it before any money goes there.</T>
        </Panel>
      ) : null}
      {list.data && !items.length && !adding ? <Empty icon="wallet-outline" title="No bank accounts yet" detail="Add one if a tenant pays you rent or you expect a refund." /> : null}
      {items.map((b) => {
        const st =
          b.verification_status === 'unverified' && b.evidence
            ? { label: 'Waiting to be checked', tone: 'paper' as ChipTone, detail: 'Your bank letter is here. Tenmina staff check it, and two staff must agree.' }
            : (STATE[b.verification_status] ?? { label: b.verification_status.replace(/_/g, ' '), tone: 'paper' as ChipTone, detail: '' });
        return (
          <Panel key={b.id} style={{ gap: space[2] }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[3] }}>
              <View style={{ flex: 1 }}>
                <T v="headline">{`${b.bank_name} ••${b.account_number_last4}`}</T>
                <Label>{[b.account_name, b.branch].filter(Boolean).join(' · ')}</Label>
              </View>
              <Chip label={st.label} tone={st.tone} />
            </View>
            <T v="footnote" muted>{b.verified_at ? `Verified ${day(b.verified_at)}. ${st.detail}` : st.detail}</T>
            {b.name_match === 'mismatch' ? <T v="footnote" color="#B3261E">The name on the account does not match your name. Money can only go to an account in your own name.</T> : null}
          </Panel>
        );
      })}

      {adding ? (
        <Rise style={{ gap: space[3] }}>
          <Label>Add an account</Label>
          <Field label="Bank" value={f.bank_name} onChange={(v) => setF({ ...f, bank_name: v })} placeholder="For example GCB Bank" />
          <Field label="Branch" value={f.branch} onChange={(v) => setF({ ...f, branch: v })} />
          <Field label="Account number" value={f.account_number} onChange={(v) => setF({ ...f, account_number: v })} keyboardType="number-pad" />
          <Field label="Name on the account" value={f.account_name} onChange={(v) => setF({ ...f, account_name: v })} hint="It must be your own name, as the bank writes it." />
          {me ? (
            letter ? (
              <Panel style={{ flexDirection: 'row', alignItems: 'center' }}>
                <Tick size={22} />
                <T v="callout" style={{ flex: 1 }}>{`Bank letter attached: ${letter.original_name ?? 'file'}`}</T>
              </Panel>
            ) : (
              <AddFile label="A letter from your bank (you can add it later)" subject={{ type: 'pmg_owner_document', id: me.id, role: 'bank_letter', country: country.code }} onDone={setLetter} />
            )
          ) : null}
          <View style={{ borderLeftWidth: 3, borderLeftColor: brand.lime, paddingLeft: space[3] }}>
            <T v="footnote" muted>We never change where money goes because of a message, email or call.</T>
          </View>
          <Button title="Cancel" variant="quiet" onPress={() => setAdding(false)} />
        </Rise>
      ) : null}
      <ProblemBox problem={act.problem} />
    </Screen>
  );
}
