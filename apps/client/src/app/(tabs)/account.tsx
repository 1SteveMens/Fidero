import { useState } from 'react';
import { Switch, Text, View } from 'react-native';
import { router } from 'expo-router';
import { radius, space, type } from '@fidero/tokens';
import { Card, Row, Screen, SectionHeader } from '../../components/ui';
import { usePalette } from '../../theme';

export default function Account() {
  const p = usePalette();
  const [biometric, setBiometric] = useState(true);

  return (
    <Screen title="Account">
      <Card>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[3] }}>
          <View style={{ width: 56, height: 56, borderRadius: 28, backgroundColor: p.primary, alignItems: 'center', justifyContent: 'center' }}>
            <Text style={[type.title, { color: p.onPrimary }]}>AO</Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={[type.headline, { color: p.text }]}>Ama Owusu</Text>
            <Text style={[type.footnote, { color: p.textMuted }]}>London · identity checked</Text>
          </View>
        </View>
      </Card>

      <SectionHeader title="Settings" />
      <View style={{ gap: space[3] }}>
        <Row icon="flag" tone="neutral" title="Country" detail="Ghana · prices in GHS and USD" />
        <Row icon="notifications" tone="neutral" title="Notifications" detail="App, email and WhatsApp" />
        <Card>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[3], minHeight: 44 }}>
            <View style={{ flex: 1 }}>
              <Text style={[type.headline, { color: p.text }]}>Unlock with Face ID</Text>
              <Text style={[type.footnote, { color: p.textMuted }]}>Approving a payment still needs your 6-digit code.</Text>
            </View>
            <Switch value={biometric} onValueChange={setBiometric} accessibilityLabel="Unlock with Face ID" />
          </View>
        </Card>
      </View>

      <SectionHeader title="Privacy" />
      <View style={{ gap: space[3] }}>
        <Row icon="shield-checkmark" tone="neutral" title="What we hold about you" detail="See and download your data" />
        <Row icon="trash" tone="danger" title="Delete account" detail="See what is deleted and what we must keep" onPress={() => router.push('/account/delete')} />
      </View>
      <View style={{ borderRadius: radius.md, padding: space[3] }}>
        <Text style={[type.footnote, { color: p.textMuted, textAlign: 'center' }]}>Fidero 0.1 · demo build with sample data</Text>
      </View>
    </Screen>
  );
}
