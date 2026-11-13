import { useEffect, useMemo, useState } from 'react';
import { View } from 'react-native';
import { router } from 'expo-router';
import { space } from '@tenmina/tokens';
import { Button, Choice, Input, Label, Panel, Screen, T, Tick } from '@tenmina/ui';
import { newUuid } from '@tenmina/mobile';
import { useField } from '../../store';
import { CaptureButton, OfflineBanner, Submitted } from '../../screens/common';

const KINDS = [
  { key: 'official_search_fee', title: 'Official search fee', detail: 'Paid at the registry counter' },
  { key: 'travel', title: 'Travel', detail: 'To and from assigned work' },
  { key: 'approved_cost', title: 'A cost Tenmina approved', detail: 'Agreed with your case manager first' },
];

/**
 * Claim an expense (SCR-MOB-21; FR-PRO-004, FR-MOB-002): the receipt is
 * photographed with this app's camera only, then queued offline like evidence.
 * A receipt pays once; a claim above the limit needs a second approval.
 */
export default function Claim() {
  const { progress, setProgress, capturesFor, queue } = useField();
  const draft = progress('claim-draft') as { id?: string };
  const subjectId = useMemo(() => draft.id ?? newUuid(), [draft.id]);
  const [kind, setKind] = useState('official_search_fee');
  const [description, setDescription] = useState('');
  const [amount, setAmount] = useState('');
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [sent, setSent] = useState(false);
  useEffect(() => {
    if (!draft.id) setProgress('claim-draft', { id: subjectId });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft.id]);
  const receipts = capturesFor('pro_expense_receipt', subjectId, 'receipt');

  if (sent) return <Submitted ground="paper" title="Claim saved." detail="It is sent with the receipt when you have signal. A case manager checks it; it is paid in the next payment run." />;

  const ready = description.trim().length > 2 && Number(amount) > 0 && /^\d{4}-\d{2}-\d{2}$/.test(date) && receipts.length > 0;
  function submit() {
    queue({
      kind: 'expense',
      label: `Expense: ${description.trim()}`,
      subjectType: 'pro_expense_receipt',
      subjectId,
      path: '/v1/me/pro/expense-claims',
      body: { kind, description: description.trim(), amount: Number(amount).toFixed(2), incurred_on: date, receipt_evidence_id: null },
      needs: [{ captureId: receipts[receipts.length - 1].id, at: 'receipt_evidence_id' }],
    });
    setProgress('claim-draft', { id: undefined });
    setSent(true);
  }

  return (
    <Screen ground="paper" back title="Claim an expense" footer={<Button title="Send the claim" icon="cloud-upload-outline" disabled={!ready} onPress={submit} />}>
      <OfflineBanner />
      <Panel style={{ gap: 0 }}>
        <Label>What was it?</Label>
        {KINDS.map((k) => (
          <Choice key={k.key} selected={kind === k.key} onPress={() => setKind(k.key)} title={k.title} detail={k.detail} />
        ))}
      </Panel>
      <Input label="What for" value={description} onChange={setDescription} placeholder="For example: search fee at Lands Commission, Accra" />
      <Input label="Amount (GHS)" value={amount} onChange={(v) => setAmount(v.replace(/[^0-9.]/g, ''))} keyboardType="decimal-pad" />
      <Input label="Date paid (YYYY-MM-DD)" value={date} onChange={setDate} />
      <Panel style={{ flexDirection: 'row', alignItems: 'center', gap: space[3] }}>
        {receipts.length ? <Tick /> : <View style={{ width: 22, height: 22, borderRadius: 7, borderWidth: 2, borderColor: '#D6D3CB' }} />}
        <View style={{ flex: 1 }}>
          <T v="headline" style={{ fontSize: 15 }}>The receipt</T>
          <T v="footnote" muted>Photograph it with this app. One receipt pays once.</T>
        </View>
        <CaptureButton subjectType="pro_expense_receipt" subjectId={subjectId} reqKey="receipt" label="Receipt" count={receipts.length} />
      </Panel>
      <T v="footnote" muted>A claim above the limit for its kind needs a second approval. Paid by Tenmina in the next payment run.</T>
      <Button title="Cancel" variant="quiet" onPress={() => router.back()} />
    </Screen>
  );
}
