import { router } from 'expo-router';
import { Switch, View } from 'react-native';
import { brand, space } from '@fidero/tokens';
import { Button, Chip, Label, ListRow, Panel, Rise, Screen, T } from '@fidero/ui';
import { useField, useFieldLoad } from '../../store';

export default function Account() {
  const { signOut, captures, queue, noSignal, setNoSignal } = useField();
  const { data } = useFieldLoad((api) => api.me(), 'me');
  const waiting = queue.filter((q) => q.state !== 'sent').length;
  return (
    <Screen ground="ink" tabs>
      <Rise style={{ flexDirection: 'row', alignItems: 'center', gap: space[4] }}>
        <View style={{ width: 64, height: 64, borderRadius: 20, backgroundColor: brand.lime, alignItems: 'center', justifyContent: 'center' }}>
          <T v="title" color={brand.ink}>{data ? data.name.split(' ').map((w) => w[0]).join('') : ''}</T>
        </View>
        <View style={{ flex: 1 }}>
          <T v="title" header>{data?.name ?? ''}</T>
          <Label>{data ? `${data.roleLabel} · this phone registered` : ''}</Label>
        </View>
      </Rise>
      <Rise delay={80}>
        <Label style={{ marginBottom: space[2] }}>This phone</Label>
        <Panel style={{ gap: 0, paddingVertical: space[1] }}>
          <ListRow icon="camera-outline" title="Evidence taken in this app" detail="Camera only. No gallery or files (RUL-08)" trailing={<Chip tone="lime" label={String(captures.length)} />} />
          <ListRow icon="cloud-upload-outline" title="Waiting to upload" detail="Kept until Fidero confirms receipt" trailing={<Chip tone="paper" label={String(waiting)} />} />
          <ListRow icon="lock-closed" title="Sealing photos" detail="Fingerprinted now. Hardware signing comes with the test build (FR-MOB-004)" />
          <ListRow
            icon="cloud-offline-outline"
            title="Pretend there is no signal"
            detail="Demo only: test the upload queue without airplane mode"
            last
            trailing={<Switch value={noSignal} onValueChange={setNoSignal} trackColor={{ true: brand.orange, false: '#3A3A3A' }} thumbColor={brand.ink} accessibilityLabel="Pretend there is no signal" />}
          />
        </Panel>
      </Rise>
      <Rise delay={160}>
        <Label style={{ marginBottom: space[2] }}>Help</Label>
        <Panel style={{ gap: 0, paddingVertical: space[1] }}>
          <ListRow icon="help-circle-outline" title="Talk to Fidero" onPress={() => undefined} />
          <ListRow icon="trash-outline" iconTone="orange" title="Delete my account" detail="See what is deleted and what we must keep (FR-APP-004)" onPress={() => undefined} last />
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
      <Label style={{ textAlign: 'center' }}>Fidero Field 0.1 · demo build with sample data</Label>
    </Screen>
  );
}
