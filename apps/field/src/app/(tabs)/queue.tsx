import { View } from 'react-native';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, space } from '@fidero/tokens';
import { Chip, Label, Panel, Rise, Screen, T } from '@fidero/ui';
import { useField } from '../../store';
import { timeOfDay } from '../../capture';
import { OnlineChip } from './index';

const ICON = { capture: 'camera-outline', submission: 'checkmark-done-outline', concern: 'flag-outline' } as const;

/** Upload queue (SCR-MOB-08): everything saved on the phone until Fidero confirms receipt (FR-MOB-005, FR-MOB-008). */
export default function Queue() {
  const { queue, online } = useField();
  const waiting = queue.filter((q) => q.state !== 'sent');
  const sent = queue.filter((q) => q.state === 'sent').slice(-8).reverse();
  return (
    <Screen ground="paper" tabs title="Queue" trailing={<OnlineChip />}>
      {!online ? (
        <Rise>
          <Panel tone="orange" style={{ flexDirection: 'row', alignItems: 'center' }}>
            <Ionicons name="cloud-offline" size={22} color={brand.ink} />
            <T v="callout" color={brand.ink} style={{ flex: 1 }}>{`Offline. ${waiting.length} ${waiting.length === 1 ? 'item is' : 'items are'} saved on this phone and upload by themselves when you have signal.`}</T>
          </Panel>
        </Rise>
      ) : null}
      <Rise delay={60}>
        <Label style={{ marginBottom: space[2] }}>{`Waiting · ${waiting.length}`}</Label>
        {waiting.length === 0 ? (
          <Panel style={{ flexDirection: 'row', alignItems: 'center' }}>
            <Ionicons name="checkmark-circle" size={22} color={brand.ink} />
            <T v="callout" style={{ flex: 1 }}>Nothing waiting. Everything has reached Fidero.</T>
          </Panel>
        ) : (
          <Panel style={{ gap: 0, paddingVertical: space[1] }}>
            {waiting.map((q, i) => (
              <View key={q.id} style={{ flexDirection: 'row', alignItems: 'center', gap: space[3], paddingVertical: space[3], borderBottomWidth: i < waiting.length - 1 ? 1 : 0, borderBottomColor: '#ECEAE4' }}>
                <Ionicons name={ICON[q.kind]} size={20} />
                <View style={{ flex: 1 }}>
                  <T v="headline" style={{ fontSize: 15 }}>{q.label}</T>
                  <Label>{`Saved ${timeOfDay(q.createdAt)}`}</Label>
                </View>
                {q.state === 'sending' ? <Chip tone="lime" label="Sending" /> : <Chip tone="paper" label="Waiting" />}
              </View>
            ))}
          </Panel>
        )}
      </Rise>
      {sent.length > 0 ? (
        <Rise delay={120}>
          <Label style={{ marginBottom: space[2] }}>Received by Fidero</Label>
          <Panel style={{ gap: 0, paddingVertical: space[1] }}>
            {sent.map((q, i) => (
              <View key={q.id} style={{ flexDirection: 'row', alignItems: 'center', gap: space[3], paddingVertical: space[3], borderBottomWidth: i < sent.length - 1 ? 1 : 0, borderBottomColor: '#ECEAE4' }}>
                <Ionicons name={ICON[q.kind]} size={20} />
                <T v="callout" style={{ flex: 1 }}>{q.label}</T>
                <Label>{q.sentAt ? timeOfDay(q.sentAt) : ''}</Label>
              </View>
            ))}
          </Panel>
        </Rise>
      ) : null}
      <T v="footnote" muted>Items stay on this phone, even if the app is closed or the phone restarts, until Fidero confirms it has them. Demo build: there is no server yet, so items are marked received a moment after the phone is online.</T>
    </Screen>
  );
}
