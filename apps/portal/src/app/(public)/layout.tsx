/* Public pages: listings, the report check, the daily exchange rate comparison, the family confirmation
   link and the development checkout. No sign-in needed to read them. */
import { PublicNav } from '@/components/roles/public-nav';
import '@/components/roles/roles.css';

export default function PublicLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <PublicNav />
      <main className="pub-main">{children}</main>
    </>
  );
}
