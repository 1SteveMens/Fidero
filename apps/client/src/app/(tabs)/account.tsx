import { useState } from 'react';
import { Switch, View } from 'react-native';
import { router } from 'expo-router';
import { brand, space } from '@tenmina/tokens';
import { Button, Chip, Label, ListRow, Panel, Rise, Screen, T } from '@tenmina/ui';
import { useSession } from '../../data';

export default function Account() {
  const { signOut } = useSession();
  const [biometric, setBiometric] = useState(true);

  return (
    <Screen ground="ink" tabs>
      <Rise style={{ flexDirection: 'row', alignItems: 'center', gap: space[4] }}>
        <View style={{ width: 64, height: 64, borderRadius: 20, backgroundColor: brand.lime, alignItems: 'center', justifyContent: 'center' }}>
          <T v="title" color={brand.ink}>AO</T>
        </View>
        <View style={{ flex: 1 }}>
          <T v="title" header>Ama Owusu</T>
          <Label>London · identity checked</Label>
        </View>
      </Rise>

      <Rise delay={100}>
        <Label style={{ marginBottom: space[2] }}>Security</Label>
        <Panel style={{ paddingVertical: space[1], gap: 0 }}>
          <ListRow icon="lock-closed" title="Authenticator app" detail="Needed for every approval" trailing={<Chip label="On" tone="lime" />} />
          <ListRow
            icon="finger-print"
            title="Unlock with Face ID"
            detail="Approving still needs your 6-digit code"
            last
            trailing={<Switch value={biometric} onValueChange={setBiometric} trackColor={{ true: brand.lime, false: '#3A3A3A' }} thumbColor={brand.ink} accessibilityLabel="Unlock with Face ID" />}
          />
        </Panel>
      </Rise>

      <Rise delay={180}>
        <Label style={{ marginBottom: space[2] }}>Money and settings</Label>
        <Panel style={{ paddingVertical: space[1], gap: 0 }}>
          <ListRow icon="business-outline" title="Where your money is held" detail="Partner Bank. Tenmina never holds it." />
          <ListRow icon="receipt-outline" title="Receipts and statements" onPress={() => undefined} />
          <ListRow icon="flag-outline" title="Country" detail="Ghana · prices in GHS and USD" />
          <ListRow icon="notifications-outline" title="Notifications" detail="App, email and WhatsApp" last />
        </Panel>
      </Rise>

      <Rise delay={260}>
        <Label style={{ marginBottom: space[2] }}>Privacy</Label>
        <Panel style={{ paddingVertical: space[1], gap: 0 }}>
          <ListRow icon="shield-checkmark-outline" title="What we hold about you" detail="See and download your data" onPress={() => undefined} />
          <ListRow icon="trash-outline" iconTone="orange" title="Delete account" detail="See what is deleted and what we must keep" onPress={() => router.push('/account/delete')} last />
        </Panel>
      </Rise>

      <Button
        title="Sign out"
        variant="quiet"
        onPress={() => {
          signOut();
          router.replace('/welcome');
        }}
      />
      <Label style={{ textAlign: 'center' }}>Tenmina 0.2 · demo build with sample data</Label>
    </Screen>
  );
}
