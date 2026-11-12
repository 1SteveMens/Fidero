# R0 case kit

Everything needed to run one land verification case by hand, from the first document to the released report. Built 12 November 2026 for the R0 manual service (`docs/validation-plan.md`). Backlog items EN-02, EN-06 and EN-07 in `docs/specs/04`.

| File | What it is | Backlog |
|---|---|---|
| `land-report-template.docx` | The report, sections 1 to 14, with yellow fill-in fields. Section 12, the scope and limitation statement, is locked in Word and cannot be edited | EN-02 |
| `consent-form.docx` | Consent to the sale and to filming, signed or thumbprinted at the consent meeting | EN-07 |
| `consent-video-script.docx` | What to check before the meeting, the filming rules, the script the lawyer follows, and what to do within 24 hours | EN-07 |
| `witness-sheet.docx` | Everyone else present at a consent meeting or site visit | EN-07 |
| `client-terms.docx` | The client's order and terms: what we check and do not, fee, turnaround, refunds, data, complaints. Accepted by signature or by replying "I agree to Tenmina terms CT-1" | Validation plan s1, FR-ORD-003 by hand |
| `professional-agreement.docx` | For lawyers, surveyors and runners: main terms, one schedule per role, the fee schedule, and a conflict declaration signed before each job | Validation plan s2, RUL-26, RUL-27 |
| `seller-agreement.docx` | For screened established sellers in the checked plots test: Tenmina checks every plot in full and acts for the buyer; fixed fee per plot, no success fee; the seller reports sales the same day and accepts escrow | Validation plan s4a |
| `evidence-folders.md` | One restricted folder per case, file names, fingerprints, who can open what, releasing a report, retention | EN-06 |
| `fingerprint.html` | Open in any browser. Fingerprints files (SHA-256) on the laptop without uploading anything, makes rows for the tracker, and checks a file against its fingerprint | EN-02, EN-06 |

The tracker (`../r0-tracker.xlsx`) has three tabs for the kit: **Evidence log**, **Reports released** and **Folder access**. Cases records which client terms version was accepted and when; Professionals records each agreement version and insurance check. The Review tab counts the problems they catch.

All periods, lengths and limits in the kit are working assumptions. Unknowns are marked `[TO VERIFY]`.

## How a case uses the kit

0. **Before anything.** Every professional on the case has signed the professional agreement, and signs the Schedule E declaration for this job. The client has accepted the client terms; save their signed copy or reply in folder A and record the version and date in Cases.
1. **Case opens.** Create the case folder (`evidence-folders.md` section 2). Share it with the lawyer and reviewer; record the access in the tracker.
2. **Documents arrive.** Save originals into A to D, fingerprint them the same day, paste the rows into the Evidence log.
3. **Site visit.** The surveyor and runner upload originals into F. Fingerprint and log within 24 hours. Use a witness sheet if anyone else is present.
4. **Consent meeting.** The lawyer leads with the consent form and script; the runner films. Everything goes into E within 24 hours, fingerprinted and logged.
5. **Report.** Fill in `land-report-template.docx`. Two people review: the lawyer and one Tenmina reviewer.
6. **Release.** Save the PDF, fingerprint it, log it in Reports released, and send it to the client with its fingerprint (`evidence-folders.md` section 7).
7. **Close.** Remove folder access, make sure the second copy exists, and set the deletion date.

## Before the first real case: the lawyer must approve

The consent form, script, witness sheet, client terms, professional agreement and seller agreement are marked **DRAFT FOR LAWYER REVIEW**. Do not use them until the lawyer has approved them. Ask the lawyer:

1. Is the consent form right for each kind of land we will see: family land, stool land, skin land and individually held land? Who must sign for each?
2. Does section 7 (reader and interpreter) meet the Illiterates Protection Act, 1912 (CAP 262), for people who sign by thumbprint `[TO VERIFY]`?
3. Do we need the form in Twi, Ga, Ewe or other languages, or is reading it aloud with an interpreter enough?
4. How long must we keep consent videos, forms and reports, and when must we delete them under the Data Protection Act 2012 (Act 843)? This fills the `[retention period]` fields.
5. Should we record full ID numbers for people giving consent and for witnesses, or is "ID seen" enough?
6. Should the family receive a copy of the signed form?
7. Do we need to register with the Data Protection Commission before the first case (EN-08)?
8. Is the scope and limitation statement (template section 12) right? It needs the insurer's agreement too, and the insurance policy reference once cover is in place.
9. Client terms: are the refund rules in section 7 fair and enforceable, and does limiting liability to the fee hold for a client who lives abroad? Do consumer laws in the client's country (UK, US, Canada, EU) change anything?
10. Client terms: is accepting by a WhatsApp or email reply enough, or must the client sign?
    Also section 9, paying the seller safely: do the payee lock, the cooling-off period and refunds only to the source account need to sit in the escrow agreement with the bank as well? And clauses 9.6 to 9.8 on exchange: is "the seller is paid in cedis" right for buyers who live abroad, given the Bank of Ghana's 2025 notice on foreign currency invoices to non-residents (Q-32 in the specs)?
11. Professional agreement: does it keep lawyers, surveyors and runners as independent contractors, not employees, under Ghana's labour and tax law? What withholding tax applies to each, and is the payment period (10 working days) right?
12. Professional agreement: is paying a visit in full when the professional leaves for safety (clause 5.3) and holding pay only during a recorded misconduct review (clause 2.6) workable?
13. Seller agreement and client terms clause 1.3: is a seller-paid check of a plot later reported to a buyer in the buyer's name sound, and is the disclosure to buyers enough? Does Act 1047 require Tenmina itself to hold a Real Estate Agency Council licence to offer checked plots?
14. Both: is mediation in Accra under the Alternative Dispute Resolution Act, 2010 (Act 798) the right route for disputes, and is Tenmina's company name ready to go in the documents?

When the lawyer approves, remove the draft line from each file's header, record the approval date in the decision log, and change the version (for example CF-1 to CF-2, CT-1 to CT-2) if the wording changed. A new version also goes into the tracker's Lists tab.

## Changing the files

The Word files and the tracker are generated, so changes stay consistent:

```bash
cd docs/operations/source
node case-kit.js && python3 finish.py   # the seven Word files
python3 tracker.py                      # the tracker
```

`finish.py` locks the scope statement. A new scope statement wording is a new version (S2): change `SCOPE` and `SCOPE_VERSION` in `case-kit.js`, `VERSION` in `finish.py`, and the ScopeVersion list in `tracker.py`, with the lawyer's and the insurer's approval recorded (FR-ADM-004). Small edits for one case are made in Word, in the copy for that case, never in the template.

Microsoft Word honours the lock on section 12. Other editors (Google Docs, Pages, LibreOffice) may not, so fill the template in Word. Whatever the editor, the second reviewer reads section 12 against this README's version before release.
