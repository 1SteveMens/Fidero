import { Redirect, Tabs } from 'expo-router';
import { TabBar } from '@tenmina/ui';
import { useSession } from '@tenmina/mobile';
import { useField } from '../../store';

const ICONS = { index: 'list', queue: 'cloud-upload', pay: 'cash', account: 'person-circle' } as const;

/** Tenmina Field tabs (03 section 2.4a): Jobs, Queue with a count, Pay, Account. */
export default function TabsLayout() {
  const { status } = useSession();
  const { device, ops } = useField();
  if (status !== 'signedIn' || !device) return <Redirect href="/welcome" />;
  const waiting = ops.filter((o) => o.state !== 'sent').length;
  return (
    <Tabs tabBar={(props) => <TabBar {...props} icons={ICONS} badges={{ queue: waiting || undefined }} />} screenOptions={{ headerShown: false }}>
      <Tabs.Screen name="index" options={{ title: 'Jobs' }} />
      <Tabs.Screen name="queue" options={{ title: 'Queue' }} />
      <Tabs.Screen name="pay" options={{ title: 'Pay' }} />
      <Tabs.Screen name="account" options={{ title: 'Account' }} />
    </Tabs>
  );
}
