import { View, useWindowDimensions } from 'react-native';
import { router } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { brand, font, radius, space } from '@tenmina/tokens';
import { Mark } from '@tenmina/ui';
import { Seal } from '@tenmina/ui';
import { Button, Label, Pulse, Rise, T } from '@tenmina/ui';
import { useSession } from '../data';
import { GroundContext } from '@tenmina/ui';

/**
 * First screen. The lime block with the seal stands in for the photograph in the
 * mockup until Tenmina has a licensed image for the app and the store pages.
 */
export default function Welcome() {
  const { signIn } = useSession();
  const insets = useSafeAreaInsets();
  const { height } = useWindowDimensions();
  const start = () => {
    signIn();
    router.replace('/');
  };
  return (
    <GroundContext.Provider value="ink">
      <View style={{ flex: 1, backgroundColor: brand.ink, paddingTop: insets.top + space[3], paddingBottom: insets.bottom + space[4], paddingHorizontal: space[6] }}>
        <Rise style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: space[2] }}>
            <Mark />
            <T v="title" color="#F7F6F2" style={{ fontFamily: font.heavy, letterSpacing: -1 }}>tenmina</T>
          </View>
        </Rise>

        <Rise delay={120} style={{ flex: 1, justifyContent: 'center', paddingVertical: space[5] }}>
          <View style={{ height: Math.min(340, height * 0.38), borderRadius: radius.xl + 8, backgroundColor: brand.lime, alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }}>
            <Seal id="welcome-seal" ring="#86C94A" text="#3F5A1F" check={brand.ink} size={Math.min(240, height * 0.27)} />
            <View style={{ position: 'absolute', left: space[4], bottom: space[4], backgroundColor: brand.ink, borderRadius: radius.md, paddingHorizontal: space[3], paddingVertical: space[2] }}>
              <Label color={brand.lime}>Released only on proof</Label>
            </View>
          </View>
        </Rise>

        <Rise delay={260} style={{ flexDirection: 'row', alignItems: 'center', gap: space[2] }}>
          <Pulse size={8} radius={4} color={brand.lime} />
          <Label color={brand.lime}>For Ghanaians abroad</Label>
        </Rise>
        <Rise delay={340}>
          <T v="display" header color="#F7F6F2" style={{ fontSize: 52, lineHeight: 52, letterSpacing: -2.3, marginTop: space[2] }}>
            Your agent{'\n'}at <T v="display" color={brand.lime} style={{ fontSize: 52, lineHeight: 52, letterSpacing: -2.3 }}>home.</T>
          </T>
        </Rise>
        <Rise delay={420}>
          <T v="body" muted style={{ marginTop: space[3], marginBottom: space[5] }}>
            Buy, build and pay in Ghana from anywhere. Every cedi checked and shown to you.
          </T>
        </Rise>
        <Rise delay={500} style={{ gap: space[1] }}>
          <Button title="Get started" icon="arrow-forward" onPress={start} />
          <Button title="I already have an account" variant="quiet" onPress={start} />
        </Rise>
      </View>
    </GroundContext.Provider>
  );
}
