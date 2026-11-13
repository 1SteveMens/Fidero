import { Linking, View } from 'react-native';
import { router } from 'expo-router';
import { brand, space } from '@tenmina/tokens';
import { Button, Chip, Label, ListRow, Panel, Rise, Screen, T } from '@tenmina/ui';
import { APP_VERSION, initials, itemsOf, portalUrl, useGet, useSession } from '@tenmina/mobile';

/** Account (SCR-PTL-20, 21, 34 and SCR-APP-04): who you are, security, how fees are paid, your data. */
export default function Account() {
  const { me, signOut, config, api } = useSession();
  const reps = useGet<{ items: { id: string; full_name: string; status: string }[] }>('/v1/me/representatives');
  const banks = useGet<{ items: { id: string; bank_name: string; account_number_last4: string; verification_status: string }[] }>('/v1/bank-accounts');
  const web = (config?.fee_payment_mode ?? 'web') === 'web';

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
            icon="lock-closed"
            title="Authenticator app"
            detail="Needed for every approval"
            onPress={() => router.push('/account/security')}
            trailing={me?.mfa_enabled ? <Chip label="On" tone="lime" /> : <Chip label="Set up" tone="orange" />}
          />
          <ListRow icon="phone-portrait-outline" title="Unlock with Face ID or fingerprint" detail="Comes with the test build. Approving always needs your code." last />
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
            onPress={() => void Linking.openURL(`${portalUrl()}/account/bank-accounts`)}
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

      <Button title="Get help" variant="dark" icon="help-circle-outline" onPress={() => void Linking.openURL(`${portalUrl()}/help`)} />
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
