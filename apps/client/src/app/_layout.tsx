import { useEffect } from 'react';
import { Stack, SplashScreen } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { brand } from '@tenmina/tokens';
import { useBlocFonts } from '@tenmina/ui';
import { ApiProvider, SessionProvider } from '../data';

void SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  const ready = useBlocFonts();

  useEffect(() => {
    if (ready) void SplashScreen.hideAsync();
  }, [ready]);

  if (!ready) return null;

  // Approvals open as sheets on a black ground; everything else draws its own header.
  const sheet = {
    presentation: 'formSheet' as const,
    sheetAllowedDetents: [0.96],
    sheetGrabberVisible: true,
    sheetCornerRadius: 28,
    contentStyle: { backgroundColor: brand.ink },
  };
  return (
    <SessionProvider>
      <ApiProvider>
        <StatusBar style="auto" />
        <Stack screenOptions={{ headerShown: false }}>
          <Stack.Screen name="(tabs)" />
          <Stack.Screen name="welcome" options={{ animation: 'fade' }} />
          <Stack.Screen name="case/[id]" />
          <Stack.Screen name="report/[id]" />
          <Stack.Screen name="escrow/[id]" options={sheet} />
          <Stack.Screen name="invoice/[id]" options={sheet} />
          <Stack.Screen name="account/delete" />
        </Stack>
      </ApiProvider>
    </SessionProvider>
  );
}
