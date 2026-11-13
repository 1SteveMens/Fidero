'use client';
/* Whether the insurance line is open in the staff member's country (US-INS-001 AC2). */
import { Blocked, useGet, useSession } from '@tenmina/web-ui';

export function LineStatus() {
  const { me } = useSession();
  const country = me?.home_country ?? '';
  const { data } = useGet<{ open: boolean; reasons: (string | { message?: string })[] }>(country ? '/v1/insurance/products/line-status' : null, { country });
  if (!data) return null;
  if (data.open) return <div className="banner-info"><strong>Cover line open in {country}.</strong> A licensed insurer partner and Tenmina&apos;s intermediary licence are in place.</div>;
  return (
    <Blocked title={`Cover line closed in ${country}`}>
      {data.reasons.map((r) => (typeof r === 'string' ? r : r.message)).join(' ') || 'Clients do not see cover products.'}
    </Blocked>
  );
}
