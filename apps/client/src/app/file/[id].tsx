import { createElement, useEffect, useState } from 'react';
import { Image, Platform, ScrollView, View, useWindowDimensions } from 'react-native';
import { useLocalSearchParams } from 'expo-router';
import { WebView } from 'react-native-webview';
import * as Sharing from 'expo-sharing';
import { File as FsFile, Paths } from 'expo-file-system';
import { brand, radius, space } from '@tenmina/tokens';
import { Button, Label, Screen, T } from '@tenmina/ui';
import { LoadState, ProblemBox, apiBaseUrl, toProblem, useApi, type Problem } from '@tenmina/mobile';

interface Link {
  url: string;
  content_type?: string;
  expires_at?: string;
  sha256?: string;
}

function absolute(url: string) {
  return url.startsWith('http') ? url : `${apiBaseUrl()}${url}`;
}

function safeName(name: string, type: string) {
  const base = (name || 'tenmina-file').replace(/[^\w.-]+/g, '-').slice(0, 80);
  if (/\.[a-z0-9]{2,4}$/i.test(base)) return base;
  return `${base}${type === 'application/pdf' ? '.pdf' : type.startsWith('image/') ? '.jpg' : ''}`;
}

/**
 * A stored file inside the app (FR-EVD-003): a short-lived signed link, then a
 * photo full screen (pinch to zoom on iPhone) or a PDF in the reader. "Share or
 * save" downloads the file to the phone and opens the share sheet. Nothing
 * opens the website. `from=report` opens a released report's sealed PDF.
 */
export default function FileScreen() {
  const api = useApi();
  const { id, name, type, from } = useLocalSearchParams<{ id: string; name?: string; type?: string; from?: string }>();
  const { width, height } = useWindowDimensions();
  const [link, setLink] = useState<Link>();
  const [problem, setProblem] = useState<Problem>();
  const [tick, setTick] = useState(0);
  const [sharing, setSharing] = useState(false);
  const [shareProblem, setShareProblem] = useState<Problem>();

  useEffect(() => {
    let live = true;
    setProblem(undefined);
    const get =
      from === 'report'
        ? api.get<Link>(`/v1/reports/${id}/pdf`)
        : from === 'listing'
          ? api.get<{ pdf: Link | null; pdf_sha256: string }>(`/v1/listings/${id}/report`).then((r) => {
              if (!r.pdf) throw new Error('This report has no PDF yet.');
              return { ...r.pdf, sha256: r.pdf_sha256 };
            })
          : api.get<Link>(`/v1/evidence/${id}/link`, { variant: 'original' });
    get.then((l) => live && setLink(l)).catch((e: unknown) => live && setProblem(toProblem(e)));
    return () => {
      live = false;
    };
  }, [api, id, from, tick]);

  const ct = link?.content_type || type || '';
  const isImage = ct.startsWith('image/');
  const isPdf = ct === 'application/pdf' || from === 'report' || from === 'listing';
  const url = link ? absolute(link.url) : '';
  const title = name || (from === 'report' || from === 'listing' ? 'Report PDF' : isImage ? 'Photo' : 'Document');

  async function share() {
    if (!url) return;
    setShareProblem(undefined);
    if (Platform.OS === 'web') {
      const a = document.createElement('a');
      a.href = url;
      a.download = safeName(title, ct);
      a.click();
      return;
    }
    setSharing(true);
    try {
      const dest = new FsFile(Paths.cache, safeName(title, ct));
      const file = await FsFile.downloadFileAsync(url, dest, { idempotent: true });
      if (!(await Sharing.isAvailableAsync())) throw new Error('Sharing is not available on this phone.');
      await Sharing.shareAsync(file.uri, { mimeType: ct || undefined, dialogTitle: title, UTI: isPdf ? 'com.adobe.pdf' : isImage ? 'public.jpeg' : undefined });
    } catch (e) {
      setShareProblem(toProblem(e));
      // A signed link lasts minutes: get a fresh one for the next try.
      setTick((t) => t + 1);
    } finally {
      setSharing(false);
    }
  }

  const viewerHeight = Math.max(420, height - 260);

  return (
    <Screen
      ground="ink"
      back
      title={title}
      footer={link ? <Button title="Share or save" icon="share-outline" variant="dark" loading={sharing} onPress={() => void share()} /> : undefined}
    >
      <LoadState loading={!link && !problem} problem={problem} onRetry={() => setTick((t) => t + 1)} hasData={!!link} />
      {link && isImage ? (
        <ScrollView
          style={{ height: viewerHeight, borderRadius: radius.lg, backgroundColor: '#000' }}
          contentContainerStyle={{ flexGrow: 1, alignItems: 'center', justifyContent: 'center' }}
          maximumZoomScale={4}
          minimumZoomScale={1}
          centerContent
          showsHorizontalScrollIndicator={false}
          showsVerticalScrollIndicator={false}
        >
          <Image source={{ uri: url }} style={{ width: width - space[5] * 2, height: viewerHeight }} resizeMode="contain" accessibilityLabel={title} />
        </ScrollView>
      ) : null}
      {link && isPdf ? (
        <View style={{ height: viewerHeight, borderRadius: radius.lg, overflow: 'hidden', backgroundColor: brand.paper }}>
          {Platform.OS === 'web' ? (
            createElement('iframe', { src: url, title, style: { border: 0, width: '100%', height: '100%', background: '#fff' } })
          ) : Platform.OS === 'ios' ? (
            <WebView source={{ uri: url }} style={{ flex: 1 }} originWhitelist={['*']} startInLoadingState accessibilityLabel={title} />
          ) : (
            <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', padding: space[5], gap: space[3] }}>
              <T v="headline" color={brand.ink}>Open it with Share or save</T>
              <T v="callout" color={brand.ink}>This phone reads PDFs in another app. The file stays sealed: its fingerprint does not change.</T>
            </View>
          )}
        </View>
      ) : null}
      {link && !isImage && !isPdf ? (
        <View style={{ gap: space[2] }}>
          <T v="headline">This file opens in another app</T>
          <T v="callout" muted>Use Share or save to open it.</T>
        </View>
      ) : null}
      {link?.sha256 ? <Label>{`Sealed · ${link.sha256.slice(0, 12)}`}</Label> : null}
      <ProblemBox problem={shareProblem} />
    </Screen>
  );
}
