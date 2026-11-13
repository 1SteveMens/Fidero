'use client';
import { useParams } from 'next/navigation';
import { PayRunPage } from '@/components/ops/PayRun';

export default function Page() {
  const { id } = useParams<{ id: string }>();
  return <PayRunPage id={id} />;
}
