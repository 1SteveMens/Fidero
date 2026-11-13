'use client';
/* Listing management for sellers, developers and authorities (SCR-PTL-31, SCR-PTL-32; US-LST-001,
   US-LST-006, US-LST-007): create, add photos, submit for verification (the fee is invoiced), see the
   badge and the report behind it, edit price and text, withdraw, re-verify an expired badge. */
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button, Card, Chip, Field, Input, KV, Money, ProblemBox, Select, Skeleton, Status, Textarea, Verdict, When, useGet, useSession } from '@tenmina/web-ui';
import type { Money as MoneyT } from '@tenmina/api-client';
import { EmptyText, Loaded, PageHead, RowLink, Section, items, useAct, useApi, words, type Page } from './kit';
import { postForm } from './files';

export type Listing = {
  id: string; reference: string; slug: string; status: string; origin: string; kind: string; title: string; description: string;
  estate_name: string; price: MoneyT; size_sqm: string | null; region: string; district: string; locality: string;
  badge: { label: string; checks_date: string; expires_at: string; report_reference: string } | null; checks_date: string | null;
  seller: { name: string; kind: string; established: boolean } | null; disclosure: string;
  media: { id: string; kind: string; caption: string; url: string; public: boolean }[];
  owner_view?: { status_reason: string; submitted_at: string | null; fee_invoice_id: string | null; fee_paid_at: string | null; verification_case_id: string | null; report_id: string | null; badge_expires_at: string | null; view_count: number; enquiries: number; suspensions: { reason: string; created_at: string }[] } | null;
};
type Terms = { terms: { title: string; text: string }; scope: { title: string; text: string }; terms_version: string; scope_version: string };

function TermsBox({ terms, agree, setAgree }: { terms?: Terms; agree: boolean; setAgree: (v: boolean) => void }) {
  if (!terms) return <Skeleton lines={2} />;
  return (
    <div className="stack" style={{ gap: 6, fontSize: 14 }}>
      <strong>{terms.scope.title}</strong><span>{terms.scope.text}</span>
      <strong>{terms.terms.title}</strong><span>{terms.terms.text}</span>
      <label className="check-row" style={{ minHeight: 44 }}><input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} style={{ width: 22, height: 22 }} /> I have read and accept both</label>
    </div>
  );
}

type ReportView = { reference: string; version: number; verdict: string; released_at: string; pdf_sha256: string; pdf: { url?: string }; sections: { label?: string; title?: string; verdict?: string | null; text?: string }[] };

const STATUS_TEXT: Record<string, string> = {
  draft: 'Not yet sent for checking. Add photos, then submit.',
  in_verification: 'Tenmina is checking the plot. The listing goes live only with a released report.',
  rejected: 'Not listed: the checks did not support listing it.',
  live: 'Live with the Tenmina Verified badge.',
  suspended: 'Hidden while Tenmina reviews it.',
  expired: 'The badge has expired. Order a re-check to list it again.',
  reserved: 'Reserved by a buyer. A fresh search runs for them.',
  sold: 'Sold through escrow.',
  withdrawn: 'Withdrawn by you.',
  removed: 'Removed by Tenmina.',
};

export function ListingsList({ base, title, intro }: { base: string; title: string; intro: string }) {
  const q = useGet<Page<Listing>>('/v1/listings', { mine: 1 });
  return (
    <div className="stack">
      <PageHead label={title} title="Listings">{intro}</PageHead>
      <Link href={`${base}/new`} className="btn btn-primary">List a property</Link>
      <Loaded q={q}>
        {(d) => items(d).length ? items(d).map((x) => (
          <RowLink key={x.id} href={`${base}/${x.id}`} meta={x.reference} title={x.title} sub={<Money value={x.price} />}
            right={x.badge && x.status === 'live' ? <Chip tone="lime">✓ Verified</Chip> : <Status value={x.status} needsYou={x.status === 'draft' || x.status === 'expired'} />} />
        )) : <EmptyText>No listings yet.</EmptyText>}
      </Loaded>
    </div>
  );
}

export function NewListing({ base, origins }: { base: string; origins: string[] }) {
  const router = useRouter();
  const { me } = useSession();
  const api = useApi();
  const act = useAct();
  const orgs = useGet<Page<{ id: string; name: string; country: string }>>('/v1/organisations');
  const [f, setF] = useState({ kind: 'plot', origin: origins[0], title: '', description: '', estate_name: '', amount: '', currency: 'GHS', size_sqm: '', locality: '', region: '', district: '', plot_number: '', site_plan_ref: '', ghana_post_gps: '' });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });
  const org = items(orgs.data)[0];
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const x = await act.run('save', () => api<Listing>('POST', '/v1/listings', {
      country: org?.country || me?.home_country || 'GH', organisation_id: org?.id, origin: f.origin, kind: f.kind, title: f.title,
      description: f.description, estate_name: f.estate_name, price: { amount: f.amount, currency: f.currency },
      ...(f.size_sqm ? { size_sqm: f.size_sqm } : {}),
      asset: { locality: f.locality, region: f.region, district: f.district, plot_number: f.plot_number, site_plan_ref: f.site_plan_ref, ghana_post_gps: f.ghana_post_gps },
    }));
    if (x) router.push(`${base}/${x.id}`);
  }
  return (
    <form className="stack" onSubmit={submit}>
      <PageHead back={{ href: base, label: 'Listings' }} label="New listing" title="List a property">Tenmina checks the plot before it goes live. You pay a fixed fee, the same whatever the verdict.</PageHead>
      {org ? <p className="muted" style={{ margin: 0 }}>Listed by {org.name}.</p> : null}
      <Field label="What it is"><Select value={f.kind} onChange={set('kind')}><option value="plot">Plot</option><option value="building">Building</option><option value="estate_plot">Plot in an estate</option><option value="offplan_unit">Off-plan unit</option></Select></Field>
      {origins.length > 1 ? <Field label="Whose land"><Select value={f.origin} onChange={set('origin')}>{origins.map((o) => <option key={o} value={o}>{words(o)}</option>)}</Select></Field> : null}
      <Field label="Title"><Input value={f.title} onChange={set('title')} required /></Field>
      <Field label="Description"><Textarea value={f.description} onChange={set('description')} /></Field>
      <Field label="Estate name (if any)"><Input value={f.estate_name} onChange={set('estate_name')} /></Field>
      <div className="grid2" style={{ gridTemplateColumns: '2fr 1fr', gap: 8 }}>
        <Field label="Price"><Input inputMode="decimal" value={f.amount} onChange={set('amount')} required /></Field>
        <Field label="Currency"><Input value={f.currency} maxLength={3} onChange={set('currency')} /></Field>
      </div>
      <Field label="Size in square metres"><Input inputMode="decimal" value={f.size_sqm} onChange={set('size_sqm')} /></Field>
      <h2>Where it is</h2>
      <Field label="Locality"><Input value={f.locality} onChange={set('locality')} required /></Field>
      <Field label="Region"><Input value={f.region} onChange={set('region')} /></Field>
      <Field label="District"><Input value={f.district} onChange={set('district')} /></Field>
      <Field label="Plot number"><Input value={f.plot_number} onChange={set('plot_number')} /></Field>
      <Field label="Site plan reference"><Input value={f.site_plan_ref} onChange={set('site_plan_ref')} /></Field>
      <Field label="Digital address (if known)"><Input value={f.ghana_post_gps} onChange={set('ghana_post_gps')} /></Field>
      <ProblemBox error={act.error} />
      <Button variant="primary" type="submit" busy={act.busy === 'save'} block>Save as draft</Button>
    </form>
  );
}

export function ManageListing({ id, base }: { id: string; base: string }) {
  const q = useGet<Listing>(`/v1/listings/${id}`);
  const api = useApi();
  const act = useAct();
  const [file, setFile] = useState<File | null>(null);
  const [caption, setCaption] = useState('');
  const [mkind, setMkind] = useState('');
  const [edit, setEdit] = useState<{ title: string; description: string; amount: string } | null>(null);
  const [reason, setReason] = useState('');
  const [showReport, setShowReport] = useState(false);
  const report = useGet<ReportView>(showReport ? `/v1/listings/${id}/report` : null);
  const { me } = useSession();
  const [agree, setAgree] = useState(false);
  const x = q.data;
  const needsTerms = x?.status === 'draft' || x?.status === 'expired';
  const terms = useGet<Terms>(needsTerms ? '/v1/catalogue/terms' : null, { country: me?.home_country || 'GH' });
  const versions = { terms_version: terms.data?.terms_version ?? '', scope_version: terms.data?.scope_version ?? '' };
  if (q.isLoading) return <Skeleton lines={8} />;
  if (q.error || !x) return <ProblemBox error={q.error ?? 'Listing not found.'} />;
  const ov = x.owner_view;
  const canEdit = ['draft', 'live', 'expired', 'in_verification'].includes(x.status);
  const reload = () => q.mutate();
  return (
    <div className="stack">
      <PageHead back={{ href: base, label: 'Listings' }} label={x.reference} title={x.title} />
      <div className="row">{x.badge && x.status === 'live' ? <Chip tone="lime">✓ {x.badge.label}</Chip> : <Status value={x.status} needsYou={x.status === 'draft' || x.status === 'expired'} />}<Money value={x.price} /></div>
      <div className="banner-info">{STATUS_TEXT[x.status] ?? words(x.status)}{ov?.status_reason ? ` ${ov.status_reason}` : ''}</div>
      {x.status === 'draft' ? (
        <div className="card-ink stack">
          <strong>Send for checking</strong>
          <p style={{ margin: 0 }}>Tenmina orders a verification of the plot and sends you the listing fee invoice. The fee is the same whatever the verdict, and buyers see the report before you do.</p>
          <TermsBox terms={terms.data} agree={agree} setAgree={setAgree} />
          <Button variant="primary" disabled={!agree || !terms.data} busy={act.busy === 'submit'} onClick={() => act.run('submit', async () => { await api('POST', `/v1/listings/${id}/submissions`, versions); await reload(); }, 'Sent for checking. Your fee invoice is under Invoices.')}>Submit for verification</Button>
        </div>
      ) : null}
      {x.status === 'expired' ? (
        <div className="card-ink stack">
          <TermsBox terms={terms.data} agree={agree} setAgree={setAgree} />
          <Button variant="action" disabled={!agree || !terms.data} busy={act.busy === 'rev'} onClick={() => act.run('rev', async () => { await api('POST', `/v1/listings/${id}/reverifications`, versions); await reload(); }, 'Re-check ordered.')}>Order a re-check</Button>
        </div>
      ) : null}
      <Card>
        <KV items={[
          ['Where', [x.locality, x.district, x.region].filter(Boolean).join(', ') || '—'],
          ['Size', x.size_sqm ? `${Number(x.size_sqm).toLocaleString('en-GB')} m²` : '—'],
          ['Checked on', x.checks_date ? <When value={x.checks_date} /> : 'Not yet'],
          ['Badge expires', x.badge?.expires_at ? <When value={x.badge.expires_at} /> : '—'],
          ['Views', ov ? String(ov.view_count) : '—'],
          ['Enquiries', ov ? (base.startsWith('/seller') ? <Link key="e" href="/seller/enquiries">{ov.enquiries}</Link> : String(ov.enquiries)) : '—'],
          ['Fee', ov?.fee_paid_at ? <span key="f">Paid <When value={ov.fee_paid_at} /></span> : ov?.fee_invoice_id ? (base.startsWith('/seller') ? <Link key="f" href="/seller/invoices">Invoiced, not paid</Link> : 'Invoiced, not paid') : '—'],
        ]} />
      </Card>
      {ov?.suspensions?.length ? <Section title="Suspensions">{ov.suspensions.map((s, n) => <Card key={n}><When value={s.created_at} />: {s.reason}</Card>)}</Section> : null}

      <Section title="Checked plots disclosure">
        <Card><p style={{ margin: 0, fontSize: 14 }}>{x.disclosure || 'Shown to buyers on the listing page.'}</p></Card>
      </Section>

      {ov?.report_id ? (
        <Section title="Report on this plot" action={!showReport ? <Button size="sm" variant="ghost" onClick={() => setShowReport(true)}>Show</Button> : undefined}>
          {showReport ? (report.isLoading ? <Skeleton /> : report.error ? <ProblemBox error={report.error} /> : report.data ? (
            <div className="card-ink stack">
              <div className="spread"><span className="mono">{report.data.reference}</span><Verdict value={report.data.verdict} /></div>
              <span>Released <When value={report.data.released_at} /></span>
              {report.data.sections.slice(0, 14).map((s, n) => <div key={n} className="statline"><span>{s.label ? `${s.label}. ` : ''}{s.title}</span><span>{s.verdict ? <Verdict value={s.verdict} /> : null}</span></div>)}
              <span className="mono" style={{ fontSize: 12, overflowWrap: 'anywhere' }}>SHA-256 {report.data.pdf_sha256}</span>
              {report.data.pdf?.url ? <a className="btn btn-primary" href={report.data.pdf.url} target="_blank" rel="noopener noreferrer">Open the PDF</a> : null}
            </div>
          ) : null) : null}
        </Section>
      ) : null}

      <Section title="Photos and documents">
        {x.status === 'draft' ? <p className="muted" style={{ margin: 0 }}>Add the site plan before you submit. Tenmina checks the plot from it.</p> : null}
        {x.media.length ? <div className="photo-strip">{x.media.filter((m) => m.kind === 'photo').map((m) => <img key={m.id} src={m.url} alt={m.caption || x.title} />)}</div> : <p className="muted">No photos yet.</p>}
        {x.media.filter((m) => m.kind !== 'photo').map((m) => <Card key={m.id}>{words(m.kind)}: {m.caption || 'File'}</Card>)}
        {canEdit ? (
          <Card className="stack">
            <Field label="Photo or document">
              <span className="filepick"><input type="file" accept="image/*,application/pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /><span>{file ? file.name : 'Choose a file or take a photo'}</span></span>
            </Field>
            <Field label="What it is">
              <Select value={mkind || (file && !file.type.startsWith('image/') ? 'site_plan' : 'photo')} onChange={(e) => setMkind(e.target.value)}>
                <option value="photo">Photo</option><option value="site_plan">Site plan</option><option value="floor_plan">Floor plan</option><option value="document">Other document</option><option value="video">Video</option>
              </Select>
            </Field>
            <Field label="Caption"><Input value={caption} onChange={(e) => setCaption(e.target.value)} /></Field>
            <Button variant="dark" disabled={!file} busy={act.busy === 'media'} onClick={() => act.run('media', async () => {
              await postForm(`/v1/listings/${id}/media`, { kind: mkind || (file!.type.startsWith('image/') ? 'photo' : 'site_plan'), caption, file });
              setFile(null); setCaption(''); setMkind(''); await reload();
            }, 'Added.')}>Add</Button>
          </Card>
        ) : null}
      </Section>

      {canEdit ? (
        <Section title="Edit">
          {edit ? (
            <Card className="stack">
              <Field label="Title"><Input value={edit.title} onChange={(e) => setEdit({ ...edit, title: e.target.value })} /></Field>
              <Field label="Description"><Textarea value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></Field>
              <Field label={`Price (${x.price.currency})`}><Input inputMode="decimal" value={edit.amount} onChange={(e) => setEdit({ ...edit, amount: e.target.value })} /></Field>
              <div className="row">
                <Button variant="dark" busy={act.busy === 'edit'} onClick={() => act.run('edit', async () => { await api('PATCH', `/v1/listings/${id}`, { title: edit.title, description: edit.description, price: { amount: edit.amount, currency: x.price.currency } }); setEdit(null); await reload(); }, 'Saved.')}>Save</Button>
                <Button variant="ghost" onClick={() => setEdit(null)}>Cancel</Button>
              </div>
            </Card>
          ) : <Button variant="ghost" onClick={() => setEdit({ title: x.title, description: x.description, amount: x.price.amount })}>Edit title, description or price</Button>}
          <Card className="stack">
            <Field label="Withdraw this listing: say why"><Input value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
            <Button variant="ghost" disabled={!reason.trim()} busy={act.busy === 'wd'} onClick={() => act.run('wd', async () => { await api('POST', `/v1/listings/${id}/withdrawals`, { reason }); await reload(); }, 'Withdrawn.')}>Withdraw</Button>
          </Card>
        </Section>
      ) : null}
      {x.status === 'live' || x.status === 'reserved' ? <Link className="btn btn-ghost" href={`/listings/${x.id}`}>See the public page</Link> : null}
      <ProblemBox error={act.error} />
      {act.toast}
    </div>
  );
}
