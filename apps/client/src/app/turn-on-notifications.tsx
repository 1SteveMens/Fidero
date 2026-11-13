import { useState } from 'react';
import { View } from 'react-native';
import { router } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, space } from '@tenmina/tokens';
import { Button, Panel, Screen, T } from '@tenmina/ui';
import { ProblemBox, registerPush, setPushChoice, toProblem, useApi, type Problem } from '@tenmina/mobile';

const ABOUT = [
  ['hand-left-outline', 'Something needs you: an approval, a document or a code'],
  ['git-commit-outline', 'Your case, escrow or bill moves on'],
  ['lock-closed-outline', 'Never amounts or report findings on the lock screen'],
] as const;

/**
 * Turn on notifications? (SCR-APP-01, W-37; FR-APP-002, FR-NTF-004). Explains
 * first, then asks. If the answer is no, the app never asks again by itself.
 */
export default function TurnOnNotifications() {
  const api = useApi();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem>();

  async function on() {
    setBusy(true);
    try {
      await registerPush(api);
      await setPushChoice('on');
      router.replace('/');
    } catch (e) {
      setProblem(toProblem(e));
    }
    setBusy(false);
  }

  return (
    <Screen
      ground="ink"
      footer={
        <>
          <Button title="Turn on" icon="notifications" loading={busy} onPress={() => void on()} />
          <Button
            title="Not now"
            variant="quiet"
            onPress={() => {
              void setPushChoice('off');
              router.replace('/');
            }}
          />
        </>
      }
    >
      <View style={{ paddingTop: space[7], gap: space[4] }}>
        <View style={{ width: 72, height: 72, borderRadius: 22, backgroundColor: brand.lime, alignItems: 'center', justifyContent: 'center' }}>
          <Ionicons name="notifications" size={34} color={brand.ink} />
        </View>
        <T v="display" header>Know when something needs you</T>
        <Panel style={{ gap: space[3] }}>
          {ABOUT.map(([icon, text]) => (
            <View key={text} style={{ flexDirection: 'row', gap: space[3], alignItems: 'center' }}>
              <Ionicons name={icon} size={22} color={brand.lime} />
              <T v="callout" style={{ flex: 1 }}>{text}</T>
            </View>
          ))}
        </Panel>
        <T v="footnote" muted>You can change channels any time in Account. Opening a notification never approves anything.</T>
        <ProblemBox problem={problem} />
      </View>
    </Screen>
  );
}
