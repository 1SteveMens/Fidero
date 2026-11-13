import { View } from 'react-native';
import { space } from '@tenmina/tokens';
import { Label, Panel, Screen, T } from '@tenmina/ui';
import { Empty, day, money, words } from '@tenmina/mobile';
import { usePay } from '../(tabs)/pay';

/** Statements (SCR-MOB-22, as SCR-BO-36; FR-PRO-007): remittance advices and the yearly statement. */
export default function Statements() {
  const { pay } = usePay();
  const list = pay?.statements ?? [];
  return (
    <Screen ground="paper" back title="Statements">
      {pay && !list.length ? <Empty icon="document-text-outline" title="No statements yet" detail="A remittance advice comes with each payment run." /> : null}
      {list.length ? (
        <Panel style={{ gap: 0, paddingVertical: space[1] }}>
          {list.map((s, i) => (
            <View key={s.id} style={{ paddingVertical: space[3], borderTopWidth: i ? 1 : 0, borderTopColor: '#ECEAE4', gap: 2 }}>
              <View style={{ flexDirection: 'row', gap: space[2] }}>
                <T v="headline" style={{ flex: 1, fontSize: 15 }}>{s.tax_year ? `Yearly statement ${s.tax_year}` : words(s.kind)}</T>
                <T v="headline" style={{ fontSize: 15 }}>{money(s.net)}</T>
              </View>
              <Label>{`${s.line_reference ?? ''}${s.line_reference ? ' · ' : ''}issued ${day(s.issued_at)}`}</Label>
            </View>
          ))}
        </Panel>
      ) : null}
      <T v="footnote" muted>Each statement is a sealed PDF. Download them on the Tenmina website.</T>
    </Screen>
  );
}
