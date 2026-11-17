import { useEffect } from 'react';
import { Stack, SplashScreen } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { brand } from '@tenmina/tokens';
import { useBlocFonts } from '@tenmina/ui';
import { SessionProvider, StartingScreen, UpdateRequiredScreen, useSession } from '@tenmina/mobile';
import { FieldProvider, useField } from '../store';

void SplashScreen.preventAutoHideAsync();

function Root() {
  const { status, update } = useSession();
  const { ops } = useField();
  useEffect(() => {
    // The starting screen is visible from the first render, so the splash can go at once.
    void SplashScreen.hideAsync();
  }, [status]);
  if (status === 'loading') return <StartingScreen />;
  // SCR-APP-05: too old to use. Saved items stay on the phone and upload after the update.
  if (update) return <UpdateRequiredScreen info={update} savedItems={ops.filter((o) => o.state !== 'sent').length} />;
  return (
    <>
      <StatusBar style="auto" />
      <Stack screenOptions={{ headerShown: false }}>
        <Stack.Screen name="(tabs)" />
        <Stack.Screen name="welcome" options={{ animation: 'fade' }} />
        <Stack.Screen name="capture" options={{ presentation: 'fullScreenModal', contentStyle: { backgroundColor: brand.ink } }} />
      </Stack>
    </>
  );
}

export default function RootLayout() {
  const ready = useBlocFonts();
  if (!ready) return null;
  return (
    <SessionProvider app="field">
      <FieldProvider>
        <Root />
      </FieldProvider>
    </SessionProvider>
  );
}
