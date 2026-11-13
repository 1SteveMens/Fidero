'use client';
import { DetailPage } from '@/components/ops/pages';
import { audit } from '@/components/ops/sections/audit';

export default function Page() {
  return <DetailPage section={audit} />;
}
