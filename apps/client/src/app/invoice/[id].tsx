import { View } from 'react-native';
import { useLocalSearchParams } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { formatDay, invoiceBlockers } from '@tenmina/shared';
import { brand, space } from '@tenmina/tokens';
import { ApprovalSheet } from '../../components/ApprovalSheet';
import { ErrorView, Loading, Screen, T } from '@tenmina/ui';
import { useApi, useLoad } from '../../data';

export default function InvoiceSheet() {
  const api = useApi();
  const { id } = useLocalSearchParams<{ id: string }>();
  const { data: inv, error, reload } = useLoad((a) => a.getInvoice(id), `invoice-${id}`);

  if (error) return <Screen ground="ink"><ErrorView message={error} onRetry={reload} /></Screen>;
  if (!inv) return <Screen ground="ink"><Loading /></Screen>;

  return (
    <ApprovalSheet
      title={`Pay for ${inv.familyMember}`}
      source={`${inv.ref} · issued ${formatDay(inv.issuedOn)}`}
      amount={inv.amount}
      description={inv.description}
      payee={inv.payee}
      payeePlace={inv.institutionPlace}
      checks={[{ label: 'Institution verified by Tenmina', ok: inv.institutionVerified }, ...inv.checks]}
      blockers={inv.status === 'awaiting_client' ? invoiceBlockers(inv) : ['You have already approved this bill. Tenmina staff are approving it now.']}
      onApprove={(code) => api.approveInvoice(inv.id, code)}
    >
      <View style={{ flexDirection: 'row', gap: space[3], alignItems: 'flex-start' }}>
        <Ionicons name="business-outline" size={20} color={brand.lime} />
        <T v="callout" muted style={{ flex: 1 }}>
          {`${inv.payee.name} is paid straight into its own account, never to a person. Its receipt comes back here, ${inv.receiptExpected}.`}
        </T>
      </View>
    </ApprovalSheet>
  );
}
