'use client';
import { useSession } from '@tenmina/web-ui';
import { NewListing } from '@/components/roles/listings';

export default function SellerNewListing() {
  const { hasRole } = useSession();
  return <NewListing base="/seller/listings" origins={hasRole('DV') ? ['developer', 'seller'] : ['seller']} />;
}
