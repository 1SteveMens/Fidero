'use client';
import { ListingsList } from '@/components/roles/listings';

export default function SellerListings() {
  return <ListingsList base="/seller/listings" title="Selling" intro="Your organisation's listings, with their badge and the checks behind it." />;
}
