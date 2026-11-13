'use client';
/* Bank name check result (FR-ESC-015). Red only for a name the bank did not match (6.1a). */
import { words } from './kit';

export function NameMatch({ value }: { value: string }) {
  if (value === 'matched') return <span className="chip chip-lime">✓ Bank matched the name</span>;
  if (value === 'mismatch') return <span className="name-mismatch">✕ Bank name does not match</span>;
  return <span className="chip">{words(value || 'not checked')}</span>;
}
