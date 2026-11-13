import { useEffect } from 'react';
import { Redirect, Stack, SplashScreen, useSegments } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { brand } from '@tenmina/tokens';
import { useBlocFonts } from '@tenmina/ui';
import { SessionProvider, UpdateRequiredScreen, useSession } from '@tenmina/mobile';

void SplashScreen.preventAutoHideAsync();

/** Approvals open as sheets on a black ground; everything else draws its own header. */
const sheet = {
  presentation: 'formSheet' as const,
  sheetAllowedDetents: [0.96],
  sheetGrabberVisible: true,
  sheetCornerRadius: 28,
  contentStyle: { backgroundColor: brand.ink },
};

/** Screens that work signed out. Every other link waits for sign-in; it never approves anything by itself. */
const PUBLIC = ['welcome', 'sign-in', 'sign-up'];

function Root() {
  const { status, update } = useSession();
  const segments = useSegments();
  useEffect(() => {
    if (status !== 'loading') void SplashScreen.hideAsync();
  }, [status]);
  if (status === 'loading') return null;
  // SCR-APP-05: an app below the minimum version shows only this (FR-APP-006).
  if (update) return <UpdateRequiredScreen info={update} />;
  const first = segments[0] as string | undefined;
  return (
    <>
      {status === 'signedOut' && first && !PUBLIC.includes(first) && first !== '(tabs)' ? <Redirect href="/welcome" /> : null}
      <StatusBar style="auto" />
      <Stack screenOptions={{ headerShown: false }}>
        <Stack.Screen name="(tabs)" />
        <Stack.Screen name="welcome" options={{ animation: 'fade' }} />
        <Stack.Screen name="release/[id]" options={sheet} />
        <Stack.Screen name="invoice/[id]" options={sheet} />
        <Stack.Screen name="payee-change/[id]" options={sheet} />
      </Stack>
    </>
  );
}

export default function RootLayout() {
  const ready = useBlocFonts();
  if (!ready) return null;
  return (
    <SessionProvider app="client">
      <Root />
    </SessionProvider>
  );
}
