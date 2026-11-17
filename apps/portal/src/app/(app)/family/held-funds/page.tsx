'use client';
import { useRouter } from 'next/navigation';
import { useEffect } from 'react';
import { Skeleton } from '@tenmina/web-ui';

/** Since the decision of 17 November 2026 the family's money is the free balance of the client's one Tenmina
 * account (FR-ESC-025). This old address opens the account. */
export default function HeldFunds() {
  const router = useRouter();
  useEffect(() => { router.replace('/money'); }, [router]);
  return <Skeleton />;
}
