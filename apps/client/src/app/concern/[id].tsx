import { useLocalSearchParams } from 'expo-router';
import { Chip, Label, Panel, Screen, T } from '@tenmina/ui';
import { KV, LoadState, day, useGet, words } from '@tenmina/mobile';

interface Concern {
  id: string;
  reference: string;
  family_member: { full_name: string };
  kind: string;
  severity: string;
  raised_at: string;
  status: string;
  client_outcome: string;
  actioned_at: string | null;
  closed_at: string | null;
}

/** A care concern (FR-CARE-006): what Tenmina did about it. The carer's own notes stay with Tenmina (US-CARE-006). */
export default function ConcernScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const c = useGet<Concern>(`/v1/concerns/${id}`);
  const d = c.data;
  return (
    <Screen ground="paper" back eyebrow={d?.reference} title={d ? `${words(d.kind)} concern` : 'Concern'}>
      <LoadState loading={c.loading} problem={c.problem} onRetry={c.reload} hasData={!!d} />
      {d ? (
        <>
          <Chip label={words(d.status)} tone={d.closed_at ? 'lime' : 'paper'} />
          <KV rows={[['About', d.family_member.full_name], ['Raised', day(d.raised_at)], ['How serious', words(d.severity)]]} />
          <Panel>
            <Label>What we did</Label>
            <T v="callout">{d.client_outcome || 'A Tenmina reviewer is looking at it today. We will tell you what we did.'}</T>
          </Panel>
        </>
      ) : null}
    </Screen>
  );
}
