import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { ApiProvider } from '../data';
import { usePalette } from '../theme';

export default function RootLayout() {
  const p = usePalette();
  const sheet = {
    presentation: 'formSheet' as const,
    sheetAllowedDetents: [0.92],
    sheetGrabberVisible: true,
    sheetCornerRadius: 28,
    headerShown: false,
    contentStyle: { backgroundColor: p.bg },
  };
  return (
    <ApiProvider>
      <StatusBar style="auto" />
      <Stack
        screenOptions={{
          headerShadowVisible: false,
          headerStyle: { backgroundColor: p.bg },
          headerTintColor: p.primary,
          headerTitleStyle: { color: p.text },
          headerBackButtonDisplayMode: 'minimal',
          contentStyle: { backgroundColor: p.bg },
        }}
      >
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen name="case/[id]" options={{ title: '' }} />
        <Stack.Screen name="report/[id]" options={{ title: 'Report' }} />
        <Stack.Screen name="escrow/[id]" options={sheet} />
        <Stack.Screen name="invoice/[id]" options={sheet} />
        <Stack.Screen name="account/delete" options={{ title: 'Delete account' }} />
      </Stack>
    </ApiProvider>
  );
}
