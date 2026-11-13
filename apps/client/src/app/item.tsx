import * as WebBrowser from 'expo-web-browser';
import { useLocalSearchParams } from 'expo-router';
import { Button, Panel, Screen, T } from '@tenmina/ui';
import { portalUrl } from '@tenmina/mobile';

/**
 * Anything the app has no screen for yet (listings, reservations, partner
 * requests, ratings): what it is and where it stands, with a link to the same
 * page on the website. Opening it never approves anything.
 */
export default function Item() {
  const { link, title, detail } = useLocalSearchParams<{ link: string; title?: string; detail?: string }>();
  return (
    <Screen ground="paper" back title={title || 'Details'} footer={<Button title="Open on the Tenmina website" icon="open-outline" onPress={() => void WebBrowser.openBrowserAsync(`${portalUrl()}${link ?? ''}`)} />}>
      <Panel>
        <T v="callout">{detail || 'See the details on the website.'}</T>
      </Panel>
    </Screen>
  );
}
