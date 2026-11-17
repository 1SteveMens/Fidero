import { View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { space } from '@tenmina/tokens';
import { Button, Label, Panel, Screen, T, usePalette } from '@tenmina/ui';

/**
 * Anything the app shows only as a summary (a partner request, a rating, a
 * monitoring alert): what it is and where it stands. It stays in the app: the
 * full record sits with the case, escrow or project it belongs to, and Tenmina
 * tells you on the home screen when it needs you. Opening it never approves
 * anything.
 */
export default function Item() {
  const p = usePalette();
  const { link, title, detail } = useLocalSearchParams<{ link: string; title?: string; detail?: string }>();
  const where = (link ?? '').split('?')[0].split('/').filter(Boolean)[0] ?? '';
  return (
    <Screen ground="paper" back title={title || 'Details'} footer={<Button title="Back to home" variant="dark" onPress={() => router.replace('/')} />}>
      <Panel>
        {where ? <Label>{where.replace(/[-_]/g, ' ')}</Label> : null}
        <T v="callout">{detail || 'Nothing needs you on this right now.'}</T>
      </Panel>
      <View style={{ flexDirection: 'row', gap: space[3] }}>
        <Ionicons name="notifications-outline" size={18} color={p.text} />
        <T v="footnote" muted style={{ flex: 1 }}>When this needs you, it comes first on your home screen and in your inbox.</T>
      </View>
    </Screen>
  );
}
