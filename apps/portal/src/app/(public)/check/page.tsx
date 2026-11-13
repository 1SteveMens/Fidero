'use client';
/* Check a report (SCR-PTL-15, FR-RPT-008): anyone checks a PDF against the fingerprint Tenmina stored.
   The PDF is hashed in this browser; only its SHA-256 is sent. The answer is match or no match, never
   the report's content or the client's name. */
import { useState } from 'react';
import { Button, Field, Input, ProblemBox } from '@tenmina/web-ui';
import { send, sha256Hex } from '@/components/roles/files';

type Result = { match: boolean; released_on: string | null; superseded?: boolean };

export default function CheckReport() {
  const [reference, setReference] = useState('');
  const [sha, setSha] = useState('');
  const [fileName, setFileName] = useState('');
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<Result | null>(null);

  async function take(f?: File | null) {
    if (!f) return;
    setResult(null);
    setFileName(f.name);
    setSha(await sha256Hex(f));
  }
  const validSha = /^[0-9a-fA-F]{64}$/.test(sha.trim());

  async function check(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null); setResult(null);
    try {
      const body = JSON.stringify(reference.trim() ? { reference: reference.trim(), sha256: sha.trim().toLowerCase() } : { sha256: sha.trim().toLowerCase() });
      setResult(await send<Result>('POST', reference.trim() ? '/v1/report-verifications' : '/v1/fingerprint-checks', body, { 'Content-Type': 'application/json' }));
    } catch (err) { setError(err); } finally { setBusy(false); }
  }

  return (
    <form className="stack" onSubmit={check} style={{ maxWidth: 640 }}>
      <div>
        <p className="label" style={{ margin: 0 }}>Check a report</p>
        <h1>Is this Tenmina report genuine?</h1>
        <p className="muted">Drop the PDF you were given. Your browser works out its fingerprint (SHA-256); the file itself never leaves your device.</p>
      </div>
      <Field label="Report reference (on the cover, optional)"><Input value={reference} onChange={(e) => setReference(e.target.value)} placeholder="TMC-GH-2026-00021-R1" /></Field>
      <div className={`drop ${over ? 'over' : ''}`} onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={(e) => { e.preventDefault(); setOver(false); take(e.dataTransfer.files?.[0]); }}>
        <input type="file" accept="application/pdf" aria-label="Choose the PDF" onChange={(e) => take(e.target.files?.[0])} />
        {fileName ? <>Fingerprint taken from <span className="mono">{fileName}</span></> : 'Drop the PDF here, or tap to choose it'}
      </div>
      <Field label="Or paste the SHA-256"><Input className="input mono" value={sha} onChange={(e) => { setSha(e.target.value); setFileName(''); setResult(null); }} spellCheck={false} /></Field>
      {sha && !validSha ? <span className="muted">A SHA-256 has 64 characters, 0 to 9 and a to f.</span> : null}
      <Button variant="primary" type="submit" busy={busy} disabled={!validSha}>Check</Button>
      <ProblemBox error={error} />
      {result ? (
        result.match ? (
          <div className="result-yes" role="status">
            <div style={{ fontSize: 22, fontWeight: 800 }}>✓ It matches</div>
            <div>This is the document Tenmina released{result.released_on ? ` on ${new Date(result.released_on).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })}` : ''}.</div>
            {result.superseded ? <div><strong>A newer version replaces it.</strong> Ask the person who gave it to you for the latest one.</div> : null}
          </div>
        ) : (
          <div className="result-no" role="status">
            <div style={{ fontSize: 22, fontWeight: 800 }}>✕ No match</div>
            <div>This file is not a report Tenmina released{reference.trim() ? ' under that reference' : ''}. It may have been changed. Do not rely on it, and contact Tenmina.</div>
          </div>
        )
      ) : null}
    </form>
  );
}
