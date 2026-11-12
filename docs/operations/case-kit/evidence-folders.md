# Evidence folders (EN-06)

How R0 cases keep their evidence until the platform takes over in R1. Every R0 case follows these rules. The goal is the same as the platform's (BR-06): every piece of evidence is tamper-evident, nothing is overwritten, and only the people on the case can see it.

All periods and limits here are working assumptions, not verified requirements. The lawyer sets the retention period `[TO VERIFY]`.

## 1. Where the folders live

- One cloud drive account owned by Tenmina, not by a person: a business Google Workspace or Microsoft 365 account `[TO VERIFY which]`. It must keep version history and allow sharing one folder with named people.
- Turn on two-step sign-in for every account that can open case folders.
- A second copy of every case folder on an encrypted external drive, updated every week, kept by the founder away from the laptop. Record the copy in the tracker's Evidence log (column K).
- Never use personal WhatsApp, personal email or a personal phone gallery as the place evidence is kept.

## 2. One folder per case

Name the folder with the case ID and the locality only. Never put the client's name in a folder or file name: names show up in sharing emails and notifications.

```
Cases/
  C014 Kasoa/
    A Client documents/     documents the client or seller supplied, including earlier transfers
    B Searches/             Lands Commission search results and receipts
    C Survey/               surveyor's report, coordinates, sketches
    D Overlays/             overlay maps and their sources
    E Consent/              consent form, witness sheet, consent video   (most restricted)
    F Site visit/           site photos and videos, site visit notes
    R Report/               drafts and released reports
```

The letters A to F match the report's appendices (template section 14). R is the report itself.

## 3. File names

```
C014_F_2027-01-20_pillar-ne.jpg
│    │ │          └ a few words, lower case, hyphens
│    │ └ date the photo was taken or the document was received
│    └ folder letter
└ case ID
```

- Released reports: `C014_R_2027-02-08_report-v1.pdf`. A correction is `report-v2`, never a replacement of v1.
- Renaming a file does not change its fingerprint. Editing it does.
- The fingerprint tool warns when a name does not follow the rule.

## 4. Getting files in without changing them

- Upload photos and videos from the phone with the cloud drive app, choosing the original quality. **Never send evidence by WhatsApp**: it compresses files, so the version you keep is not the original.
- Never edit, crop, rotate, filter, trim or compress evidence. If a copy needs marking up for the report, save the marked copy as a new file with `-marked` at the end of its name, and keep the original.
- Scan paper documents to PDF at the office or with the drive app's scanner. Keep the paper original in the locked case file.
- Phones: camera location tag on, date and time set to automatic. From R2 the Tenmina Field app does this and signs each photo; until then the fingerprint is the protection.

## 5. Fingerprint and log within 24 hours

1. Open `case-kit/fingerprint.html` in a browser on the laptop. It works offline; nothing is uploaded.
2. Type the case ID and your name, then drop the case folder (or the new files) on it.
3. Click **Copy rows for the Evidence log**, open the tracker's **Evidence log** tab, click the first empty cell in column A and paste.
4. Fill in what each file shows, who took or received it, when and where.
5. Check the two grey columns:
   - **Fingerprint looks right?** must say Yes.
   - **Same file elsewhere?** must be blank. "Another case" means the same file is logged under a different case: a reused photo, or a document that turns up in two deals. Stop and find out why before the report goes out. "Twice in this case" usually means the file was pasted twice; delete the extra row.
   - **Logged within 24 hours?** should say Yes.

Fingerprints logged late prove less. The tracker records the logging date, and the report reviewer checks that evidence was logged within 24 hours of capture or receipt.

## 6. Who can open a folder

| Folder | Who may open it |
|---|---|
| Whole case folder | The founder, the case's lawyer, the case's Tenmina reviewer |
| A, B, C, D, F | Also the case's surveyor and runner, to add files |
| E Consent | Only the founder, the lawyer and the reviewer. Never the surveyor, runner or client |
| R Report | The client receives the released PDF by email, not access to the folder |

- Share with named people only. Never use "anyone with the link".
- Give "add files" access to people who upload evidence and "view only" to everyone else.
- Record every grant and removal in the tracker's **Folder access** tab.
- Remove access for the surveyor and runner when the report is released, and for everyone except the founder when the case closes.

## 7. Releasing a report

1. The report is built from `case-kit/land-report-template.docx`. Do not copy an older report.
2. No highlighted fill-in text remains. Section 12 is unchanged and shows its scope statement version.
3. The lawyer and the second reviewer have signed (section 13).
4. Save as PDF: `C014_R_<date>_report-v1.pdf` in R Report.
5. Fingerprint the PDF and log it in the tracker's **Reports released** tab, with the scope statement version and both reviewers.
6. Send the PDF and its fingerprint to the client. Tell them that anyone can check the report against the fingerprint with Tenmina.
7. Never change a released PDF. A correction is a new version with a reason, logged as a new row, and the client is told.

## 8. How long files are kept

- Keep each case for the retention period the lawyer sets `[TO VERIFY]`, then delete both copies and record the deletion in the Evidence log notes.
- Keep a case longer only if there is a dispute, a legal hold, or the lawyer says so.
- Anyone recorded may ask what Tenmina holds about them (Data Protection Act 2012, Act 843). The founder answers within the period the law sets `[TO VERIFY]`.

## 9. When R1 arrives

The platform's evidence store replaces these folders (FR-EVD-001 to FR-EVD-006). The migration (EN-30) moves each R0 file with its logged fingerprint and checks that every fingerprint still matches. A file whose fingerprint does not match is flagged, not moved silently.
