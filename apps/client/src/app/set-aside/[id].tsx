import { View } from 'react-native';
import { useLocalSearchParams } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, space } from '@tenmina/tokens';
import { Screen, T } from '@tenmina/ui';
import { LoadState, money, toProblem, useApi, useLoad, type ApiMoney } from '@tenmina/mobile';
import { ApprovalSheet } from '../../components/ApprovalSheet';
import type { AccountCommitment, TenminaAccount } from '../../lib';

/**
 * Set money aside for a commitment from the free balance of the client's one Tenmina account (FR-ESC-027), or,
 * with `?keep=1`, keep a cancelled commitment's money in the account instead of a refund to source (FR-ESC-028).
 * Nobody is paid: the client approves with Face ID or the code, no Tenmina staff approve, and it counts only when
 * the bank confirms it.
 */
export default function SetAsideSheet() {
  const api = useApi();
  const { id, keep } = useLocalSearchParams<{ id: string; keep?: string }>();
  const data = useLoad(async (a) => {
    const acc = await a.get<TenminaAccount>('/v1/account');
    const c = acc.commitments.find((x) => x.id === id) ?? (await a.get<{ commitment: AccountCommitment }>(`/v1/account/commitments/${id}`)).commitment;
    return { acc, c };
  }, `set-aside-${id}`);
  if (!data.data) {
    return (
      <Screen ground="ink" back>
        <LoadState loading={data.loading} problem={data.problem} onRetry={data.reload} hasData={false} />
      </Screen>
    );
  }
  const { acc, c } = data.data;
  const keeping = keep === '1';
  const free = acc.balances.find((b) => b.currency === c.currency)?.free_balance;
  const left = Number(c.still_to_set_aside.amount);
  const amount: ApiMoney = keeping ? c.available_to_instruct : { amount: Math.max(0, Math.min(left, Number(free?.amount ?? 0))).toFixed(2), currency: c.currency };
  const short = !keeping && Number(free?.amount ?? 0) < left;
  return (
    <ApprovalSheet
      title={keeping ? 'Keep it in your account' : `Set aside for ${c.title}`}
      source={keeping ? `${c.reference} is being cancelled` : `From your free balance${free ? ` of ${money(free)}` : ''}`}
      amount={amount}
      description={keeping ? 'Instead of a refund to the bank account it came from.' : 'Nobody is paid now. The bank keeps it for this deal only.'}
      payee={{ name: keeping ? 'Your free balance' : c.title, place: keeping ? undefined : (c.payees.length ? `Released only to ${c.payees.join(', ')}` : undefined), matched: null }}
      checks={keeping ? [
        { label: 'The commitment is being cancelled', ok: c.cancelling },
        { label: 'Only you can choose this', ok: true },
      ] : [
        { label: 'The terms are agreed by everyone', ok: c.status !== 'proposed' },
        { label: 'Within what this deal still needs', ok: Number(amount.amount) <= left },
        { label: 'Within your free balance', ok: Number(amount.amount) > 0 },
      ]}
      blockers={keeping ? (c.can_keep_in_account ? [] : ['There is nothing set aside to keep, or the commitment is not being cancelled.'])
        : !c.can_fund ? ['This commitment cannot take money now.'] : Number(amount.amount) <= 0 ? ['Your free balance is empty. Pay into your account first.'] : []}
      chain={['You', 'Bank confirms']}
      after={[{ title: 'The bank moves it inside your account', detail: 'From one line of your account to the other. Nobody is paid.' }, { title: 'It counts when the bank confirms it', detail: 'You see it on the account card.' }]}
      approvedMessage={keeping ? 'We asked the bank to move it back to your free balance.' : 'We asked the bank to set it aside. It counts once the bank confirms it.'}
      onApprove={async (code) => {
        try {
          if (keeping) await api.post(`/v1/account/commitments/${id}/keep-in-account`, { code, gesture: 'press_and_hold' });
          else await api.post('/v1/account/commitments', { commitment_id: id, amount, code, gesture: 'press_and_hold' });
          return undefined;
        } catch (e) {
          return toProblem(e);
        }
      }}
    >
      {short ? (
        <View style={{ flexDirection: 'row', gap: space[3], alignItems: 'flex-start' }}>
          <Ionicons name="information-circle-outline" size={20} color={brand.lime} />
          <T v="callout" muted style={{ flex: 1 }}>{`This deal still needs ${money(c.still_to_set_aside)}. Pay the rest into your account, then set it aside.`}</T>
        </View>
      ) : null}
    </ApprovalSheet>
  );
}
