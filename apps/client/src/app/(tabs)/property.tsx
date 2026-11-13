import { Linking, View } from 'react-native';
import { router } from 'expo-router';
import { space } from '@tenmina/tokens';
import { IconButton, Rise, Screen, T } from '@tenmina/ui';
import { LoadState, Section, portalUrl } from '@tenmina/mobile';
import { ItemList, NeedsYouList, StartTile, useHome } from '../../components/rows';

const CASES = ['case', 'report', 'partner_order'];
const MONEY = ['escrow', 'held_funds', 'release_approval', 'bank_account'];
const LISTINGS = ['listing_reservation', 'listing_enquiry'];

/** Property (03 2.3a): orders and cases, reports, escrows and listings, in one place. */
export default function Property() {
  const home = useHome();
  const items = (home.data?.items ?? []).filter((i) => ['property', 'escrow', 'listings', ''].includes(i.line) && !i.family_member_id);
  const needs = items.filter((i) => i.needs_action);
  const rest = items.filter((i) => !i.needs_action);

  return (
    <Screen ground="paper" tabs title="Property" trailing={<IconButton icon="add" tone="lime" label="Check a plot or a house" onPress={() => router.push('/order')} />}>
      <LoadState loading={home.loading} problem={home.problem} onRetry={home.reload} hasData={!!home.data} />
      {home.data ? (
        <>
          <Rise>
            <NeedsYouList items={needs} />
          </Rise>
          <Rise delay={80}>
            <Section title="Cases and reports">
              <ItemList items={rest.filter((i) => CASES.includes(i.kind) && i.line === 'property')} empty="No property cases yet." />
            </Section>
          </Rise>
          <Rise delay={140}>
            <Section title="Money held at the bank">
              <ItemList items={rest.filter((i) => MONEY.includes(i.kind) && i.line !== 'family')} empty="No escrows yet." />
            </Section>
          </Rise>
          {rest.some((i) => LISTINGS.includes(i.kind)) ? (
            <Rise delay={200}>
              <Section title="Listings">
                <ItemList items={rest.filter((i) => LISTINGS.includes(i.kind))} />
              </Section>
            </Rise>
          ) : null}
          <T v="headline" header style={{ fontSize: 18, marginTop: space[2] }}>Start something new</T>
          <View style={{ flexDirection: 'row', gap: space[2] }}>
            <StartTile icon="location-outline" title="Check a plot" detail="Searches, survey, legal" tone="lime" href="/order" />
            <StartTile icon="home-outline" title="Check a house" detail="Structure, title, rates" tone="ink" href={{ pathname: '/order', params: { line: 'building' } }} />
            <StartTile icon="list-outline" title="Verified listings" detail="Opens the website" tone="surface" onPress={() => void Linking.openURL(`${portalUrl()}/listings`)} />
          </View>
        </>
      ) : null}
    </Screen>
  );
}
