import { Redirect, Tabs } from 'expo-router';
import { TabBar } from '@tenmina/ui';
import { useSession } from '@tenmina/mobile';

const ICONS = { index: 'home', property: 'business', family: 'people', projects: 'checkbox', account: 'person-circle' } as const;

/** Tabs match the portal (docs/specs/03 2.4): Home, Property, Family, Projects, Account. */
export default function TabsLayout() {
  const { status } = useSession();
  if (status !== 'signedIn') return <Redirect href="/welcome" />;
  return (
    <Tabs tabBar={(props) => <TabBar {...props} icons={ICONS} />} screenOptions={{ headerShown: false }}>
      <Tabs.Screen name="index" options={{ title: 'Home' }} />
      <Tabs.Screen name="property" options={{ title: 'Property' }} />
      <Tabs.Screen name="family" options={{ title: 'Family' }} />
      <Tabs.Screen name="projects" options={{ title: 'Projects' }} />
      <Tabs.Screen name="account" options={{ title: 'Account' }} />
    </Tabs>
  );
}
