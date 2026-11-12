import { useLocalSearchParams } from 'expo-router';
import { formatDay, releaseBlockers, SAMPLE_FRESH_SEARCH_WINDOW_DAYS, SAMPLE_TODAY } from '@fidero/shared';
import { ApprovalSheet } from '../../components/ApprovalSheet';
import { ErrorView, Loading, Screen } from '../../components/ui';
import { useApi, useLoad } from '../../data';

export default function EscrowSheet() {
  const api = useApi();
  const { id } = useLocalSearchParams<{ id: string }>();
  const { data: e, error, reload } = useLoad((a) => a.getEscrow(id), `escrow-${id}`);

  if (error) return <Screen ground="ink"><ErrorView message={error} onRetry={reload} /></Screen>;
  if (!e) return <Screen ground="ink"><Loading /></Screen>;

  return (
    <ApprovalSheet
      title="Approve release"
      source={`Release from ${e.bankRef}`}
      amount={e.release}
      description={`To the seller for ${e.title}`}
      payee={e.payee}
      checks={e.conditions.map((c) => ({ label: c.text, detail: c.closedOn ? formatDay(c.closedOn) : undefined, ok: !!c.closedOn }))}
      blockers={
        e.status === 'ready_to_release'
          ? releaseBlockers(e, { todayIso: SAMPLE_TODAY, freshSearchWindowDays: SAMPLE_FRESH_SEARCH_WINDOW_DAYS })
          : [`This release is ${e.status.replace(/_/g, ' ')}. Nothing for you to do now.`]
      }
      onApprove={(code) => api.approveRelease(e.id, code)}
    />
  );
}
