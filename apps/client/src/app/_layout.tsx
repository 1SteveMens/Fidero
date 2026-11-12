import { useEffect } from 'react';
import { Stack, SplashScreen } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useFonts } from 'expo-font';
import {
  BricolageGrotesque_400Regular,
  BricolageGrotesque_600SemiBold,
  BricolageGrotesque_700Bold,
  BricolageGrotesque_800ExtraBold,
} from '@expo-google-fonts/bricolage-grotesque';
import { IBMPlexMono_500Medium, IBMPlexMono_600SemiBold } from '@expo-google-fonts/ibm-plex-mono';
import { brand } from '@fidero/tokens';
import { ApiProvider, SessionProvider } from '../data';

void SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  const [loaded, failed] = useFonts({
    BricolageGrotesque_400Regular,
    BricolageGrotesque_600SemiBold,
    BricolageGrotesque_700Bold,
    BricolageGrotesque_800ExtraBold,
    IBMPlexMono_500Medium,
    IBMPlexMono_600SemiBold,
  });

  useEffect(() => {
    if (loaded || failed) void SplashScreen.hideAsync();
  }, [loaded, failed]);

  if (!loaded && !failed) return null;

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
