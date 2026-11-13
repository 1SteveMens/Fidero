import { Linking, View } from 'react-native';
import { space } from '@tenmina/tokens';
import { Rise, Screen, T } from '@tenmina/ui';
import { LoadState, Section, portalUrl } from '@tenmina/mobile';
import { ItemList, StartTile, useHome } from '../../components/rows';

/**
 * Projects (03 2.3a): building in stages and project funds, property
 * management, and disputes. Money moves only against a passed inspection or a
 * checked invoice, after the client approves and two staff approve.
 */
export default function Projects() {
  const home = useHome();
  const items = home.data?.items ?? [];
  const pick = (kinds: string[], lines?: string[]) => items.filter((i) => kinds.includes(i.kind) && (!lines || lines.includes(i.line)));
  const builds = pick(['project']);
  const managed = pick(['managed_property', 'repair']);
  const disputes = pick(['dispute']);
  const open = (path: string) => void Linking.openURL(`${portalUrl()}${path}`);

  return (
    <Screen ground="paper" tabs title="Projects">
      <LoadState loading={home.loading} problem={home.problem} onRetry={home.reload} hasData={!!home.data} />
      {home.data ? (
        <>
          <Rise>
            <Section title="Building and project funds">
              <ItemList items={builds} empty="No projects yet." />
            </Section>
          </Rise>
          <Rise delay={80}>
            <Section title="Property management">
              <ItemList items={managed} empty="No managed properties." />
            </Section>
          </Rise>
          <Rise delay={140}>
            <Section title="Disputes">
              <ItemList items={disputes} empty="No disputes." />
            </Section>
          </Rise>
          <T v="headline" header style={{ fontSize: 18, marginTop: space[2] }}>Start something new</T>
          <View style={{ flexDirection: 'row', gap: space[2] }}>
            <StartTile icon="construct-outline" title="Build in stages" detail="Paid after each inspection" tone="lime" onPress={() => open('/build/new')} />
            <StartTile icon="cash-outline" title="Project funds" detail="Released against invoices" tone="ink" onPress={() => open('/projects/new')} />
          </View>
          <View style={{ flexDirection: 'row', gap: space[2] }}>
            <StartTile icon="home-outline" title="Manage a property" detail="Rent, repairs, inspections" tone="surface" onPress={() => open('/properties/new')} />
            <StartTile icon="calendar-outline" title="An event" detail="Funerals, weddings" tone="surface" onPress={() => open('/events/new')} />
          </View>
          <T v="footnote" muted>Starting a build, a project, a managed property or an event opens the Tenmina website.</T>
        </>
      ) : null}
    </Screen>
  );
}
