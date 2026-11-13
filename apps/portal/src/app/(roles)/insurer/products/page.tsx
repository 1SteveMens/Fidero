'use client';
/* Your products as clients see them (SCR-PTL-51). Tenmina's administrators publish or withdraw them with
   your approval on file; ask your Tenmina contact to change one. */
import { Card, Money, Status, When, useGet } from '@tenmina/web-ui';
import { EmptyText, Loaded, PageHead, items, words, type Page } from '@/components/roles/kit';
import type { Product } from '@/components/roles/insurer';

export default function InsurerProducts() {
  const q = useGet<Page<Product>>('/v1/insurance/products');
  return (
    <div className="stack">
      <PageHead label="Insurer" title="Products">Your name comes first on every product page. Tenmina does not hold the risk.</PageHead>
      <Loaded q={q}>{(d) => items(d).length ? items(d).map((p) => (
        <Card key={p.id} className="stack">
          <div className="label">{p.insurer_name}</div>
          <div className="spread"><strong style={{ fontSize: 18 }}>{p.name}</strong><Status value={p.status} /></div>
          <span>{p.summary}</span>
          <span><Money value={p.premium} /> a {p.premium_period} · {words(p.kind)} cover</span>
          <span className="muted" style={{ fontSize: 14 }}>{p.statement}</span>
          {p.published_at ? <span className="muted" style={{ fontSize: 13 }}>Published <When value={p.published_at} /></span> : null}
        </Card>
      )) : <EmptyText>No products yet.</EmptyText>}</Loaded>
    </div>
  );
}
