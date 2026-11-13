'use client';
import { useParams } from 'next/navigation';
import { ManageListing } from '@/components/roles/listings';

export default function AuthorityListing() {
  const { id } = useParams<{ id: string }>();
  return <ManageListing id={id} base="/authority/listings" />;
}
