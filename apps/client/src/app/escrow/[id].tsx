import { useLocalSearchParams } from 'expo-router';
import { formatDay, releaseBlockers, SAMPLE_FRESH_SEARCH_WINDOW_DAYS, SAMPLE_TODAY } from '@fidero/shared';
import { ApprovalSheet } from '../../components/ApprovalSheet';
import { ErrorView, Loading, Screen } from '../../components/ui';
import { useApi, useLoad } from '../../data';

export default function EscrowSheet() {
  const api = useApi();
  const { id } = useLocalSearchParams<{ id: string }>();
  const { data: e, error, reload } = useLoad((a) => a.getEscrow(id), `escrow-${id}`);

  return (
    <Screen topInset={false}>
      {error ? <ErrorView message={error} onRetry={reload} /> : null}
      {!e && !error ? <Loading /> : null}
      {e ? (
        <ApprovalSheet
          eyebrow={`Escrow · ${e.bankRef}`}
          title={`Release to the seller for ${e.title}?`}
          amount={e.release}
          payee={e.payee}
          heldAt={e.heldAt}
          checks={e.conditions.map((c) => ({ label: c.closedOn ? `${c.text} · ${formatDay(c.closedOn)}` : c.text, ok: !!c.closedOn }))}
          blockers={
            e.status === 'ready_to_release'
              ? releaseBlockers(e, { todayIso: SAMPLE_TODAY, freshSearchWindowDays: SAMPLE_FRESH_SEARCH_WINDOW_DAYS })
              : []
          }
          onApprove={(code) => api.approveRelease(e.id, code)}
        />
      ) : null}
    </Screen>
  );
}
