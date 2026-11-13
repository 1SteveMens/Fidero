'use client';
import { Empty, NeedsYou, Skeleton, useGet, useSession } from '@tenmina/web-ui';

type HomeItem = { kind: string; title: string; detail?: string; href?: string; needs_action?: boolean };

export default function Home() {
  const { me } = useSession();
  const home = useGet<{ items: HomeItem[] }>('/v1/home');
  const needs = home.data?.items.filter((i) => i.needs_action) ?? [];
  const rest = home.data?.items.filter((i) => !i.needs_action) ?? [];
  return (
    <div className="stack">
      <p className="label">Home</p>
      <h1>Hello, {me?.full_name.split(' ')[0]}.</h1>
      {home.isLoading ? <Skeleton /> : null}
      {needs.map((n, i) => <NeedsYou key={i} title={n.title} detail={n.detail} href={n.href} />)}
      {rest.length ? rest.map((n, i) => (
        <a key={i} href={n.href} className="card card-link"><div className="label">{n.kind}</div><div style={{ fontWeight: 700 }}>{n.title}</div>{n.detail ? <div className="muted">{n.detail}</div> : null}</a>
      )) : !home.isLoading && !needs.length ? <Empty>Nothing needs you right now.</Empty> : null}
    </div>
  );
}
