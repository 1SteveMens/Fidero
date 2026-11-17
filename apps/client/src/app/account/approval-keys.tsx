import { useCallback, useEffect, useState } from 'react';
import { Platform, View } from 'react-native';
import { router, useFocusEffect } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, space } from '@tenmina/tokens';
import { Button, Chip, Label, Panel, Screen, T } from '@tenmina/ui';
import { LoadState, ProblemBox, day, forgetApprovalKey, itemsOf, localApprovalKey, toProblem, useGet, useSession, when, type Problem } from '@tenmina/mobile';
import { EnrolBiometric } from '../../components/EnrolBiometric';

interface ApprovalKey {
  id: string;
  device_name: string;
  platform: 'ios' | 'android';
  status: 'active' | 'revoked';
  created_at: string;
  last_used_at: string | null;
}

/**
 * Phones that can approve with Face ID or a fingerprint (FR-ACC-014): this
 * phone, turn it on or off; other phones, remove any you no longer use. A
 * password reset or a locked account removes them all.
 */
export default function ApprovalKeys() {
  const { me, api } = useSession();
  const keys = useGet<{ items: ApprovalKey[] }>('/v1/me/approval-keys', { status: 'active' });
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem>();
  const [localId, setLocalId] = useState<string | null>();

  const readLocal = useCallback(() => {
    if (me) void localApprovalKey(me.id).then((k) => setLocalId(k?.keyId ?? null));
  }, [me]);
  useFocusEffect(readLocal);

  const all = itemsOf(keys.data);
  const here = all.find((k) => k.id === localId);
  const others = all.filter((k) => k.id !== localId);

  // A key removed elsewhere (another phone, a password reset) is forgotten here too.
  useEffect(() => {
    if (me && keys.data && localId && !itemsOf(keys.data).some((k) => k.id === localId)) {
      void forgetApprovalKey(me.id).then(() => setLocalId(null));
    }
  }, [me, keys.data, localId]);

  async function remove(k: ApprovalKey) {
    setBusy(true);
    setProblem(undefined);
    try {
      await api.del(`/v1/me/approval-keys/${k.id}`);
      if (me && k.id === localId) await forgetApprovalKey(me.id);
      readLocal();
      keys.reload();
    } catch (e) {
      setProblem(toProblem(e));
    }
    setBusy(false);
  }

  return (
    <Screen ground="ink" back title="Phones that can approve">
      <T v="callout" muted>Approve payments with Face ID or a fingerprint instead of typing the code. Each phone has its own key; your face or fingerprint never leaves the phone.</T>
      {!me?.mfa_enabled ? (
        <Panel style={{ borderWidth: 2, borderColor: brand.orange, backgroundColor: 'transparent' }}>
          <Label color={brand.orange}>Set up your authenticator first</Label>
          <T v="callout">Face ID and fingerprint approvals need an authenticator app as the back-up.</T>
          <Button title="Set up the authenticator" variant="dark" onPress={() => router.push('/account/security')} />
        </Panel>
      ) : (
        <>
          <LoadState loading={keys.loading} problem={keys.problem} onRetry={keys.reload} hasData={!!keys.data} />
          <Label>This phone</Label>
          <Panel>
            {here ? (
              <>
                <KeyRow k={here} />
                <Button title="Turn off on this phone" variant="danger" loading={busy} onPress={() => void remove(here)} />
              </>
            ) : Platform.OS === 'web' ? (
              <T v="callout" muted>A browser uses the code from your authenticator app. Face ID and fingerprint work in the iPhone and Android apps.</T>
            ) : localId === undefined ? null : (
              <EnrolBiometric
                onDone={() => {
                  readLocal();
                  keys.reload();
                }}
              />
            )}
          </Panel>
          <Label>Other phones</Label>
          {others.length ? (
            <Panel style={{ gap: space[3] }}>
              {others.map((k, i) => (
                <View key={k.id} style={{ gap: space[2], paddingTop: i ? space[3] : 0, borderTopWidth: i ? 1 : 0, borderTopColor: '#2C2C2C' }}>
                  <KeyRow k={k} />
                  <Button title={`Remove ${k.device_name}`} variant="danger" loading={busy} onPress={() => void remove(k)} />
                </View>
              ))}
            </Panel>
          ) : keys.data ? (
            <T v="callout" muted>No other phone can approve.</T>
          ) : null}
          <ProblemBox problem={problem} />
        </>
      )}
    </Screen>
  );
}

function KeyRow({ k }: { k: ApprovalKey }) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[3] }}>
      <Ionicons name={k.platform === 'ios' ? 'phone-portrait-outline' : 'phone-portrait'} size={24} color={brand.lime} />
      <View style={{ flex: 1, gap: 2 }}>
        <T v="headline">{k.device_name}</T>
        <Label>{`Added ${day(k.created_at)} · ${k.last_used_at ? `last used ${when(k.last_used_at)}` : 'not used yet'}`}</Label>
      </View>
      <Chip label="On" tone="lime" />
    </View>
  );
}
