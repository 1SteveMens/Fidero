import { View } from 'react-native';
import { router } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { FIELD_ROLES } from '@tenmina/shared';
import { brand, font, space } from '@tenmina/tokens';
import { Button, GroundContext, Label, Mark, Panel, Rise, T } from '@tenmina/ui';
import { useState } from 'react';
import { Choice } from '@tenmina/ui';
import { useField } from '../store';

/**
 * Sign in and register this phone (SCR-MOB-01). The demo build lets the tester pick a role,
 * so each role's screens can be tried on one phone. Real sign-in replaces this.
 */
export default function Welcome() {
  const { signIn } = useField();
  const insets = useSafeAreaInsets();
  const [role, setRole] = useState(FIELD_ROLES[0].role);
  return (
    <GroundContext.Provider value="ink">
      <View style={{ flex: 1, backgroundColor: brand.ink, paddingTop: insets.top + space[4], paddingBottom: insets.bottom + space[4], paddingHorizontal: space[6], gap: space[5] }}>
        <Rise style={{ flexDirection: 'row', alignItems: 'baseline', gap: space[2] }}>
          <Mark />
          <T v="title" color="#F7F6F2" style={{ fontFamily: font.heavy, letterSpacing: -1 }}>tenmina</T>
          <Label color={brand.lime}>Field</Label>
        </Rise>
        <View style={{ flex: 1, justifyContent: 'center', gap: space[3] }}>
          <Rise delay={100}>
            <T v="display" header color="#F7F6F2">Work you can prove.</T>
          </Rise>
          <Rise delay={180}>
            <T v="body" muted>Your jobs, checklists and evidence in one place. Photos are taken in this app only, and sealed when they are taken.</T>
          </Rise>
          <Rise delay={260}>
            <Panel style={{ marginTop: space[3], gap: 0 }}>
              <Label style={{ marginBottom: space[1] }}>Demo: try the app as</Label>
              {FIELD_ROLES.map((r) => (
                <Choice key={r.role} selected={role === r.role} onPress={() => setRole(r.role)} title={r.label} detail={r.detail} />
              ))}
            </Panel>
          </Rise>
        </View>
        <Rise delay={340}>
          <Button
            title="Sign in"
            icon="arrow-forward"
            onPress={() => {
              signIn(role);
              router.replace('/');
            }}
          />
        </Rise>
      </View>
    </GroundContext.Provider>
  );
}
