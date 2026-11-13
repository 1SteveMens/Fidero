import { useState } from 'react';
import { Platform, View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import * as DocumentPicker from 'expo-document-picker';
import Ionicons from '@expo/vector-icons/Ionicons';
import { brand, space } from '@tenmina/tokens';
import { Button, Choice, DotStepper, Label, Panel, Screen, T, Tick } from '@tenmina/ui';
import { Field, ProblemBox, money, toProblem, useApi, useGet, useLoad, useSession, words, type ApiMoney, type Problem } from '@tenmina/mobile';

interface Tier {
  tier: string;
  tier_name: string;
  price: ApiMoney;
  local_price: ApiMoney | null;
  guide_for_you: ApiMoney | null;
  turnaround_days: number | null;
  requires_same_seller: boolean;
}

interface Terms {
  terms: { title: string; text: string };
  scope: { title: string; text: string };
  terms_version: string;
  scope_version: string;
}

const STEPS = ['What', 'Plot', 'Seller', 'Agree'];

/**
 * Order a report in four steps (SCR-PTL-06 to 09; W-03 to W-05): what to check
 * and the tier, the plot and its site plan, the seller, then the scope and terms.
 * The fee is then paid on the website (SCR-APP-06). Prices come only from the server.
 */
export default function Order() {
  const api = useApi();
  const { me } = useSession();
  const params = useLocalSearchParams<{ line?: string }>();
  const [step, setStep] = useState(0);
  const [assetType, setAssetType] = useState<'plot' | 'building'>(params.line === 'building' ? 'building' : 'plot');
  const [tier, setTier] = useState<string>();
  const [locality, setLocality] = useState('');
  const [plotNumber, setPlotNumber] = useState('');
  const [sitePlanRef, setSitePlanRef] = useState('');
  const [gps, setGps] = useState('');
  const [file, setFile] = useState<{ uri: string; name: string; mimeType?: string; file?: File }>();
  const [sellerName, setSellerName] = useState('');
  const [sellerPhone, setSellerPhone] = useState('');
  const [lead, setLead] = useState<string>();
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem>();
  const tiers = useGet<Tier[]>('/v1/catalogue/tiers', { kind: 'verification', asset_type: assetType });
  const leads = useGet<{ lead_sources: string[] }>('/v1/catalogue/lead-sources');
  const terms = useLoad((a) => a.get<Terms>('/v1/catalogue/terms'), 'terms');
  const chosen = tiers.data?.find((t) => t.tier === tier);

  async function pick() {
    const r = await DocumentPicker.getDocumentAsync({ type: ['image/*', 'application/pdf'], copyToCacheDirectory: true });
    if (!r.canceled && r.assets[0]) setFile(r.assets[0] as typeof file);
  }

  async function submit() {
    if (!file) return;
    setBusy(true);
    setProblem(undefined);
    try {
      const order = await api.post<{ id: string }>('/v1/orders', {
        country: me?.home_country ?? 'GH',
        kind: 'verification',
        draft: true,
        tier,
        asset: { type: assetType, locality: locality.trim(), plot_number: plotNumber.trim(), site_plan_ref: sitePlanRef.trim(), ghana_post_gps: gps.trim() },
        seller: { name: sellerName.trim(), phone: sellerPhone.trim() },
        lead_source: lead,
      });
      const form = new FormData();
      if (Platform.OS === 'web' && file.file) form.append('file', file.file, file.name);
      else form.append('file', { uri: file.uri, name: file.name, type: file.mimeType ?? 'application/octet-stream' } as unknown as Blob);
      form.append('role', 'site_plan');
      await api.request('POST', `/v1/orders/${order.id}/documents`, { form });
      await api.post(`/v1/orders/${order.id}/submit`, { accept_terms: true, terms_version: terms.data?.terms_version, scope_version: terms.data?.scope_version });
      router.replace(`/pay-fee/${order.id}`);
    } catch (e) {
      setProblem(toProblem(e));
    }
    setBusy(false);
  }

  const canNext = [
    !!tier,
    locality.trim().length > 1 && (assetType === 'building' || (plotNumber.trim() && sitePlanRef.trim())) && !!file,
    sellerName.trim().length > 1 && sellerPhone.trim().length > 6 && !!lead,
    agree && !!terms.data,
  ][step];

  return (
    <Screen
      ground="paper"
      back
      title={assetType === 'plot' ? 'Check a plot' : 'Check a house'}
      footer={
        <View style={{ flexDirection: 'row', gap: space[2] }}>
          {step > 0 ? (
            <View style={{ flex: 1 }}>
              <Button title="Back" variant="quiet" onPress={() => setStep((s) => s - 1)} />
            </View>
          ) : null}
          <View style={{ flex: 2 }}>
            {step < 3 ? (
              <Button title="Next" icon="arrow-forward" disabled={!canNext} onPress={() => setStep((s) => s + 1)} />
            ) : (
              <Button title="Agree and go to payment" icon="checkmark" disabled={!canNext} loading={busy} onPress={() => void submit()} />
            )}
          </View>
        </View>
      }
    >
      <Panel>
        <DotStepper labels={STEPS} done={step} />
      </Panel>

      {step === 0 ? (
        <>
          <Panel style={{ gap: 0 }}>
            <Label>What are you buying?</Label>
            <Choice selected={assetType === 'plot'} onPress={() => setAssetType('plot')} title="A plot of land" detail="Registry searches, site visit, survey overlay, lawyer" />
            <Choice selected={assetType === 'building'} onPress={() => setAssetType('building')} title="A house or building" detail="As for land, plus the structure and permits" />
          </Panel>
          <Panel style={{ gap: 0 }}>
            <Label>How deep a check?</Label>
            {[...(tiers.data ?? [])].sort((a, b) => Number(a.price.amount) - Number(b.price.amount)).map((t) => (
              <Choice
                key={t.tier}
                selected={tier === t.tier}
                onPress={() => setTier(t.tier)}
                title={`${t.tier_name} · ${money(t.price)}`}
                detail={[t.guide_for_you ? `about ${money(t.guide_for_you)}` : '', t.local_price ? money(t.local_price) : '', t.turnaround_days ? `${t.turnaround_days} days` : '', t.requires_same_seller ? 'further plot, same seller' : ''].filter(Boolean).join(' · ')}
              />
            ))}
          </Panel>
          <ProblemBox problem={tiers.problem} />
        </>
      ) : null}

      {step === 1 ? (
        <>
          <Field label="Town or area" value={locality} onChange={setLocality} placeholder="For example: Kasoa, Millennium City" />
          {assetType === 'plot' ? (
            <>
              <Field label="Plot number" value={plotNumber} onChange={setPlotNumber} />
              <Field label="Site plan reference" value={sitePlanRef} onChange={setSitePlanRef} hint="Printed on the site plan, often with the surveyor's stamp." />
            </>
          ) : null}
          <Field label="GhanaPost GPS address (optional)" value={gps} onChange={setGps} placeholder="GA-123-4567" />
          <Panel style={{ gap: space[2] }}>
            <Label>The site plan</Label>
            {file ? (
              <View style={{ flexDirection: 'row', gap: space[3], alignItems: 'center' }}>
                <Tick />
                <T v="callout" style={{ flex: 1 }}>{file.name}</T>
              </View>
            ) : (
              <T v="callout" muted>A photo or PDF of the site plan the seller gave you.</T>
            )}
            <Button title={file ? 'Choose another file' : 'Choose the site plan'} variant="dark" icon="document-attach-outline" onPress={() => void pick()} />
          </Panel>
        </>
      ) : null}

      {step === 2 ? (
        <>
          <Field label="Seller's name" value={sellerName} onChange={setSellerName} />
          <Field label="Seller's phone" value={sellerPhone} onChange={setSellerPhone} keyboardType="phone-pad" placeholder="+233 …" hint="We call the seller to arrange the site visit. Never pay the seller before the report." />
          <Panel style={{ gap: 0 }}>
            <Label>How did you hear about Tenmina?</Label>
            {(leads.data?.lead_sources ?? []).map((l) => (
              <Choice key={l} selected={lead === l} onPress={() => setLead(l)} title={words(l)} />
            ))}
          </Panel>
        </>
      ) : null}

      {step === 3 && terms.data ? (
        <>
          <Panel>
            <Label>{terms.data.scope.title}</Label>
            <T v="callout">{terms.data.scope.text}</T>
          </Panel>
          <Panel>
            <Label>{terms.data.terms.title}</Label>
            <T v="callout">{terms.data.terms.text}</T>
          </Panel>
          <Choice selected={agree} onPress={() => setAgree((a) => !a)} title="I have read the scope and the terms, and I agree" detail={chosen ? `${chosen.tier_name}: ${money(chosen.price)}, paid on the Tenmina website` : undefined} />
          <View style={{ flexDirection: 'row', gap: space[2] }}>
            <Ionicons name="lock-closed-outline" size={18} color={brand.ink} />
            <T v="footnote" muted style={{ flex: 1 }}>You pay Tenmina's fee for the work, whatever the verdict. Never pay the seller until the report is out and the escrow is set up.</T>
          </View>
        </>
      ) : null}
      <ProblemBox problem={problem} />
    </Screen>
  );
}
