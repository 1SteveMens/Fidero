import { useEffect, useState } from 'react';
import { Image, View } from 'react-native';
import Ionicons from '@expo/vector-icons/Ionicons';
import { radius } from '@tenmina/tokens';
import { usePalette } from '@tenmina/ui';
import { apiBaseUrl, useApi } from '@tenmina/mobile';

/** A photo from the evidence store, through a short-lived signed link (FR-EVD-003). */
export function EvidenceThumb({ id, size = 132, label }: { id: string; size?: number; label: string }) {
  const api = useApi();
  const p = usePalette();
  const [uri, setUri] = useState<string>();
  useEffect(() => {
    let live = true;
    api
      .get<{ url: string }>(`/v1/evidence/${id}/link`, { variant: 'preview' })
      .then((r) => live && setUri(r.url.startsWith('http') ? r.url : `${apiBaseUrl()}${r.url}`))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [api, id]);
  return (
    <View style={{ width: size, height: size, borderRadius: radius.md, backgroundColor: p.surface, overflow: 'hidden', alignItems: 'center', justifyContent: 'center' }}>
      {uri ? <Image source={{ uri }} style={{ width: size, height: size }} accessibilityLabel={label} /> : <Ionicons name="image-outline" size={28} color={p.textMuted} />}
    </View>
  );
}
