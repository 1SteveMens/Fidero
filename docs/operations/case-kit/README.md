# R0 case kit

Everything needed to run one land verification case by hand, from the first document to the released report. Built 12 November 2026 for the R0 manual service (`docs/validation-plan.md`). Backlog items EN-02, EN-06 and EN-07 in `docs/specs/04`.

| File | What it is | Backlog |
|---|---|---|
| `land-report-template.docx` | The report, sections 1 to 14, with yellow fill-in fields. Section 12, the scope and limitation statement, is locked in Word and cannot be edited | EN-02 |
| `consent-form.docx` | Consent to the sale and to filming, signed or thumbprinted at the consent meeting | EN-07 |
| `consent-video-script.docx` | What to check before the meeting, the filming rules, the script the lawyer follows, and what to do within 24 hours | EN-07 |
| `witness-sheet.docx` | Everyone else present at a consent meeting or site visit | EN-07 |
| `evidence-folders.md` | One restricted folder per case, file names, fingerprints, who can open what, releasing a report, retention | EN-06 |
| `fingerprint.html` | Open in any browser. Fingerprints files (SHA-256) on the laptop without uploading anything, makes rows for the tracker, and checks a file against its fingerprint | EN-02, EN-06 |

The tracker (`../r0-tracker.xlsx`) has three tabs for the kit: **Evidence log**, **Reports released** and **Folder access**. The Review tab counts the problems they catch.

All periods, lengths and limits in the kit are working assumptions. Unknowns are marked `[TO VERIFY]`.

## How a case uses the kit

1. **Case opens.** Create the case folder (`evidence-folders.md` section 2). Share it with the lawyer and reviewer; record the access in the tracker.
2. **Documents arrive.** Save originals into A to D, fingerprint them the same day, paste the rows into the Evidence log.
3. **Site visit.** The surveyor and runner upload originals into F. Fingerprint and log within 24 hours. Use a witness sheet if anyone else is present.
4. **Consent meeting.** The lawyer leads with the consent form and script; the runner films. Everything goes into E within 24 hours, fingerprinted and logged.
5. **Report.** Fill in `land-report-template.docx`. Two people review: the lawyer and one Tenmina reviewer.
6. **Release.** Save the PDF, fingerprint it, log it in Reports released, and send it to the client with its fingerprint (`evidence-folders.md` section 7).
7. **Close.** Remove folder access, make sure the second copy exists, and set the deletion date.

## Before the first real case: the lawyer must approve

The consent form, script and witness sheet are marked **DRAFT FOR LAWYER REVIEW**. Do not use them with a family or traditional authority until the lawyer has approved them. Ask the lawyer:

1. Is the consent form right for each kind of land we will see: family land, stool land, skin land and individually held land? Who must sign for each?
2. Does section 7 (reader and interpreter) meet the Illiterates Protection Act, 1912 (CAP 262), for people who sign by thumbprint `[TO VERIFY]`?
3. Do we need the form in Twi, Ga, Ewe or other languages, or is reading it aloud with an interpreter enough?
4. How long must we keep consent videos, forms and reports, and when must we delete them under the Data Protection Act 2012 (Act 843)? This fills the `[retention period]` fields.
5. Should we record full ID numbers for people giving consent and for witnesses, or is "ID seen" enough?
6. Should the family receive a copy of the signed form?
7. Do we need to register with the Data Protection Commission before the first case (EN-08)?
8. Is the scope and limitation statement (template section 12) right? It needs the insurer's agreement too, and the insurance policy reference once cover is in place.

When the lawyer approves, remove the draft line from each file's header, record the approval date in the decision log, and change the version (for example CF-1 to CF-2) if the wording changed.

## Changing the files

The Word files and the tracker are generated, so changes stay consistent:

```bash
cd docs/operations/source
node case-kit.js && python3 finish.py   # the four Word files
python3 tracker.py                      # the tracker
```

`finish.py` locks the scope statement. A new scope statement wording is a new version (S2): change `SCOPE` and `SCOPE_VERSION` in `case-kit.js`, `VERSION` in `finish.py`, and the ScopeVersion list in `tracker.py`, with the lawyer's and the insurer's approval recorded (FR-ADM-004). Small edits for one case are made in Word, in the copy for that case, never in the template.

Microsoft Word honours the lock on section 12. Other editors (Google Docs, Pages, LibreOffice) may not, so fill the template in Word. Whatever the editor, the second reviewer reads section 12 against this README's version before release.
