import { Text } from 'react-native';
import { useLocalSearchParams } from 'expo-router';
import { formatDay, invoiceBlockers } from '@fidero/shared';
import { type } from '@fidero/tokens';
import { ApprovalSheet } from '../../components/ApprovalSheet';
import { Card, ErrorView, Loading, Muted, Screen } from '../../components/ui';
import { useApi, useLoad } from '../../data';
import { usePalette } from '../../theme';

export default function InvoiceSheet() {
  const api = useApi();
  const p = usePalette();
  const { id } = useLocalSearchParams<{ id: string }>();
  const { data: inv, error, reload } = useLoad((a) => a.getInvoice(id), `invoice-${id}`);

  return (
    <Screen topInset={false}>
      {error ? <ErrorView message={error} onRetry={reload} /> : null}
      {!inv && !error ? <Loading /> : null}
      {inv ? (
        <ApprovalSheet
          eyebrow={`Invoice ${inv.ref} · ${formatDay(inv.issuedOn)}`}
          title={`Pay ${inv.familyMember}'s hospital bill?`}
          amount={inv.amount}
          payee={inv.payee}
          heldAt="Partner Bank"
          checks={[{ label: 'Institution verified by Fidero', ok: inv.institutionVerified }, ...inv.checks]}
          blockers={inv.status === 'awaiting_client' ? invoiceBlockers(inv) : []}
          onApprove={(code) => api.approveInvoice(inv.id, code)}
        >
          <Card>
            <Text style={[type.callout, { color: p.text }]}>{inv.description}</Text>
            <Muted>The hospital's receipt comes back here, {inv.receiptExpected}.</Muted>
          </Card>
        </ApprovalSheet>
      ) : null}
    </Screen>
  );
}
