import { useCallback, useState } from 'react';
import { View } from 'react-native';
import { router, useFocusEffect } from 'expo-router';
import { brand, space } from '@tenmina/tokens';
import { Button, Chip, Label, ListRow, Panel, Rise, Screen, T } from '@tenmina/ui';
import { APP_VERSION, initials, itemsOf, localApprovalKey, useGet, useSession } from '@tenmina/mobile';

/**
 * Account (SCR-PTL-20, 21, 34 and SCR-APP-04): who you are, security, how fees
 * are paid, your data. Everything opens inside the app: the mobile number for
 * codes by text message (FR-ACC-015), bank accounts, representatives and help.
 */
export default function Account() {
  const { me, signOut, config, api } = useSession();
  const reps = useGet<{ items: { id: string; full_name: string; status: string }[] }>('/v1/me/representatives');
  const banks = useGet<{ items: { id: string; bank_name: string; account_number_last4: string; verification_status: string }[] }>('/v1/bank-accounts');
  const web = (config?.fee_payment_mode ?? 'web') === 'web';
  const [faceId, setFaceId] = useState(false);
  useFocusEffect(
    useCallback(() => {
      if (me) void localApprovalKey(me.id).then((k) => setFaceId(!!k));
    }, [me]),
  );

  return (
    <Screen ground="ink" tabs>
      <Rise style={{ flexDirection: 'row', alignItems: 'center', gap: space[4] }}>
        <View style={{ width: 64, height: 64, borderRadius: 20, backgroundColor: brand.lime, alignItems: 'center', justifyContent: 'center' }}>
          <T v="title" color={brand.ink}>{initials(me?.full_name)}</T>
        </View>
        <View style={{ flex: 1 }}>
          <T v="title" header>{me?.full_name ?? ''}</T>
          <Label>{`${me?.email ?? ''} · identity ${me?.id_check_status === 'passed' ? 'checked' : 'not checked yet'}`}</Label>
        </View>
      </Rise>

      <Rise delay={80}>
        <Label style={{ marginBottom: space[2] }}>Security</Label>
        <Panel style={{ paddingVertical: space[1], gap: 0 }}>
          <ListRow
            icon="chatbubble-ellipses-outline"
            title="Mobile number"
            detail={
              me?.sms_pause
                ? `${me.phone_masked ?? ''} · approvals by text paused`
                : me?.mfa_enabled
                  ? `${me?.phone_masked ?? ''} · you sign in with the authenticator`
                  : `${me?.phone_masked ?? ''} · codes for sign-in and the website`
            }
            onPress={() => router.push('/account/phone')}
            trailing={me?.sms_pause ? <Chip label="Paused" tone="orange" /> : me?.phone_verified ? <Chip label="Confirmed" tone="lime" /> : <Chip label="Confirm" tone="orange" />}
          />
          <ListRow
            icon="scan-outline"
            title="Face ID or fingerprint for approvals"
            detail={faceId ? 'On for this phone · manage phones' : 'Approve without typing a code'}
            onPress={() => router.push('/account/approval-keys')}
            trailing={faceId ? <Chip label="On" tone="lime" /> : <Chip label="Off" tone="paper" />}
          />
          <ListRow
            icon="key-outline"
            title="Authenticator app"
            detail={me?.mfa_enabled ? 'Replaces the text message code' : 'Optional, instead of codes by text'}
            onPress={() => router.push('/account/security')}
            trailing={me?.mfa_enabled ? <Chip label="On" tone="lime" /> : <Chip label="Off" tone="paper" />}
            last
          />
        </Panel>
      </Rise>

      <Rise delay={140}>
        <Label style={{ marginBottom: space[2] }}>Money and settings</Label>
        <Panel style={{ paddingVertical: space[1], gap: 0 }}>
          <ListRow icon="business-outline" title="Where your money is held" detail="At the partner bank, in your own accounts. Tenmina never holds it." />
          <ListRow
            icon="card-outline"
            title="Paying Tenmina's fees"
            detail={web ? 'On the Tenmina website, never inside the app' : 'With the payment provider in the app'}
            trailing={<Chip label={web ? 'Website' : 'In app'} tone="paper" />}
          />
          <ListRow
            icon="wallet-outline"
            title="Your bank accounts"
            detail={banks.data ? `${itemsOf(banks.data).length} saved · refunds go only here` : 'Loading'}
            onPress={() => router.push('/account/bank-accounts')}
          />
          <ListRow icon="notifications-outline" title="Notifications" detail="App, email, text and WhatsApp" onPress={() => router.push('/account/notifications')} />
          <ListRow
            icon="people-outline"
            title="Representatives"
            detail={reps.data ? `${itemsOf(reps.data).filter((r) => r.status === 'active').length} active · read-only or limited` : 'People who act for you'}
            onPress={() => router.push('/account/representatives')}
          />
          <ListRow icon="flag-outline" title="Country" detail={me?.home_country === 'GH' ? 'Ghana · prices in GHS' : (me?.home_country ?? '')} last />
        </Panel>
      </Rise>

      <Rise delay={200}>
        <Label style={{ marginBottom: space[2] }}>Privacy</Label>
        <Panel style={{ paddingVertical: space[1], gap: 0 }}>
          <ListRow icon="shield-checkmark-outline" title="My data" detail="Ask for a copy of what we hold" onPress={() => router.push('/account/data')} />
          <ListRow icon="trash-outline" iconTone="orange" title="Delete my account" detail="What is deleted and what we must keep" onPress={() => router.push('/account/delete')} last />
        </Panel>
      </Rise>

      <Button title="Get help" variant="dark" icon="help-circle-outline" onPress={() => router.push('/help')} />
      <Button
        title="Sign out"
        variant="quiet"
        onPress={() => {
          void signOut().then(() => router.replace('/welcome'));
        }}
      />
      <Label style={{ textAlign: 'center' }}>{`Tenmina ${APP_VERSION} · ${api.header}`}</Label>
    </Screen>
  );
}
