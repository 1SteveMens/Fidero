'use client';
import { LineStatus } from '@/components/ops/LineStatus';
import { SectionPage } from '@/components/ops/pages';
import { insurance } from '@/components/ops/sections/insurance';

export default function Page() {
  return <SectionPage section={insurance}><LineStatus /></SectionPage>;
}
