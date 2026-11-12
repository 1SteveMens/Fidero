import { Text, View } from 'react-native';
import { router } from 'expo-router';
import { formatMoney, type HomeRow } from '@fidero/shared';
import { hero, space, type } from '@fidero/tokens';
import { ErrorView, Hero, Loading, Pill, Row, Screen, SectionHeader, VerdictPill } from '../../components/ui';
import { useLoad } from '../../data';
import { usePalette } from '../../theme';

function RowList({ rows, icon }: { rows: HomeRow[]; icon: 'business' | 'heart' | 'document-text' }) {
  return (
    <View style={{ gap: space[3] }}>
      {rows.map((r) => (
        <Row
          key={r.id}
          icon={icon}
          tone="neutral"
          title={r.title}
          detail={r.detail}
          onPress={r.href ? () => router.push(r.href as never) : undefined}
          trailing={r.badge?.verdict ? <VerdictPill verdict={r.badge.verdict} /> : undefined}
        />
      ))}
    </View>
  );
}

export default function Home() {
  const p = usePalette();
  const { data, error, reload } = useLoad((api) => api.getDashboard(), 'dashboard');

  return (
    <Screen subtitle="Ghana · GHS" title={data ? `Hello, ${data.firstName}` : 'Hello'}>
      {error ? <ErrorView message={error} onRetry={reload} /> : null}
      {!data && !error ? <Loading /> : null}
      {data ? (
        <>
          <Hero>
            <Text style={[type.footnote, { color: hero.textMuted, fontWeight: '600' }]}>Held for you at {data.heldAt}</Text>
            <Text style={[type.amount, { color: hero.text, fontVariant: ['tabular-nums'], letterSpacing: -1 }]}>{formatMoney(data.held)}</Text>
            <Text style={[type.callout, { color: hero.textMuted }]}>
              Fidero never holds your money. The bank pays only after you and two Fidero staff approve.
            </Text>
          </Hero>

          {data.needsYou.length > 0 ? (
            <>
              <SectionHeader title="Needs you" count={data.needsYou.length} />
              <View style={{ gap: space[3] }}>
                {data.needsYou.map((n) => (
                  <Row key={n.id} icon="hand-left" tone="primary" title={n.title} detail={n.detail} onPress={() => router.push(n.href as never)} />
                ))}
              </View>
            </>
          ) : (
            <View style={{ alignItems: 'flex-start', gap: space[2] }}>
              <Pill label="Nothing needs you right now" tone="success" icon="checkmark-circle" />
            </View>
          )}

          <SectionHeader title="Property" />
          <RowList rows={data.property} icon="business" />

          <SectionHeader title="Family" />
          <RowList rows={data.family} icon="heart" />

          <SectionHeader title="Projects and errands" />
          <RowList rows={data.projects} icon="document-text" />

          <Text style={[type.footnote, { color: p.textMuted, textAlign: 'center' }]}>Sample data for the demo build.</Text>
        </>
      ) : null}
    </Screen>
  );
}
