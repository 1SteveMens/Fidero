import { useState } from 'react';
import { Image, ScrollView, View, useWindowDimensions } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, radius, space } from '@tenmina/tokens';
import { Button, Chip, Label, Panel, Screen, T, VerdictChip } from '@tenmina/ui';
import { Field, KV, LoadState, ProblemBox, Section, apiBaseUrl, day, money, useAction, useGet, words } from '@tenmina/mobile';
import type { Listing } from '../listings';

interface ListingReport {
  report_id: string;
  reference: string;
  verdict: 'green' | 'amber' | 'red' | null;
  released_at: string | null;
  pdf_sha256: string;
  sections: { number: number; label: string; title: string; verdict: string | null; findings: string }[];
}

/**
 * One verified listing in the app (SCR-PTL-21, FR-LST-003, FR-LST-005): photos,
 * price, the badge with its check date, the full report behind it, a question
 * to the seller, and reserving, which starts a fresh search and proposes a bank
 * escrow. Nothing is paid here.
 */
export default function ListingScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { width } = useWindowDimensions();
  const l = useGet<Listing>(`/v1/listings/${id}`);
  const d = l.data;
  // RUL-14: anyone signed in while the badge is valid; the buyer who reserved it keeps the report after that.
  const report = useGet<ListingReport>(d?.can_read_report ? `/v1/listings/${id}/report` : null);
  const act = useAction();
  const [question, setQuestion] = useState('');
  const [asked, setAsked] = useState(false);
  const photos = (d?.media ?? []).filter((m) => m.kind === 'photo' && m.url);
  const w = width - space[5] * 2;

  async function ask() {
    const r = await act.run('POST', `/v1/listings/${id}/enquiries`, { message: question.trim() });
    if (r) {
      setQuestion('');
      setAsked(true);
    }
  }
  async function reserve() {
    const r = await act.run<{ id: string; escrow: string | null }>('POST', `/v1/listings/${id}/reservations`, {}, { idempotencyKey: `reserve-${id}` });
    if (r) {
      l.reload();
      if (r.escrow) router.push(`/escrow/${r.escrow}`);
    }
  }

  return (
    <Screen ground="paper" back eyebrow={d?.reference ?? 'Listing'} title={d?.title}>
      <LoadState loading={l.loading} problem={l.problem} onRetry={l.reload} hasData={!!d} />
      {d ? (
        <>
          {photos.length ? (
            <ScrollView horizontal pagingEnabled showsHorizontalScrollIndicator={false}>
              {photos.map((m) => (
                <View key={m.id} style={{ width: w }}>
                  <Image source={{ uri: `${apiBaseUrl()}${m.url}` }} style={{ width: w, aspectRatio: 4 / 3, borderRadius: radius.xl, backgroundColor: '#E9E6DF' }} accessibilityLabel={m.caption || `Photo of ${d.title}`} />
                  {m.caption ? <T v="footnote" muted style={{ marginTop: 4, paddingHorizontal: 2 }}>{m.caption}</T> : null}
                </View>
              ))}
            </ScrollView>
          ) : null}
          <View style={{ flexDirection: 'row', gap: space[2], flexWrap: 'wrap' }}>
            {d.badge ? <Chip label="Tenmina Verified" tone="lime" icon="checkmark" /> : <Chip label={words(d.status)} tone="paper" />}
            {d.reserved ? <Chip label="Reserved" tone="paper" /> : null}
          </View>
          <T v="amount" style={{ fontSize: 30, lineHeight: 36 }}>{money(d.price)}</T>
          {d.description ? <T v="callout">{d.description}</T> : null}
          <KV
            rows={[
              ['Kind', words(d.kind)],
              ['Where', [d.estate_name, d.locality, d.district].filter((v, i, all) => v && all.indexOf(v) === i && !(i > 0 && all[0] && v.startsWith(all[0]))).join(', ') || '—'],
              ['Size', d.size_sqm ? `${Number(d.size_sqm).toLocaleString('en-GB')} m²` : '—'],
              ['Seller', `${d.seller.name}${d.seller.established ? ' · established' : ''}`],
              ['Checked', d.badge ? day(d.badge.checks_date) : '—'],
            ]}
          />
          {d.disclosure ? <T v="footnote" muted>{d.disclosure}</T> : null}

          {report.data ? (
            <Section title={`Tenmina's report · ${report.data.reference}`}>
              <Panel style={{ gap: space[2] }}>
                {report.data.verdict ? <VerdictChip verdict={report.data.verdict} suffix="verdict" /> : null}
                {report.data.sections.slice(0, 4).map((s) => (
                  <View key={s.number} style={{ gap: 2 }}>
                    <Label>{`${s.label}. ${s.title}`}</Label>
                    {s.findings ? <T v="footnote">{s.findings}</T> : null}
                  </View>
                ))}
                <Button title="Read the full report" icon="document-text-outline" variant="dark" onPress={() => router.push({ pathname: '/file/[id]', params: { id, from: 'listing', name: `Report ${report.data?.reference ?? ''}`, type: 'application/pdf' } })} />
              </Panel>
            </Section>
          ) : null}

          {d.can_reserve ? (
            <Panel tone="raised" style={{ gap: space[2] }}>
              <View style={{ flexDirection: 'row', gap: space[2], alignItems: 'center' }}>
                <Ionicons name="lock-closed" size={18} color={brand.lime} />
                <T v="headline" style={{ flex: 1 }}>Reserve it</T>
              </View>
              <T v="footnote" muted>Tenmina runs a fresh official search and proposes a bank escrow. You pay nothing now. The seller is paid by the bank only after the conditions are met.</T>
              <Button title="Reserve this listing" loading={act.busy} onPress={() => void reserve()} />
            </Panel>
          ) : null}

          <Section title="Ask about it">
            {asked ? <T v="callout">Sent. The answer comes to your inbox.</T> : null}
            <Field label="Your question" value={question} onChange={setQuestion} multiline hint="Tenmina passes it to the seller. Never pay anyone directly." />
            <Button title="Send the question" variant="dark" disabled={question.trim().length < 5} loading={act.busy} onPress={() => void ask()} />
          </Section>
          <ProblemBox problem={act.problem} />
        </>
      ) : null}
    </Screen>
  );
}
