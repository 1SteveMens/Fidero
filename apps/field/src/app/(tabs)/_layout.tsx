import { Redirect, Tabs } from 'expo-router';
import { TabBar } from '@fidero/ui';
import { useField } from '../../store';

const ICONS = { index: 'list', queue: 'cloud-upload', pay: 'cash', account: 'person-circle' } as const;

/** Fidero Field tabs (03 section 2.4a): Jobs, Queue with a count, Pay, Account. */
export default function TabsLayout() {
  const { role, queue } = useField();
  if (!role) return <Redirect href="/welcome" />;
  const waiting = queue.filter((q) => q.state !== 'sent').length;
  return (
    <Tabs tabBar={(props) => <TabBar {...props} icons={ICONS} badges={{ queue: waiting || undefined }} />} screenOptions={{ headerShown: false }}>
      <Tabs.Screen name="index" options={{ title: 'Jobs' }} />
      <Tabs.Screen name="queue" options={{ title: 'Queue' }} />
      <Tabs.Screen name="pay" options={{ title: 'Pay' }} />
      <Tabs.Screen name="account" options={{ title: 'Account' }} />
    </Tabs>
  );
}
