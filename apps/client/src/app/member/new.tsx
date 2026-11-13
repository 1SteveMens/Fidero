import { useState } from 'react';
import { Pressable, View } from 'react-native';
import { router } from 'expo-router';
import { space } from '@tenmina/tokens';
import { Button, Choice, Label, Panel, Screen, T, Tick, usePalette } from '@tenmina/ui';
import { Field, ProblemBox, useAction } from '@tenmina/mobile';

const RELATIONSHIPS = ['mother', 'father', 'sibling', 'child', 'nephew', 'niece', 'grandparent', 'spouse', 'other'];

/**
 * Add a family member (SCR-PTL-38; FR-FEE-001): who Tenmina pays bills and
 * arranges care for. They never receive money: institutions, carers and vendors do.
 */
export default function NewMember() {
  const pal = usePalette('paper');
  const act = useAction();
  const [name, setName] = useState('');
  const [rel, setRel] = useState('mother');
  const [phone, setPhone] = useState('');
  const [address, setAddress] = useState('');
  const [confirms, setConfirms] = useState(true);

  async function save() {
    const r = await act.run('POST', '/v1/family-members', { full_name: name.trim(), relationship: rel, phone: phone.trim(), address: address.trim(), may_confirm_visits: confirms });
    if (r) router.back();
  }

  return (
    <Screen ground="paper" back title="Add a family member" footer={<Button title="Add" disabled={name.trim().length < 2 || phone.trim().length < 7} loading={act.busy} onPress={() => void save()} />}>
      <Field label="Full name" value={name} onChange={setName} />
      <Panel style={{ gap: 0 }}>
        <Label>Relationship to you</Label>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', columnGap: space[4] }}>
          {RELATIONSHIPS.map((r) => (
            <View key={r} style={{ width: '45%' }}>
              <Choice selected={rel === r} onPress={() => setRel(r)} title={r.charAt(0).toUpperCase() + r.slice(1)} />
            </View>
          ))}
        </View>
      </Panel>
      <Field label="Their mobile number" value={phone} onChange={setPhone} keyboardType="phone-pad" placeholder="+233 …" hint="For visit codes and confirmations on their own phone." />
      <Field label="Where they live" value={address} onChange={setAddress} placeholder="Area and town" />
      <Pressable onPress={() => setConfirms((c) => !c)} accessibilityRole="checkbox" accessibilityState={{ checked: confirms }} style={{ flexDirection: 'row', gap: space[3], alignItems: 'center', minHeight: 44 }}>
        {confirms ? <Tick size={26} /> : <View style={{ width: 26, height: 26, borderRadius: 8, borderWidth: 2, borderColor: pal.text }} />}
        <T v="callout" style={{ flex: 1 }}>They can confirm care visits and deliveries with a code on their phone.</T>
      </Pressable>
      <ProblemBox problem={act.problem} />
    </Screen>
  );
}
