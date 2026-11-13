import type { ComponentProps } from 'react';
import { View } from 'react-native';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, space } from '@tenmina/tokens';
import { Button, Chip, Label, Panel, Rise, Screen, T } from '@tenmina/ui';
import { clock } from '@tenmina/mobile';
import { useField } from '../../store';
import { OnlineChip } from '../../screens/common';
import type { Op } from '../../types';

const ICON: Record<string, ComponentProps<typeof Ionicons>['name']> = {
  evidence: 'camera-outline',
  submission: 'checkmark-done-outline',
  inspection: 'clipboard-outline',
  checkin: 'locate-outline',
  checkout: 'exit-outline',
  visit_item: 'heart-outline',
  concern: 'flag-outline',
  expense: 'receipt-outline',
};

function Row({ op, last }: { op: Op; last: boolean }) {
  const { retry, removeOp, captures } = useField();
  const cap = op.captureId ? captures.find((c) => c.id === op.captureId) : undefined;
  const flags = cap?.flags?.length ? `${cap.flags.length} for review` : '';
  return (
    <View style={{ paddingVertical: space[3], borderBottomWidth: last ? 0 : 1, borderBottomColor: '#ECEAE4', gap: space[2] }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[3] }}>
        <Ionicons name={ICON[op.kind] ?? 'cloud-upload-outline'} size={20} />
        <View style={{ flex: 1 }}>
          <T v="headline" style={{ fontSize: 15 }}>{op.label}</T>
          <Label>{`Saved ${clock(op.createdAt)}${op.sentAt ? ` · received ${clock(op.sentAt)}` : ''}${flags ? ` · ${flags}` : ''}`}</Label>
        </View>
        {op.state === 'sent' ? (
          <Chip tone="lime" icon="checkmark" label="Received" />
        ) : op.state === 'sending' ? (
          <Chip tone="ink" label="Sending" />
        ) : op.state === 'failed' ? (
          <Chip tone="orange" label="Needs you" />
        ) : (
          <Chip tone="paper" label="Waiting" />
        )}
      </View>
      {op.state === 'failed' && op.problem ? (
        <View style={{ gap: space[2] }}>
          <T v="footnote">{op.problem.detail}</T>
          <View style={{ flexDirection: 'row', gap: space[2] }}>
            <View style={{ flex: 1 }}>
              <Button title="Try again" variant="dark" onPress={() => retry(op.id)} />
            </View>
            <View style={{ flex: 1 }}>
              <Button title="Remove" variant="quiet" onPress={() => removeOp(op.id)} />
            </View>
          </View>
        </View>
      ) : null}
      {op.state === 'waiting' && op.problem ? <T v="footnote" muted>{`Last try: ${op.problem.code === 'offline' ? 'no signal' : op.problem.detail}`}</T> : null}
    </View>
  );
}

/**
 * Upload queue (SCR-MOB-08; FR-MOB-005, FR-MOB-008): everything saved on the
 * phone until Tenmina confirms it, in the order it is sent. Nothing is lost if
 * the app closes or the phone restarts.
 */
export default function Queue() {
  const { ops, online, syncNow } = useField();
  const open = ops.filter((o) => o.state !== 'sent');
  const sent = ops.filter((o) => o.state === 'sent').slice(-10).reverse();
  return (
    <Screen ground="paper" tabs title="Queue" trailing={<OnlineChip />}>
      {!online ? (
        <Rise>
          <Panel tone="orange" style={{ flexDirection: 'row', alignItems: 'center' }}>
            <Ionicons name="cloud-offline" size={22} color={brand.ink} />
            <T v="callout" color={brand.ink} style={{ flex: 1 }}>{`Offline. ${open.length} ${open.length === 1 ? 'item is' : 'items are'} saved on this phone and upload by themselves when you have signal.`}</T>
          </Panel>
        </Rise>
      ) : null}
      <Rise delay={60}>
        <Label style={{ marginBottom: space[2] }}>{`Waiting · ${open.length}`}</Label>
        {open.length === 0 ? (
          <Panel style={{ flexDirection: 'row', alignItems: 'center' }}>
            <Ionicons name="checkmark-circle" size={22} color={brand.ink} />
            <T v="callout" style={{ flex: 1 }}>Nothing waiting. Everything has reached Tenmina.</T>
          </Panel>
        ) : (
          <Panel style={{ gap: 0, paddingVertical: space[1] }}>
            {open.map((o, i) => (
              <Row key={o.id} op={o} last={i === open.length - 1} />
            ))}
          </Panel>
        )}
      </Rise>
      {open.length && online ? <Button title="Send now" variant="dark" icon="cloud-upload-outline" onPress={() => void syncNow()} /> : null}
      {sent.length ? (
        <Rise delay={120}>
          <Label style={{ marginBottom: space[2] }}>Received by Tenmina</Label>
          <Panel style={{ gap: 0, paddingVertical: space[1] }}>
            {sent.map((o, i) => (
              <Row key={o.id} op={o} last={i === sent.length - 1} />
            ))}
          </Panel>
        </Rise>
      ) : null}
      <T v="footnote" muted>{`Items stay on this phone, even if the app is closed or the phone restarts, until Tenmina confirms it has them. Photos are deleted from the phone once stored.`}</T>
    </Screen>
  );
}
