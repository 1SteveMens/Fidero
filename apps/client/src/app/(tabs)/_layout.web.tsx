import type { ColorValue } from 'react-native';
import { Tabs } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { usePalette } from '../../theme';

/**
 * Web preview only. Native builds use NativeTabs in _layout.tsx (Liquid Glass on
 * iOS, Material 3 on Android); the web fallback of NativeTabs draws a top strip,
 * so the preview uses a bottom bar that looks like the phone.
 */
export default function WebTabsLayout() {
  const p = usePalette();
  const icon =
    (name: keyof typeof Ionicons.glyphMap) =>
    ({ color, focused }: { color: ColorValue; focused: boolean }) => (
      <Ionicons name={(focused ? name : `${name}-outline`) as keyof typeof Ionicons.glyphMap} size={24} color={color as string} />
    );
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: p.primary,
        tabBarInactiveTintColor: p.textMuted,
        tabBarStyle: {
          position: 'absolute',
          left: 16,
          right: 16,
          bottom: 16,
          height: 64,
          borderRadius: 32,
          borderTopWidth: 0,
          backgroundColor: p.surface,
          shadowColor: '#000',
          shadowOpacity: 0.12,
          shadowRadius: 20,
          paddingTop: 6,
        },
        tabBarLabelStyle: { fontSize: 11, fontWeight: '600' },
      }}
    >
      <Tabs.Screen name="index" options={{ title: 'Home', tabBarIcon: icon('home') }} />
      <Tabs.Screen name="property" options={{ title: 'Property', tabBarIcon: icon('business') }} />
      <Tabs.Screen name="family" options={{ title: 'Family', tabBarIcon: icon('people') }} />
      <Tabs.Screen name="projects" options={{ title: 'Projects', tabBarIcon: icon('checkbox') }} />
      <Tabs.Screen name="account" options={{ title: 'Account', tabBarIcon: icon('person-circle') }} />
    </Tabs>
  );
}
