import { Linking, Switch, View } from 'react-native';
import { router } from 'expo-router';
import { brand, space } from '@tenmina/tokens';
import { Button, Chip, Label, ListRow, Panel, Rise, Screen, T } from '@tenmina/ui';
import { APP_VERSION, initials, portalUrl, useSession, when, words } from '@tenmina/mobile';
import { useField } from '../../store';

const ROLE: Record<string, string> = { IN: 'Inspector', CT: 'Contractor', CE: 'Carer or errand agent', RN: 'Runner', SV: 'Surveyor', QS: 'Quantity surveyor', LW: 'Lawyer' };

/** Account, storage and help (SCR-MOB-13; FR-MOB-008, FR-MOB-009, FR-APP-004). */
export default function Account() {
  const { me, signOut, api } = useSession();
  const { device, captures, ops, noSignal, setNoSignal, lastSyncAt, reset } = useField();
  const waiting = ops.filter((o) => o.state !== 'sent').length;
  const onPhone = captures.filter((c) => c.state !== 'stored').length;
  return (
    <Screen ground="ink" tabs>
      <Rise style={{ flexDirection: 'row', alignItems: 'center', gap: space[4] }}>
        <View style={{ width: 64, height: 64, borderRadius: 20, backgroundColor: brand.lime, alignItems: 'center', justifyContent: 'center' }}>
          <T v="title" color={brand.ink}>{initials(me?.full_name)}</T>
        </View>
        <View style={{ flex: 1 }}>
          <T v="title" header>{me?.full_name ?? ''}</T>
          <Label>{(me?.roles ?? []).map((r) => ROLE[r] ?? r).join(' · ')}</Label>
        </View>
      </Rise>
      <Rise delay={80}>
        <Label style={{ marginBottom: space[2] }}>This phone</Label>
        <Panel style={{ gap: 0, paddingVertical: space[1] }}>
          <ListRow
            icon="key-outline"
            title="Registered to you"
            detail={device ? `${words(device.alg)} key · since ${when(device.registeredAt)} · ${device.id.slice(0, 8)}` : 'Not registered'}
            trailing={device ? <Chip tone="lime" label={words(device.status)} /> : undefined}
          />
          <ListRow icon="camera-outline" title="Evidence taken in this app" detail="Camera only. No gallery or files (RUL-08)" trailing={<Chip tone="paper" label={String(captures.length)} />} />
          <ListRow icon="cloud-upload-outline" title="Waiting to upload" detail={`${onPhone} ${onPhone === 1 ? 'capture' : 'captures'} stored on the phone until Tenmina has them`} trailing={<Chip tone={waiting ? 'orange' : 'paper'} label={String(waiting)} />} />
          <ListRow icon="sync-outline" title="Last sync" detail={lastSyncAt ? when(lastSyncAt) : 'Not yet'} />
          <ListRow
            icon="cloud-offline-outline"
            title="Test: pretend there is no signal"
            detail="Try the upload queue without airplane mode"
            last
            trailing={<Switch value={noSignal} onValueChange={setNoSignal} trackColor={{ true: brand.orange, false: '#3A3A3A' }} thumbColor={brand.ink} accessibilityLabel="Pretend there is no signal" />}
          />
        </Panel>
      </Rise>
      <Rise delay={160}>
        <Label style={{ marginBottom: space[2] }}>Help</Label>
        <Panel style={{ gap: 0, paddingVertical: space[1] }}>
          <ListRow icon="help-circle-outline" title="Talk to Tenmina" onPress={() => void Linking.openURL(`${portalUrl()}/help`)} />
          <ListRow icon="trash-outline" iconTone="orange" title="Delete my account" detail="What is deleted and what we must keep (FR-APP-004)" onPress={() => router.push('/delete')} last />
        </Panel>
      </Rise>
      {waiting ? <T v="footnote" muted>{`${waiting} ${waiting === 1 ? 'item is' : 'items are'} not sent yet. Send them before you sign out, or they stay on this phone.`}</T> : null}
      <Button
        title="Sign out"
        variant="quiet"
        disabled={waiting > 0}
        onPress={() => {
          void signOut()
            .then(reset)
            .then(() => router.replace('/welcome'));
        }}
      />
      <Label style={{ textAlign: 'center' }}>{`Tenmina Field ${APP_VERSION} · ${api.header}`}</Label>
    </Screen>
  );
}
