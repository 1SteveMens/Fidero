import { useEffect } from 'react';
import { Stack, SplashScreen } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { brand } from '@tenmina/tokens';
import { useBlocFonts } from '@tenmina/ui';
import { FieldProvider } from '../store';

void SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  const ready = useBlocFonts();
  useEffect(() => {
    if (ready) void SplashScreen.hideAsync();
  }, [ready]);
  if (!ready) return null;
  return (
    <FieldProvider>
      <StatusBar style="auto" />
      <Stack screenOptions={{ headerShown: false }}>
        <Stack.Screen name="(tabs)" />
        <Stack.Screen name="welcome" options={{ animation: 'fade' }} />
        <Stack.Screen name="job/[id]" />
        <Stack.Screen name="capture" options={{ presentation: 'fullScreenModal', contentStyle: { backgroundColor: brand.ink } }} />
      </Stack>
    </FieldProvider>
  );
}
