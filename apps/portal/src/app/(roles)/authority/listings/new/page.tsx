'use client';
import { NewListing } from '@/components/roles/listings';

export default function AuthorityNewListing() {
  return <NewListing base="/authority/listings" origins={['stool', 'family']} />;
}
