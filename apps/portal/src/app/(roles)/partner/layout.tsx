'use client';
import { PartnerGate } from '@/components/roles/partner';

export default function PartnerLayout({ children }: { children: React.ReactNode }) {
  return <PartnerGate>{children}</PartnerGate>;
}
