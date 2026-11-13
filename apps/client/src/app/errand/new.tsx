import { useState } from 'react';
import { router } from 'expo-router';
import { Button, Choice, Label, Panel, Screen, T } from '@tenmina/ui';
import { LoadState, ProblemBox, itemsOf, money, useAction, useGet, useSession, type ApiMoney } from '@tenmina/mobile';
import type { Home } from '../../lib';

interface CatalogueItem {
  code?: string;
  key?: string;
  name: string;
  description?: string;
  official_fees?: ApiMoney;
  tenmina_charge?: ApiMoney;
  target_days?: number;
}

/** Errand catalogue (SCR-PTL-49, FR-TSK-001): choose the paperwork, say who it is for, and Tenmina quotes. */
export default function NewErrand() {
  const { me } = useSession();
  const cat = useGet<{ items: CatalogueItem[] } | CatalogueItem[]>('/v1/errand-catalogue', { country: me?.home_country ?? 'GH' });
  const home = useGet<Home>('/v1/home');
  const act = useAction();
  const [code, setCode] = useState<string>();
  const [member, setMember] = useState<string | null>(null);
  const items = itemsOf(cat.data as { items: CatalogueItem[] });

  async function create() {
    const r = await act.run<{ id: string }>('POST', '/v1/errands', { code, for_family_member_id: member });
    if (r) router.replace(`/errand/${r.id}`);
  }

  return (
    <Screen ground="paper" back title="Paperwork and errands" footer={<Button title="Ask for this errand" disabled={!code} loading={act.busy} onPress={() => void create()} />}>
      <T v="callout" muted>A vetted agent does the steps. Official fees are paid by the bank straight to the agency, after you approve each one.</T>
      <LoadState loading={cat.loading} problem={cat.problem} onRetry={cat.reload} hasData={!!cat.data} />
      {items.length ? (
        <Panel style={{ gap: 0 }}>
          <Label>What do you need?</Label>
          {items.map((c) => {
            const k = c.code ?? c.key ?? c.name;
            return (
              <Choice
                key={k}
                selected={code === k}
                onPress={() => setCode(k)}
                title={c.name}
                detail={[c.tenmina_charge ? `Tenmina ${money(c.tenmina_charge)}` : '', c.official_fees ? `official fees ${money(c.official_fees)}` : '', c.target_days ? `about ${c.target_days} days` : ''].filter(Boolean).join(' · ')}
              />
            );
          })}
        </Panel>
      ) : null}
      {home.data?.family_members.length ? (
        <Panel style={{ gap: 0 }}>
          <Label>Who is it for?</Label>
          <Choice selected={member === null} onPress={() => setMember(null)} title="For me" />
          {home.data.family_members.map((m) => (
            <Choice key={m.id} selected={member === m.id} onPress={() => setMember(m.id)} title={m.full_name} detail={m.relationship} />
          ))}
        </Panel>
      ) : null}
      <ProblemBox problem={act.problem} />
    </Screen>
  );
}
