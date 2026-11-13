'use client';
import { useParams } from 'next/navigation';
import { ManageListing } from '@/components/roles/listings';

export default function SellerListing() {
  const { id } = useParams<{ id: string }>();
  return <ManageListing id={id} base="/seller/listings" />;
}
