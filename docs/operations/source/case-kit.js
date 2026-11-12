// Builds the R0 case kit Word files (EN-02 report template, EN-07 consent kit,
// client terms and the professional services agreement).
// Run from this folder:  node case-kit.js && python3 finish.py
// Needs the `docx` npm package (npm install -g docx). Output goes to ../case-kit/.
// Text in [[double brackets]] becomes a highlighted fill-in field.

const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, WidthType, ShadingType,
  AlignmentType, HeadingLevel, Header, Footer, PageNumber, PageBreak, BorderStyle,
  LevelFormat, PageOrientation, TabStopType, VerticalAlign,
} = require('docx');

const OUT = path.join(__dirname, '..', 'case-kit');
const FONT = 'Arial';
const INK = '0B0B0B';
const MUTED = '5F5C55';
const LINE = 'C9C5BC';
const TINT = 'F3F1EC';
const VERDICT = { Green: 'E3F6D3', Amber: 'FFF4C2', Red: 'FFDCD9' };
const A4 = { width: 11906, height: 16838 };
const MARGIN = 1134; // 2 cm
const W = A4.width - 2 * MARGIN; // 9638 portrait content width
const WL = A4.height - 2 * MARGIN; // 14570 landscape content width

// ---------- text helpers ----------
function runs(text, o = {}) {
  const out = [];
  String(text).split(/(\[\[[^\]]+\]\])/).forEach((part) => {
    if (!part) return;
    const m = part.match(/^\[\[(.+)\]\]$/);
    if (m) out.push(new TextRun({ text: `[${m[1]}]`, font: FONT, size: o.size || 20, bold: o.bold, highlight: 'yellow' }));
    else out.push(new TextRun({ text: part, font: FONT, size: o.size || 20, bold: o.bold, italics: o.italics, color: o.color }));
  });
  return out;
}
const P = (text, o = {}) => new Paragraph({
  children: Array.isArray(text) ? text : runs(text, o),
  alignment: o.align,
  spacing: o.line === false ? { before: o.before ?? 0, after: o.after ?? 120 } : { before: o.before ?? 0, after: o.after ?? 120, line: o.line ?? 276 },
  keepNext: o.keepNext,
  border: o.rule ? { bottom: { style: BorderStyle.SINGLE, size: 6, color: INK, space: 4 } } : undefined,
});
const H1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun({ text: t })] });
const H2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun({ text: t })] });
const note = (t) => P(t, { color: MUTED, italics: true, size: 18 });
const bullet = (t, o = {}) => new Paragraph({ numbering: { reference: 'bullets', level: 0 }, children: runs(t, o), spacing: { after: 60, line: 264 } });
const numbered = (t, ref = 'steps') => new Paragraph({ numbering: { reference: ref, level: 0 }, children: runs(t), spacing: { after: 80, line: 264 } });
const say = (t) => new Paragraph({
  children: [new TextRun({ text: 'Say: ', font: FONT, size: 20, bold: true }), ...runs(t)],
  indent: { left: 340 },
  border: { left: { style: BorderStyle.SINGLE, size: 18, color: INK, space: 8 } },
  spacing: { before: 60, after: 120, line: 276 },
});
const spacer = (after = 120) => new Paragraph({ children: [], spacing: { after } });
const pageBreak = () => new Paragraph({ children: [new PageBreak()] });

// ---------- tables ----------
const border = { style: BorderStyle.SINGLE, size: 4, color: LINE };
const borders = { top: border, bottom: border, left: border, right: border };
function cell(content, width, o = {}) {
  const paras = (Array.isArray(content) ? content : [content]).map((c) =>
    c instanceof Paragraph ? c : P(c, { bold: o.bold, size: o.size, after: 0, color: o.color }));
  return new TableCell({
    children: paras,
    width: { size: width, type: WidthType.DXA },
    borders,
    shading: o.fill ? { type: ShadingType.CLEAR, color: 'auto', fill: o.fill } : undefined,
    margins: { top: 70, bottom: 70, left: 110, right: 110 },
    verticalAlign: o.valign || VerticalAlign.TOP,
    columnSpan: o.span,
  });
}
function table(widths, rows, o = {}) {
  const total = widths.reduce((a, b) => a + b, 0);
  return new Table({
    width: { size: total, type: WidthType.DXA },
    columnWidths: widths,
    rows: rows.map((r, i) => {
      const head = o.header !== false && i === 0;
      return new TableRow({
        tableHeader: head,
        cantSplit: true,
        height: o.rowHeight && !head ? { value: o.rowHeight, rule: 'atLeast' } : undefined,
        children: r.map((c, j) => {
          if (c && c.cell) return cell(c.text, widths[j], c);
          return cell(c ?? '', widths[j], head ? { bold: true, fill: TINT, size: 18 } : { size: o.size || 20, fill: o.firstColFill && j === 0 ? TINT : undefined, bold: o.firstColBold && j === 0 });
        }),
      });
    }),
  });
}
// label | value rows, no header row
const fields = (rows, w1 = 3000, total = W) => table([w1, total - w1], rows, { header: false, firstColFill: true, firstColBold: true });

// ---------- document ----------
function doc({ title, headerText, children, landscape = false, draft = false }) {
  const headerKids = [P(headerText, { size: 16, color: MUTED, after: 0 })];
  if (draft) headerKids.push(P('DRAFT FOR LAWYER REVIEW. Do not use until the lawyer has approved this version.', { size: 16, bold: true, after: 0 }));
  return new Document({
    creator: 'Tenmina', title,
    styles: {
      default: { document: { run: { font: FONT, size: 20 } } },
      paragraphStyles: [
        { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
          run: { font: FONT, size: 28, bold: true, color: INK },
          paragraph: { spacing: { before: 320, after: 140 }, keepNext: true, outlineLevel: 0 } },
        { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true,
          run: { font: FONT, size: 22, bold: true, color: INK },
          paragraph: { spacing: { before: 200, after: 80 }, keepNext: true, outlineLevel: 1 } },
      ],
    },
    numbering: { config: [
      { reference: 'bullets', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 360, hanging: 240 } } } }] },
      ...['steps', 'steps2', 'steps3', 'steps4', 'steps5'].map((reference) => ({ reference, levels: [{ level: 0, format: LevelFormat.DECIMAL, text: '%1.', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 400, hanging: 300 } } } }] })),
    ] },
    sections: [{
      properties: { page: {
        size: landscape ? { width: A4.width, height: A4.height, orientation: PageOrientation.LANDSCAPE } : A4,
        margin: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN, header: 560, footer: 560 },
      } },
      headers: { default: new Header({ children: headerKids }) },
      footers: { default: new Footer({ children: [new Paragraph({
        tabStops: [{ type: TabStopType.RIGHT, position: landscape ? WL : W }],
        children: [
          new TextRun({ text: 'Confidential. Tenmina', font: FONT, size: 16, color: MUTED }),
          new TextRun({ text: '\tPage ', font: FONT, size: 16, color: MUTED }),
          new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 16, color: MUTED }),
          new TextRun({ text: ' of ', font: FONT, size: 16, color: MUTED }),
          new TextRun({ children: [PageNumber.TOTAL_PAGES], font: FONT, size: 16, color: MUTED }),
        ] })] }) },
      children,
    }],
  });
}
const wordmark = () => P([new TextRun({ text: 'tenmina', font: FONT, size: 36, bold: true, color: INK })], { after: 80, line: false });
const titleBlock = (t, sub) => [wordmark(), P([new TextRun({ text: t, font: FONT, size: 40, bold: true })], { after: 120, line: false }), sub ? P(sub, { color: MUTED, after: 240, rule: true }) : spacer()];

// =====================================================================
// EN-02 Land verification report template
// =====================================================================
const grade = (red, amber, green) => table([1300, W - 1300], [
  ['Verdict', 'When this section gets it'],
  [{ cell: true, text: 'Red', fill: VERDICT.Red, bold: true }, red],
  [{ cell: true, text: 'Amber', fill: VERDICT.Amber, bold: true }, amber],
  [{ cell: true, text: 'Green', fill: VERDICT.Green, bold: true }, green],
]);
const evidence = (items) => table([5600, 2700, 1338], [
  ['Evidence', 'Where it is (appendix and file)', 'Attached?'],
  ...items.map((e) => [e, '[[Appendix, file name]]', '[[Yes / No]]']),
]);
const sectionVerdict = () => fields([['Section verdict', '[[Green / Amber / Red]]'], ['Signed off by', '[[Name, role]]']], 3000);

const SECTIONS = [
  { n: 4, t: 'Plot identity', owner: 'Surveyor',
    checks: 'The plot the client is being sold is the plot on the site plan, and that plot is the one the surveyor found on the ground.',
    ev: ['Copy of the site plan supplied by the seller', 'Ghana Post GPS address', "Surveyor's coordinates of each pillar found", 'Satellite image with the site plan boundary overlaid', 'Photos of each pillar and of the plot from each corner'],
    g: ['The ground does not match the site plan.', 'Pillars are missing but the boundary is otherwise consistent.', 'Ground, plan and coordinates agree.'] },
  { n: 5, t: 'Lands Commission searches', owner: 'Lawyer',
    checks: "Official searches at the Lands Commission on the plot and on the seller's name: registered interests, caveats, pending applications and previous transfers.",
    ev: ['Official search result on the plot, with the Lands Commission stamp and date', "Official search result on the seller's name", 'Receipts for search fees', "Lawyer's note on what the results mean"],
    g: ['Another person holds a registered interest the seller cannot explain, or a caveat blocks transfer.', 'The search is pending or the record is incomplete.', "The record is consistent with the seller's claim, or the plot is unregistered customary land with no adverse entry."] },
  { n: 6, t: "Surveyor's report", owner: 'Surveyor',
    checks: "The licensed surveyor confirms the plot's position against the cadastral record and neighbouring plots, and notes overlaps.",
    ev: ["Surveyor's signed report with licence number", 'Cadastral extract or composite plan, if available', 'Sketch showing the plot and its neighbours', 'Any overlap measured in metres'],
    g: ['The plot overlaps a neighbour or a registered plot.', 'The overlap is small and the surveyor advises it can be corrected.', 'No overlap.'] },
  { n: 7, t: 'Overlay checks', owner: 'Tenmina reviewer',
    checks: "Whether the plot falls within a government acquisition, a road reserve, a wetland, a flood zone, a known dispute area, or a zoning that does not allow the client's intended use.",
    ev: ['Overlay map for each layer checked, with source and date', 'Planning scheme extract or local assembly confirmation, where available', 'Flood and wetland indicators from satellite imagery and site observation', 'Note on any known dispute in the area, with source'],
    g: ['The plot is inside an acquisition, road reserve or protected wetland.', 'The plot is near the boundary of one, or zoning is uncertain.', 'Clear.'] },
  { n: 8, t: 'Seller authority and consent', owner: 'Lawyer',
    checks: 'Who the seller is, what interest they hold, and whether the people who must consent have consented.',
    ev: ["Seller's identity document", "Document showing the seller's interest: allocation note, indenture, lease or family resolution", 'Written confirmation from the stool, skin or family head that the seller may sell this plot', 'Signed consent form from the required parties (Tenmina consent form)', 'Video recording of the consent meeting, with its fingerprint', 'Witness sheet for the consent meeting', "Lawyer's note on who else may need to consent"],
    g: ['The seller cannot show an interest, or the authority denies the sale.', 'Consent is promised but not yet recorded.', 'The interest is shown and consent is signed and recorded.'] },
  { n: 9, t: 'Chain of ownership', owner: 'Lawyer',
    checks: 'How the seller came to hold the plot, and whether the chain has gaps.',
    ev: ['Copies of previous transfers, indentures and receipts', "Lawyer's summary of the chain, with dates", 'Any inconsistency noted'],
    g: ['A previous transfer shows the plot was sold to someone else and not recovered.', 'Documents are missing but the authority confirms the chain.', 'The chain is complete.'] },
  { n: 10, t: 'Occupation and ground conditions', owner: 'Surveyor and runner',
    checks: 'Who is on the land now, any structures, any sign of dispute or land guard activity, access, and physical conditions that affect building.',
    ev: ['Site visit notes with date and names of visitors', 'Photos of any structure, fence or marking', 'Notes of conversations with neighbours, with no personal data beyond what is needed', 'Access route and road condition'],
    g: ['The plot is occupied by someone claiming ownership, or there was any threat to the team.', 'There are minor encroachments.', 'Vacant and undisputed.'] },
];

const SCOPE_VERSION = 'S1';
const SCOPE = [
  'This report sets out the results of the checks listed in section 3, carried out on the dates stated, using the documents the client supplied and the public and official records available to Tenmina on those dates. It describes the position as found on those dates only.',
  'The report does not guarantee title. Title to land in Ghana can only be confirmed by registration at the Lands Commission, and registered title can be challenged. The report does not replace legal advice on the purchase agreement, which the client should obtain from the lawyer named in this report or another lawyer of their choice.',
  'The report relies on records held by third parties, including the Lands Commission, traditional authorities and local assemblies. Tenmina has not verified the completeness of those records and cannot do so. The report relies on statements made by the seller, the traditional authority and witnesses, which Tenmina has recorded but cannot independently prove.',
  "The report covers only the plot described on the cover page and only the matters listed in sections 4 to 10. Anything not listed is outside scope. Tenmina's liability for this report is limited to the fee paid for it, except where the law does not allow that limit. Tenmina holds professional indemnity insurance in respect of this report [policy reference TO VERIFY].",
  "The report is for the named client only and may not be relied on by any other person without Tenmina's written agreement.",
];

function reportTemplate() {
  const k = [];
  // 1 Cover
  k.push(...titleBlock('Land verification report', 'Prepared for the named client only. Read section 12, the scope and limitation statement, before relying on this report.'));
  k.push(table([W], [[{ cell: true, text: [P([new TextRun({ text: 'VERDICT', font: FONT, size: 18, bold: true, color: MUTED })], { after: 60, line: false }), P([new TextRun({ text: '[GREEN / AMBER / RED]', font: FONT, size: 56, bold: true, highlight: 'yellow' })], { after: 60, line: false }), P('Shade this box green, amber or red to match.', { size: 16, color: MUTED, after: 0 })], fill: TINT }]], { header: false }));
  k.push(spacer(200));
  k.push(fields([
    ['Report reference', '[[TMN-GH-YYYY-NNNN]]'],
    ['Case ID', '[[C001]]'],
    ['Report date', '[[Day Month Year]]'],
    ['Client', '[[Full name, country of residence, email]]'],
    ['Plot', '[[Locality, plot number, site plan reference]]'],
    ['Ghana Post GPS address', '[[XX-0000-0000]]'],
    ['Seller', '[[Name and capacity]]'],
    ['Searches dated', '[[Date of each search]]'],
    ['Site visit dated', '[[Date]]'],
    ['Lawyer', '[[Name, Ghana Bar licence number]]'],
    ['Surveyor', '[[Name, licence number]]'],
  ]));
  k.push(spacer(160));
  k.push(note('Validity: this report describes the position on the dates of the searches and the site visit. It is not a guarantee of future events.'));
  k.push(H2('Document control'));
  k.push(table([1100, 1700, 1500, 3238, 2100], [
    ['Version', 'Released on', 'Scope statement', 'Reason for this version', 'Second reviewer'],
    ['[[1]]', '[[Date]]', SCOPE_VERSION, 'First release', '[[Name]]'],
  ]));
  k.push(note('A released report is never changed. A correction is a new version with its reason, a new fingerprint, and a message to the client.'));
  k.push(pageBreak());

  // 2 Summary
  k.push(H1('2. Summary'));
  k.push(fields([['Verdict', '[[Green / Amber / Red]]']]));
  k.push(H2('Why'));
  ['[[First reason]]', '[[Second reason]]', '[[Third reason, up to five]]'].forEach((t) => k.push(numbered(t)));
  k.push(H2('Before you pay'));
  k.push(P('[[Conditions the client must meet before paying, for amber or green. Write "None" for red.]]'));
  k.push(H2('Recommended next step'));
  k.push(P('[[One or two sentences]]'));
  k.push(note('Keep this section to one page. Write for a reader who will read nothing else.'));
  k.push(pageBreak());

  // 3 Scope of engagement
  k.push(H1('3. Scope of engagement'));
  k.push(fields([
    ['What the client asked us to check', '[[In the client\'s words, then ours]]'],
    ['Searches', '[[Each search, with the date lodged and the date of the result]]'],
    ['Site visit', '[[Date, who attended]]'],
    ['Consent meeting', '[[Date, place, who attended]]'],
    ['Outside scope', '[[Anything asked for that we did not check, and why. Write "Nothing" if so.]]'],
  ], 3400));
  k.push(H2('Documents the client supplied'));
  k.push(table([5600, 2000, 2038], [['Document', 'Received on', 'Appendix A file'], ['[[Document]]', '[[Date]]', '[[File name]]'], ['[[Document]]', '[[Date]]', '[[File name]]'], ['[[Document]]', '[[Date]]', '[[File name]]']]));

  // 4-10
  SECTIONS.forEach((s) => {
    k.push(pageBreak());
    k.push(H1(`${s.n}. ${s.t}`));
    k.push(P([new TextRun({ text: 'Section owner: ', font: FONT, size: 18, bold: true, color: MUTED }), new TextRun({ text: s.owner, font: FONT, size: 18, color: MUTED })]));
    k.push(H2('What we checked'));
    k.push(P(s.checks));
    k.push(H2('What we found'));
    k.push(P('[[Findings in plain English. Facts first, then what they mean for the client.]]'));
    k.push(H2('Evidence'));
    k.push(evidence(s.ev));
    k.push(H2('How this section is graded'));
    k.push(grade(...s.g));
    k.push(spacer(120));
    k.push(sectionVerdict());
  });

  // 11
  k.push(pageBreak());
  k.push(H1('11. Verdict and conditions'));
  k.push(table([5000, 2400, 2238], [
    ['Section', 'Verdict', 'Owner'],
    ...SECTIONS.map((s) => [`${s.n}. ${s.t}`, '[[Green / Amber / Red]]', s.owner]),
    [{ cell: true, text: 'Overall verdict', bold: true, fill: TINT }, { cell: true, text: '[[Green / Amber / Red]]', bold: true, fill: TINT }, { cell: true, text: '', fill: TINT }],
  ]));
  k.push(note('The overall verdict cannot be green if any section from 4 to 10 is red.'));
  k.push(H2('What must happen before the client pays'));
  k.push(table([4300, 2300, 3038], [['Step', 'Who does it', 'Evidence that closes it'], ['[[Step]]', '[[Name or role]]', '[[Document, photo or search]]'], ['[[Step]]', '[[Name or role]]', '[[Document, photo or search]]']]));
  k.push(H2('Conditions for the purchase agreement and escrow'));
  k.push(P('[[For green: conditions such as consent documents delivered before money is released.]]'));
  k.push(H2('Recommended next steps'));
  k.push(P('[[Escrow, conveyancing, title registration]]'));

  // 12 Scope statement, locked by finish.py
  k.push(pageBreak());
  k.push(H1('12. Scope and limitation statement'));
  k.push(note(`Version ${SCOPE_VERSION}. This wording is locked and cannot be edited in this template. It changes only with the lawyer's and the insurer's written approval, as a new version.`));
  k.push(P('@@SCOPE_START@@', { after: 0 }));
  SCOPE.forEach((t) => k.push(P(t, { after: 160, line: 288 })));
  k.push(P(`Scope statement version ${SCOPE_VERSION}.`, { size: 16, color: MUTED }));
  k.push(P('@@SCOPE_END@@', { after: 0 }));

  // 13
  k.push(H1('13. Signatures'));
  k.push(table([1900, 2700, 2000, 1738, 1300], [
    ['Role', 'Name', 'Licence number', 'Signature', 'Date'],
    ['Lawyer', '[[Name]]', '[[Number]]', '', '[[Date]]'],
    ['Surveyor', '[[Name]]', '[[Number]]', '', '[[Date]]'],
    ['Tenmina reviewer', '[[Name]]', 'Not applicable', '', '[[Date]]'],
  ], { rowHeight: 620 }));
  k.push(note('Two people review every report before release: the lawyer who signed the legal sections and one other Tenmina reviewer.'));

  // 14
  k.push(pageBreak());
  k.push(H1('14. Appendices'));
  k.push(note('Each appendix matches a folder in the case\'s evidence folder (see evidence-folders.md). Every file listed has its fingerprint in the tracker\'s Evidence log.'));
  k.push(table([900, 5200, 3538], [
    ['', 'Appendix', 'Evidence folder'],
    ['A', 'Documents supplied by the client, including earlier transfers', 'A Client documents'],
    ['B', 'Search results and receipts', 'B Searches'],
    ['C', "Surveyor's full report and coordinates", 'C Survey'],
    ['D', 'Overlay maps', 'D Overlays'],
    ['E', 'Consent forms, witness sheets and the video recording reference', 'E Consent'],
    ['F', 'Site visit photos with time and GPS position', 'F Site visit'],
    ['G', 'Data handling note', 'This report'],
  ]));
  k.push(H2('Appendix G. Data handling note'));
  k.push(P('Tenmina keeps the personal data in this report and its evidence (names, identity documents, photos and video of the seller, the family or traditional authority and witnesses) only to verify this plot for the client. It is stored in a restricted folder that only the people working on this case can open, with a second copy kept securely. It is kept for [[retention period, TO VERIFY with the lawyer]] and then deleted, unless the law requires it to be kept longer. This follows the Data Protection Act 2012 (Act 843). Anyone named in this report may ask Tenmina what it holds about them at [[Tenmina contact email]].'));
  return doc({ title: 'Land verification report template', headerText: 'Tenmina · Land verification report · [Report reference] · Template EN-02, version 1', children: k });
}

// =====================================================================
// EN-07 Consent kit
// =====================================================================
const yesNo = 'Yes ☐    No ☐';

function consentForm() {
  const k = [];
  k.push(...titleBlock('Consent to the sale of land and to recording', 'Read every part aloud, in a language each person understands, before anyone signs or marks it. Use one form per meeting.'));
  k.push(fields([['Case ID', '[[C001]]'], ['Form version', 'CF-1']], 3000));

  k.push(H1('1. The meeting'));
  k.push(fields([['Date', '[[Day Month Year]]'], ['Started at', '[[Time]]'], ['Place', '[[Town, house or palace, Ghana Post GPS address]]'], ['Language used', '[[e.g. Twi, Ga, Ewe, Dagbani, English]]']]));

  k.push(H1('2. The plot'));
  k.push(fields([['Locality', '[[Town or area]]'], ['Plot number', '[[Number]]'], ['Site plan reference', '[[Reference and date of the site plan shown at the meeting]]'], ['Approximate size', '[[e.g. 70 ft by 100 ft]]'], ['Ghana Post GPS address', '[[XX-0000-0000]]'], ['Neighbours or boundaries', '[[As described at the meeting]]']]));

  k.push(H1('3. The sale'));
  k.push(fields([['Seller', '[[Full name]]'], ['Seller holds the land as', '[[Individual / family member / stool or skin allocation / other]]'], ['Land is held by', '[[Family, stool, skin or individual, and its name]]'], ['Buyer', '[[Full name of the Tenmina client]]']]));
  k.push(note('Tenmina is checking this plot for the buyer. Tenmina is not the buyer or the seller, and does not hold the purchase money.'));

  k.push(H1('4. Statement of consent'));
  k.push(P('To be read aloud, then signed or marked by each person in section 5.', { italics: true, color: MUTED }));
  k.push(P('We, the persons named in section 5, confirm that:', { bold: true }));
  [
    'we have the authority to consent to dealings in the plot described in section 2 on behalf of [[the family, stool or skin]];',
    'we consent to [[seller]] selling that plot to [[buyer]];',
    'to our knowledge the plot has not been sold, leased or promised to anyone else, and is not the subject of any dispute, court case or claim, except: [[write "none" or describe]];',
    'no one has paid or promised us anything for this consent, except these customary payments: [[write "none" or list them]];',
    'this form was read and explained to us in a language we understand, and we sign or mark it freely.',
  ].forEach((t) => k.push(numbered(t, 'steps2')));

  k.push(H1('5. Persons giving consent'));
  k.push(table([2300, 1900, 2100, 2038, 1300], [
    ['Full name', 'Capacity (e.g. head of family, chief, elder)', 'ID seen (type and number)', 'Signature or thumbprint', 'Date'],
    ...Array(5).fill(['', '', '', '', '']),
  ], { rowHeight: 820 }));

  k.push(H1('6. Consent to filming and to keeping personal data'));
  k.push(P('To be read aloud before the camera starts. Each person in section 5 answers for themselves.', { italics: true, color: MUTED }));
  k.push(P('Tenmina asks to film this meeting and to keep the video, photos and this form. They are used only to show the buyer and the buyer\'s lawyer that consent was given, and, if needed, a court or the Lands Commission. Tenmina keeps them in a restricted folder, shares them with no one else, and keeps them for [[retention period, TO VERIFY with the lawyer]]. You may ask Tenmina what it holds about you, and ask for a mistake to be corrected, at [[Tenmina contact email or phone]]. This follows the Data Protection Act 2012 (Act 843). You may say no. If you say no, you will not be filmed.'));
  k.push(table([3600, 2400, 2338, 1300], [
    ['Full name', 'I agree to be filmed', 'Signature or thumbprint', 'Date'],
    ...Array(5).fill(['', yesNo, '', '']),
  ], { rowHeight: 620 }));

  k.push(H1('7. Reader and interpreter'));
  k.push(P('I, [[full name]], of [[address]], declare that I read this form over to the persons named in sections 5 and 6 in the [[language]] language, that I explained it to them, and that they appeared to understand it fully before signing or marking it.'));
  k.push(fields([['Signature', ''], ['Date', '']]));
  k.push(note('Lawyer to confirm this wording meets the Illiterates Protection Act, 1912 (CAP 262) [TO VERIFY].'));

  k.push(H1('8. Present for the buyer'));
  k.push(table([2600, 2200, 2100, 2738], [
    ['Name', 'Role', 'Licence number', 'Signature'],
    ['[[Lawyer name]]', 'Lawyer', '[[Number]]', ''],
    ['[[Name]]', 'Tenmina runner', 'Not applicable', ''],
    ['[[Name]]', '[[Second Tenmina person, required if the plot is flagged disputed]]', 'Not applicable', ''],
  ], { rowHeight: 620 }));
  k.push(P('I was present and saw each person in section 5 sign or mark this form. (Lawyer)', { size: 18 }));

  k.push(H1('9. After the meeting'));
  k.push(P('Filled in by Tenmina within 24 hours.', { italics: true, color: MUTED }));
  k.push(fields([['Meeting ended at', '[[Time]]'], ['Video file name', '[[C001_E_YYYY-MM-DD_consent-meeting.mp4]]'], ['Video fingerprint (first 12 characters)', '[[From the fingerprint tool]]'], ['Scan of this form, file name', '[[C001_E_YYYY-MM-DD_consent-form.pdf]]'], ['Copy given to the family?', yesNo]], 3800));
  return doc({ title: 'Consent form', headerText: 'Tenmina · Consent to the sale of land and to recording · Case [Case ID] · Form CF-1', children: k, draft: true });
}

function videoScript() {
  const k = [];
  k.push(...titleBlock('Consent meeting: filming guide and script', 'For the lawyer who leads the meeting and the Tenmina runner who films it. One continuous video, start to finish.'));
  k.push(fields([['Case ID', '[[C001]]'], ['Guide version', 'VS-1'], ['Expected length', '15 to 30 minutes (assumption)']], 3000));

  k.push(H1('Before you go'));
  [
    'The risk screen for this case is done. If the plot is flagged as disputed, at least two Tenmina people attend. Never go alone to a disputed plot.',
    'The lawyer has confirmed who must consent, and the family head or traditional authority has agreed the date, time and place.',
    'Print two copies of the consent form and the witness sheet, and bring the site plan.',
    'An interpreter is arranged if anyone does not read English. The interpreter is not a party to the sale.',
    'Phone fully charged, at least 4 GB free, camera location tag on, date and time set to automatic. Bring a power bank.',
  ].forEach((t) => k.push(numbered(t, 'steps')));

  k.push(H1('Filming rules'));
  [
    'Film landscape (sideways). Keep the speaker\'s face and any document in good light.',
    'Record one continuous video. Do not pause. If the recording stops, start a new one at once and say on camera why it stopped.',
    'Never edit, trim, add filters to or compress the video. Never send it by WhatsApp: WhatsApp changes the file, so its fingerprint no longer matches.',
    'Do not film anyone who said no to filming. Keep them out of the frame, or stop and let the lawyer decide whether the meeting goes ahead.',
    'Do not film identity cards. The lawyer says on camera which document they saw. The number is written on the form only.',
  ].forEach((t) => k.push(bullet(t)));

  k.push(H1('Script'));
  k.push(P('The lawyer leads. The interpreter repeats each part in the meeting\'s language. Fill the bracketed parts in aloud.', { italics: true, color: MUTED }));

  const part = (n, t, who, lines, after = []) => {
    k.push(H2(`${n}. ${t}`));
    k.push(P(`Who speaks: ${who}`, { size: 18, color: MUTED }));
    lines.forEach((l) => k.push(say(l)));
    after.forEach((a) => k.push(bullet(a)));
  };
  part(1, 'Before the camera starts', 'Lawyer', ['Tenmina would like to film this meeting, to show the buyer that consent was given. The video is kept privately. Does everyone agree to be filmed? Anyone may say no.'], ['Mark each person\'s answer on the witness sheet and in section 6 of the consent form. Then start recording.']);
  part(2, 'Opening', 'Lawyer', ['Today is [[day, date]]. The time is [[time]]. We are at [[place]]. My name is [[name]], a lawyer, licence number [[number]]. I am here for [[buyer]], who wishes to buy [[plot number]] at [[locality]]. [[Runner name]] is filming for Tenmina. Everyone here has agreed to be filmed. Is that right?'], ['Wait for each person to say yes aloud.']);
  part(3, 'Introductions', 'Each person present', ['Please say your name, your role at this meeting, and your connection to this land.'], ['After each consenting person, the lawyer says: "I have seen [[name]]\'s [[type of ID]]."']);
  part(4, 'The plot', 'Lawyer, then the family head or chief', ['This is the site plan, reference [[reference]], dated [[date]]. It shows plot [[number]] at [[locality]], about [[size]], next to [[neighbours]]. Is this the plot you are consenting to?'], ['Hold the site plan to the camera for at least five seconds.']);
  part(5, 'Authority', 'Lawyer, then the family head or chief', ['Who holds this land? Who has the authority to consent to its sale? Is anyone else\'s consent needed?']);
  part(6, 'Other buyers and disputes', 'Lawyer, then each consenting person', ['Has this plot been sold, leased or promised to anyone else? Is there any dispute, court case or claim on it?']);
  part(7, 'Payments', 'Lawyer, then each consenting person', ['Has anyone paid you or promised you anything for this consent, apart from customary payments? If so, what?']);
  part(8, 'Consent', 'Interpreter, then each consenting person', ['[[Interpreter reads section 4 of the consent form in full.]]', 'Each consenting person, in their own words: I, [[name]], consent to [[seller]] selling plot [[number]] at [[locality]] to [[buyer]].']);
  part(9, 'Signing', 'Everyone signing', ['[[Lawyer:]] Each person will now sign or put their thumbprint on the form.'], ['Film each person signing or marking, the interpreter signing section 7, and the lawyer signing section 8.', 'Then film every page of the signed form and the witness sheet, one at a time.']);
  part(10, 'Closing', 'Lawyer', ['The time is now [[time]]. The meeting is over. Thank you.'], ['Stop recording.']);

  k.push(H1('Stop and leave if'));
  [
    'anyone becomes threatening, or people arrive who dispute the meeting;',
    'someone says the person consenting has no authority over the land;',
    'a consenting person withdraws, or seems to be under pressure.',
  ].forEach((t) => k.push(bullet(t)));
  k.push(P('Safety comes first. Leave calmly, and log what happened in the tracker\'s Incidents tab the same day. The lawyer decides whether to rebook.'));

  k.push(H1('Within 24 hours'));
  [
    'Upload the original video from the phone to the case\'s E Consent folder, using the cloud drive app. Name it C001_E_YYYY-MM-DD_consent-meeting.mp4.',
    'Scan the signed consent form and witness sheet as PDFs into the same folder.',
    'Run every file through the fingerprint tool and paste the rows into the tracker\'s Evidence log.',
    'Write the video\'s file name and first 12 fingerprint characters in section 9 of the consent form copy you keep.',
    'Keep the paper originals in the locked case file. Give the family a copy if they ask and the lawyer agrees.',
    'Delete the video from the phone only after the second copy is made and logged.',
  ].forEach((t) => k.push(numbered(t, 'steps3')));
  return doc({ title: 'Consent meeting filming guide', headerText: 'Tenmina · Consent meeting: filming guide and script · Guide VS-1', children: k, draft: true });
}

function witnessSheet() {
  const k = [];
  k.push(...titleBlock('Witness sheet', 'Everyone present who does not sign section 5 of the consent form: witnesses, elders, neighbours, the interpreter, the lawyer and Tenmina staff. Use a second sheet if more than seven people attend. Write roles, not opinions, and collect nothing more than the sheet asks for.'));
  k.push(table([2600, 4200, 2600, WL - 9400], [
    ['Case ID', 'Meeting', 'Date', 'Place'],
    ['[[C001]]', 'Consent meeting ☐    Site visit ☐    Other ☐', '', ''],
  ]));
  k.push(spacer(80));
  k.push(P('Read aloud first: Tenmina records who was present at this meeting, to show the buyer and the buyer\'s lawyer that it took place and who saw it. Your name and role are kept privately, for [[retention period, TO VERIFY with the lawyer]], under the Data Protection Act 2012 (Act 843). Your phone number is optional. You may say no to being filmed.', { size: 18 }));
  k.push(table([450, 2700, 1900, 2400, 1600, 1300, 1500, WL - 11850], [
    ['#', 'Full name', 'Role at the meeting', 'Connection to the land or the parties', 'Phone (optional)', 'ID seen? (type)', 'Agrees to be filmed', 'Signature or thumbprint'],
    ...Array.from({ length: 7 }, (_, i) => [String(i + 1), '', '', '', '', '', yesNo, '']),
  ], { rowHeight: 520, size: 18 }));
  k.push(spacer(100));
  k.push(table([3600, 3600, 3600, WL - 10800], [
    ['Recorded by (Tenmina)', 'Signature', 'Lawyer present', 'Signature'],
    ['', '', '', ''],
  ], { rowHeight: 460 }));
  return doc({ title: 'Witness sheet', headerText: 'Tenmina · Witness sheet · Form WS-1', children: k, landscape: true, draft: true });
}

// =====================================================================
// Client terms (land verification) and professional services agreement
// =====================================================================
const clause = (num, text) => new Paragraph({
  children: [new TextRun({ text: num + '  ', font: FONT, size: 20, bold: true }), ...runs(text)],
  indent: { left: 520, hanging: 520 },
  spacing: { after: 100, line: 276 },
});
const ENTITY = '[[Tenmina company name and registration number, TO VERIFY]]';

function clientTerms() {
  const k = [];
  k.push(...titleBlock('Your land verification: order and terms', 'Please read these terms before you pay. They explain what we check, what we do not, what it costs, and what happens if something goes wrong.'));
  k.push(H1('Your order'));
  k.push(fields([
    ['Terms version', 'CT-1'],
    ['Case ID', '[[C001]]'],
    ['Your name', '[[Full name]]'],
    ['Where you live', '[[Country]]'],
    ['Email and WhatsApp', '[[Email, WhatsApp number]]'],
    ['The plot', '[[Locality, plot number, site plan reference if you have it]]'],
    ['Seller', '[[Name, and how to reach them]]'],
    ['Have you paid anything yet?', '[[No / Yes: how much, to whom, when]]'],
    ['Fee', '[[Amount and currency]]'],
    ['Extras agreed', '[[None / rush / extra plot / travel beyond the usual area]]'],
    ['Documents you will send', '[[Site plan, indenture, receipts, allocation note, anything else]]'],
  ], 3200));
  k.push(spacer(80));
  k.push(table([W], [[{ cell: true, fill: TINT, text: [
    P('To accept', { bold: true, after: 60 }),
    P('Sign below, or reply to the message that brought you these terms with the words "I agree to Tenmina terms CT-1". We keep your reply with your case. We start work once you have accepted and your fee has arrived.', { after: 120 }),
    P('Signature: ______________________________          Date: ________________', { after: 0 }),
  ] }]], { header: false }));
  k.push(pageBreak());

  k.push(H1('The terms'));
  k.push(H2('1. Who we are'));
  k.push(clause('1.1', `Tenmina is ${ENTITY}, of [[address in Ghana]]. You can reach us at [[email]] or on WhatsApp at [[number]].`));
  k.push(clause('1.2', 'We act for you, the buyer, and no one else. We do not act for the seller, the family or the traditional authority, and no one working on your case may take money from them.'));
  k.push(clause('1.3', 'We may also show you plots we have already checked, from sellers we have screened. Those sellers pay us a fixed fee per plot to have it checked, the same whatever the verdict, and nothing more if you buy. We tell you when a plot comes from such a seller. If you choose one, we run a fresh search and give you the report in your own name, and we still act only for you.'));

  k.push(H2('2. What we will do'));
  k.push(clause('2.1', 'We check the plot described in your order and give you a written report with a verdict: green, amber or red. The report covers:'));
  ['that the plot on the site plan is the plot on the ground (plot identity);', 'official searches at the Lands Commission on the plot and on the seller\'s name;', 'a licensed surveyor\'s visit, with the pillars found and any overlap with neighbours;', 'whether the plot falls in a government acquisition, road reserve, wetland, flood zone, known dispute area or a zoning that rules out your use;', 'who the seller is, what right they hold, and whether the family, stool or skin consents, recorded on video with witnesses and a lawyer present;', 'how the seller came to hold the plot (chain of ownership);', 'who is on the land now and any sign of dispute or land guard activity.'].forEach((t) => k.push(bullet(t)));
  k.push(clause('2.2', 'A licensed lawyer signs the legal sections and a licensed surveyor signs the survey sections. Two people review every report before you receive it.'));
  k.push(clause('2.3', 'You receive the report as a PDF, with its fingerprint: a code that proves the PDF has not been changed. Anyone can ask us to check a copy against it.'));
  k.push(clause('2.4', 'We update you at least once a week by WhatsApp or email until the report is delivered.'));

  k.push(H2('3. What we do not do'));
  ['We do not guarantee title. Only registration at the Lands Commission confirms title in Ghana, and registered title can be challenged.', 'We do not advise on the purchase agreement or negotiate with the seller. Our lawyer or another lawyer of your choice can do that, under a separate agreement.', 'We do not hold, receive or pay your purchase money. Do not pay anyone until you have read the report\'s conditions.', 'We do not register the land or carry out the conveyancing.', 'We do not check anything not listed in section 2, or any plot other than the one in your order.', 'We do not send anyone onto land where there is a threat to their safety, and we never confront occupiers or land guards.'].forEach((t) => k.push(bullet(t)));
  k.push(note('Section 12 of your report, the scope and limitation statement, sets out these limits in full. It is the same in every report.'));

  k.push(H2('4. What we need from you'));
  k.push(clause('4.1', 'The documents listed in your order, and the seller\'s contact details. You agree that we may contact the seller, the family or traditional authority, neighbours and public offices about the plot.'));
  k.push(clause('4.2', 'The truth about what you have already paid or signed. It changes what we check first.'));
  k.push(clause('4.3', 'If you have not paid the seller, please do not pay until you have our report.'));

  k.push(H2('5. Fee and payment'));
  k.push(clause('5.1', 'The fee in your order covers the lawyer, the surveyor, our field runner, the standard Lands Commission search fees and travel within [[usual area, TO VERIFY]].'));
  k.push(clause('5.2', 'You pay the full fee before we start, by the payment link we send you [[payment provider, TO VERIFY]]. We never ask you to pay a person\'s private account.'));
  k.push(clause('5.3', 'We charge extra only for something you agree to in writing before we do it: a rush job, another plot, travel beyond the usual area, or extra searches.'));
  k.push(clause('5.4', 'The fee is the same whatever the verdict. Nobody on your case is paid more or less because the plot turns out green, amber or red.'));

  k.push(H2('6. How long it takes'));
  k.push(clause('6.1', 'We aim to deliver within 20 working days of receiving your fee and the documents in your order (working assumption). The Lands Commission sets its own pace; if a search is late we tell you, and why, in our weekly update.'));
  k.push(clause('6.2', 'If an early check finds a problem that makes the plot red on its own, we tell you at once. You choose: we stop there and give you a report on what we found, with a refund for the checks not done, or we finish every check.'));

  k.push(H2('7. Cancelling and refunds'));
  k.push(table([4600, W - 4600], [
    ['When', 'What you get back'],
    ['You cancel before we lodge any search or book any visit', 'The whole fee'],
    ['You cancel after work has started', 'The fee less the cost of work already done, listed item by item'],
    ['We stop because of a safety risk, or because the seller or family will not allow the checks', 'A report on what we could check, and the fee for the checks not done'],
    ['We stop early at your choice after a red finding (6.2)', 'A report on what we found, and the fee for the checks not done'],
    ['The report has been delivered', 'No refund. The report has done its job, whatever the verdict'],
    ['We made a mistake on something we checked', 'A corrected report, free, as a new version with the reason'],
  ]));
  k.push(note('Refund rules are working assumptions until the lawyer confirms them [TO VERIFY]. Refunds go back by the way you paid, less any charge the payment provider does not return [TO VERIFY].'));

  k.push(H2('8. Your report'));
  k.push(clause('8.1', 'The report is for you. You may share it with your lawyer, your bank, your family or a buyer\'s agent acting for you. Nobody else may rely on it without our written agreement.'));
  k.push(clause('8.2', 'We never change a released report. A correction is a new version with a new fingerprint and the reason, and we send it to you.'));

  k.push(H2('9. Paying the seller safely'));
  k.push(clause('9.1', 'We will never ask you to pay money to a new or different account by WhatsApp, email or phone. If anyone does, even if the message seems to come from us, the seller or the lawyer, do not pay. Call us on the number in your order.'));
  k.push(clause('9.2', 'If you use escrow through our partner bank, the purchase money goes to the bank, never to Tenmina. The seller and the seller\'s account are fixed when you agree the escrow terms, and the bank pays only an account whose name matches the verified seller.'));
  k.push(clause('9.3', 'If the seller\'s account must change, it changes only when you approve, two Tenmina staff approve, the seller\'s identity and the new account are checked again, and [[72 hours, TO VERIFY]] have passed. We tell you on two channels, such as email and WhatsApp.'));
  k.push(clause('9.4', 'Money is released only when every condition is met, a fresh search is clean, you approve, and two Tenmina staff approve. Your silence is never approval. We aim for the bank to pay within [[2 working days, TO VERIFY]] of the last approval.'));
  k.push(clause('9.5', 'If the purchase does not go ahead, the bank refunds the money only to the account it came from. If that account is closed, we check your identity again, you approve, and the same waiting period as 9.3 applies.'));
  k.push(clause('9.6', 'Escrow has its own agreement between you, the bank and Tenmina, with the bank\'s fee [[TO VERIFY]]. These terms do not open an escrow.'));

  k.push(H2('10. Limits'));
  k.push(clause('10.1', 'Our liability for the report is limited to the fee you paid, except where the law does not allow that limit. We hold professional indemnity insurance for our reports [[policy reference, TO VERIFY]].'));
  k.push(clause('10.2', 'We are not responsible for what third parties\' records leave out, or for events after the dates of our searches and site visit.'));

  k.push(H2('11. Your personal data'));
  k.push(clause('11.1', 'We collect what we need for your case: your name, contact details, documents and messages, and the names, documents, photos and video of the seller, the family or traditional authority and witnesses.'));
  k.push(clause('11.2', 'Only the people working on your case see it: our lawyer, surveyor, runner and reviewer. It is kept in a restricted folder, with a second copy kept securely, for [[retention period, TO VERIFY with the lawyer]], and then deleted.'));
  k.push(clause('11.3', 'Our storage may be outside Ghana [[location and legal basis, TO VERIFY with the lawyer]]. We follow the Data Protection Act 2012 (Act 843). You may ask what we hold about you, and ask us to correct it, at [[email]].'));

  k.push(H2('12. Complaints and disputes'));
  k.push(clause('12.1', 'Tell us at [[email]]. The founder replies within 5 working days (working assumption).'));
  k.push(clause('12.2', 'If we cannot agree, we will try mediation in Accra before either of us goes to court [[lawyer to confirm, including the Alternative Dispute Resolution Act, 2010 (Act 798), TO VERIFY]]. These terms are governed by the law of Ghana.'));
  return doc({ title: 'Client terms', headerText: 'Tenmina · Land verification: order and terms · Version CT-1', children: k, draft: true });
}

function professionalAgreement() {
  const k = [];
  k.push(...titleBlock('Professional services agreement', 'For lawyers, surveyors and field runners who work on Tenmina cases. The main terms apply to everyone; the schedule for your role says what you do, how fast, and what you are paid.'));
  k.push(fields([['Agreement version', 'PA-1'], ['Role', 'Lawyer ☐    Surveyor ☐    Field runner ☐']], 3000));

  k.push(H1('The parties'));
  k.push(fields([
    ['Tenmina', ENTITY],
    ['Address', '[[Tenmina address in Ghana]]'],
    ['The professional', '[[Full name, and firm if any]]'],
    ['Licence or registration', '[[Ghana Bar or surveyors\' licence number, or "not applicable" for a runner]]'],
    ['Address and phone', '[[Address, phone]]'],
    ['Payment account', '[[Bank or mobile money account in the professional\'s own name]]'],
    ['Starts on', '[[Date]]'],
  ], 3000));

  k.push(H1('Main terms'));
  k.push(H2('1. How we work together'));
  k.push(clause('1.1', 'You are an independent professional, not an employee of Tenmina. You may work for others, except as clause 3 says.'));
  k.push(clause('1.2', 'Tenmina offers you jobs by WhatsApp or email, each with a case ID, the plot, what is needed and the date it is due. You accept or decline within 1 working day. Once you accept, you deliver as your schedule says, and you tell Tenmina at once if anything will make you late.'));
  k.push(clause('1.3', 'You deal with the client only through Tenmina during the case. If the client asks for further work, such as conveyancing, Tenmina introduces you and you agree terms with the client directly.'));

  k.push(H2('2. Pay'));
  k.push(clause('2.1', 'Tenmina pays the fees in Schedule D. Your fee never depends on the verdict or outcome of your work: a red report pays the same as a green one.'));
  k.push(clause('2.2', 'A fee is earned when your work is accepted: your signed section passes Tenmina\'s second review, or, for a runner, your month is closed on its last working day. A part month is paid by working days.'));
  k.push(clause('2.3', 'Tenmina pays within [[10, TO VERIFY]] working days of acceptance, from its own business account, to the account in your own name above. Never in cash, and never from client money.'));
  k.push(clause('2.4', 'Expenses are paid only if Tenmina approved them before you spent the money, against an official receipt. Lands Commission and other official fees are repaid at cost.'));
  k.push(clause('2.5', 'Tenmina deducts withholding tax where the law requires it, and gives you a statement of what was deducted [[rates, TO VERIFY]]. You are responsible for your own taxes.'));
  k.push(clause('2.6', 'Tenmina may hold pay for a job only while a written fraud or misconduct review of that job is open, and tells you why. When the review closes, the pay is released or cancelled.'));
  k.push(clause('2.7', 'If work does not meet the standard in your schedule, you put it right at no extra fee.'));

  k.push(H2('3. Independence'));
  k.push(clause('3.1', 'Before each job you sign the declaration in Schedule E. You must not take a job if you, your family or your firm has any link to the seller, the buyer, the family or traditional authority selling the land, a neighbouring owner, or another buyer of the same plot.'));
  k.push(clause('3.2', 'You take no money, gift or favour from anyone connected with the plot. Customary drinks offered at a meeting are recorded on the consent form, not accepted personally.'));
  k.push(clause('3.3', 'You do not act for the seller in the same transaction.'));

  k.push(H2('4. Evidence and honesty'));
  k.push(clause('4.1', 'You follow Tenmina\'s evidence rules (evidence-folders.md): original files only, phone location tag on, upload to the case folder within 24 hours, never by WhatsApp, and never edited, cropped or trimmed.'));
  k.push(clause('4.2', 'You never invent, alter or reuse evidence. Every file is fingerprinted, and a file used in two cases is detected. Fabricated or reused evidence ends this agreement at once, and Tenmina may report it to your professional body or the police.'));
  k.push(clause('4.3', 'You report what you find, including what the client will not want to hear.'));

  k.push(H2('5. Safety'));
  k.push(clause('5.1', 'You never visit a plot flagged as disputed alone, or before Tenmina\'s risk screen is done.'));
  k.push(clause('5.2', 'If you feel threatened, you leave. You never confront occupiers or land guards and never carry case money. You tell Tenmina the same day, and it is logged.'));
  k.push(clause('5.3', 'A visit you leave for safety is paid in full. Nobody is paid more for staying.'));

  k.push(H2('6. Confidentiality and personal data'));
  k.push(clause('6.1', 'Everything about a case is confidential, during this agreement and after it ends.'));
  k.push(clause('6.2', 'You use personal data only for the job, keep it in Tenmina\'s case folders, and delete it from your phone and computer once Tenmina confirms it is uploaded and copied. You follow the Data Protection Act 2012 (Act 843).'));
  k.push(clause('6.3', 'You tell Tenmina within 24 hours if a phone, file or document with case data is lost or seen by someone who should not see it.'));

  k.push(H2('7. Licences and insurance'));
  k.push(clause('7.1', 'Lawyers and surveyors keep their licence current, give Tenmina a copy each year, and tell Tenmina at once if it is suspended or withdrawn.'));
  k.push(clause('7.2', 'Lawyers and surveyors hold their own professional indemnity insurance [[minimum cover, TO VERIFY]] and give Tenmina proof of it.'));
  k.push(clause('7.3', 'Your signed section is your professional opinion and your responsibility. Tenmina\'s liability to you is limited to fees due under this agreement.'));

  k.push(H2('8. Ending the agreement'));
  k.push(clause('8.1', 'Either of us may end this agreement with 14 days\' written notice. Jobs already accepted are finished and paid, unless Tenmina asks you to stop, in which case work done so far is paid.'));
  k.push(clause('8.2', 'Tenmina may end it at once for a breach of clause 3, 4.2, 5 or 6, or if your licence lapses. Work affected by the breach is not paid.'));
  k.push(clause('8.3', 'When it ends, you hand back or delete all case data and confirm in writing that you have done so.'));

  k.push(H2('9. Disputes'));
  k.push(clause('9.1', 'We will try to settle any disagreement by talking, then by mediation in Accra, before going to court [[lawyer to confirm, including the Alternative Dispute Resolution Act, 2010 (Act 798), TO VERIFY]]. This agreement is governed by the law of Ghana.'));

  k.push(H2('Signatures'));
  k.push(table([2400, 3200, 2638, 1400], [
    ['', 'Name', 'Signature', 'Date'],
    ['For Tenmina', '[[Name, role]]', '', ''],
    ['The professional', '[[Name]]', '', ''],
  ], { rowHeight: 700 }));

  // Schedules
  const sched = (letter, title, rows, extra = []) => {
    k.push(pageBreak());
    k.push(H1(`Schedule ${letter}. ${title}`));
    k.push(fields(rows, 2800));
    extra.forEach((e) => k.push(e));
  };
  sched('A', 'Lawyer', [
    ['What you do', 'Lodge or supervise official Lands Commission searches on the plot and the seller\'s name. Review the documents. Establish the seller\'s authority and the chain of ownership. Lead the consent meeting using Tenmina\'s consent form and script. Write and sign report sections 5, 8 and 9. Check that section 12 is unchanged before signing.'],
    ['Turnaround', 'Signed legal sections within 10 working days of the search results (working assumption).'],
    ['Standard', 'Report template EN-02 followed in full. Every finding linked to its evidence. Plain English the client can act on.'],
    ['Second review', 'Your sections are reviewed by a Tenmina reviewer. Questions are answered within 2 working days.'],
  ]);
  sched('B', 'Surveyor', [
    ['What you do', 'Visit the site, find each pillar, take coordinates, compare the ground with the site plan and the cadastral record, measure any overlap, and photograph each pillar and the plot from each corner. Write and sign report sections 4 and 6, and contribute to section 10.'],
    ['Turnaround', 'Signed sections within 5 working days of the site visit (working assumption).'],
    ['Standard', 'Coordinates in [[format, e.g. WGS84 decimal degrees and Ghana National Grid, TO VERIFY]]. Photos with location tag. Overlaps in metres.'],
    ['Safety', 'Two people at any plot flagged as disputed. Risk screen before every visit.'],
  ]);
  sched('C', 'Field runner', [
    ['What you do', 'Lodge searches and chase results, book site visits and consent meetings, film consent meetings using Tenmina\'s script, photograph sites, upload originals within 24 hours, fingerprint them and log them in the tracker, and keep the case dates up to date.'],
    ['Hours and area', '[[Days, hours and area covered, TO VERIFY]]'],
    ['Standard', 'Evidence rules followed every time. Weekly status to Tenmina by [[day]].'],
    ['Month', 'Closed by Tenmina on the last working day. A part month is paid by working days.'],
  ]);
  k.push(pageBreak());
  k.push(H1('Schedule D. Fees'));
  k.push(table([2200, 2700, 1500, W - 6400], [
    ['Role', 'Fee', 'Currency', 'Included'],
    ['Lawyer', '[[Per report, TO VERIFY]]', '[[GHS]]', 'Searches supervision, document review, consent meeting, sections 5, 8, 9'],
    ['Surveyor', '[[Per visit, TO VERIFY]]', '[[GHS]]', 'One site visit and sections 4 and 6'],
    ['Surveyor travel', '[[Per km or fixed, TO VERIFY]]', '[[GHS]]', 'Beyond [[distance]] from [[base]]'],
    ['Field runner', '[[Per month, TO VERIFY]]', '[[GHS]]', 'All runner work in the agreed area'],
    ['Official fees', 'At cost', 'GHS', 'Against an official receipt'],
  ], { rowHeight: 560 }));
  k.push(note('Fees are agreed per professional and written here. No fee may vary with the verdict or outcome of the work.'));
  k.push(H1('Schedule E. Declaration for each job'));
  k.push(P('Before starting each job, I confirm that neither I, my family nor my firm has any link to the seller, the buyer, the family or traditional authority selling the land, a neighbouring owner, or another buyer of this plot, and that I have taken nothing from anyone connected with it.', { size: 18 }));
  k.push(table([1500, 3400, 1400, 1938, 1400], [
    ['Case ID', 'Plot', 'Any link? (describe)', 'Signature', 'Date'],
    ...Array(6).fill(['', '', 'None ☐', '', '']),
  ], { rowHeight: 520, size: 18 }));
  return doc({ title: 'Professional services agreement', headerText: 'Tenmina · Professional services agreement · Version PA-1', children: k, draft: true });
}


function sellerAgreement() {
  const k = [];
  k.push(...titleBlock('Seller agreement: checked plots', 'For established sellers whose plots Tenmina checks and offers to buyers. Tenmina checks every plot in full and acts for the buyer; this agreement sets what each side does.'));
  k.push(fields([['Agreement version', 'SA-1'], ['Seller ID', '[[S01]]']], 3000));
  k.push(H1('The parties'));
  k.push(fields([
    ['Tenmina', ENTITY],
    ['The seller', '[[Company name and registration number]]'],
    ['Real Estate Agency Council licence', '[[Number, or "not required" with the lawyer\'s note, TO VERIFY]]'],
    ['Signing for the seller', '[[Name, role]]'],
    ['Address and phone', '[[Address, phone]]'],
    ['Account for sale proceeds', '[[Bank account in the seller\'s own name, verified by Tenmina]]'],
    ['Starts on', '[[Date]]'],
  ], 3000));
  k.push(H1('Terms'));
  k.push(H2('1. What Tenmina does'));
  k.push(clause('1.1', 'Tenmina checks each plot the seller puts forward, with the same checks as any other report: Lands Commission searches, a licensed surveyor\'s visit, overlay checks, the seller\'s authority and chain of ownership, and occupation of the land.'));
  k.push(clause('1.2', 'Tenmina offers a plot to buyers only while its report is green and less than [[90 days, TO VERIFY]] old. Buyers see the full report.'));
  k.push(clause('1.3', 'When a buyer chooses a plot, Tenmina runs a fresh search and issues the report to that buyer. Tenmina acts for the buyer, not for the seller.'));
  k.push(clause('1.4', 'Tenmina may stop offering any plot at once if new information arises, and tells the seller why unless the law or a buyer\'s safety prevents it.'));
  k.push(H2('2. Fee'));
  k.push(clause('2.1', 'The seller pays [[fixed fee per plot, TO VERIFY]] for each plot checked, before the check starts.'));
  k.push(clause('2.2', 'The fee is the same whatever the verdict and is not refunded if the plot is amber or red. There is no fee or commission when a plot sells.'));
  k.push(clause('2.3', 'The seller pays nothing to Tenmina\'s staff, lawyers, surveyors or runners, and offers them no gift or favour. Any such offer ends this agreement.'));
  k.push(H2('3. What the seller does'));
  k.push(clause('3.1', 'Gives Tenmina true and complete documents for each plot, access to the site, and the contacts of the family, stool or skin whose consent is needed.'));
  k.push(clause('3.2', 'Tells Tenmina the same day if a checked plot is sold, reserved, disputed or affected by any claim, and does not sell a plot to two buyers.'));
  k.push(clause('3.3', 'Keeps the price shown to a buyer for [[30 days, TO VERIFY]] after the buyer reserves the plot through Tenmina.'));
  k.push(clause('3.4', 'Accepts payment through escrow at Tenmina\'s partner bank when a buyer chooses it, takes no deposit outside escrow on that plot, and accepts that the bank pays only the verified account above. The account changes only under Tenmina\'s payee rules, with a waiting period.'));
  k.push(clause('3.5', 'Does not pressure buyers, and does not describe Tenmina\'s check as a guarantee of title.'));
  k.push(H2('4. Independence'));
  k.push(clause('4.1', 'The seller never sees a buyer\'s report before the buyer and has no say in any verdict. A red report stands.'));
  k.push(clause('4.2', 'Tenmina tells buyers that the seller pays Tenmina to check plots.'));
  k.push(H2('5. Personal data and confidentiality'));
  k.push(clause('5.1', 'Each side uses the other\'s and buyers\' personal data only for the purpose of this agreement, under the Data Protection Act 2012 (Act 843).'));
  k.push(H2('6. Ending the agreement'));
  k.push(clause('6.1', 'Either side may end this agreement with [[30 days, TO VERIFY]] written notice. Sales already in escrow complete under their own agreements.'));
  k.push(clause('6.2', 'Tenmina may end it at once if the seller breaks clause 2.3, 3.2 or 3.4, or gives false information, and may tell buyers with open purchases why.'));
  k.push(H2('7. Disputes'));
  k.push(clause('7.1', 'Disagreements go first to talks, then to mediation in Accra, before court [[lawyer to confirm, including the Alternative Dispute Resolution Act, 2010 (Act 798), TO VERIFY]]. This agreement is governed by the law of Ghana.'));
  k.push(H2('Signatures'));
  k.push(table([2400, 3200, 2638, 1400], [
    ['', 'Name', 'Signature', 'Date'],
    ['For Tenmina', '[[Name, role]]', '', ''],
    ['For the seller', '[[Name, role]]', '', ''],
  ], { rowHeight: 700 }));
  return doc({ title: 'Seller agreement', headerText: 'Tenmina · Seller agreement: checked plots · Version SA-1', children: k, draft: true });
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const files = {
    'land-report-template.docx': reportTemplate(),
    'consent-form.docx': consentForm(),
    'consent-video-script.docx': videoScript(),
    'witness-sheet.docx': witnessSheet(),
    'client-terms.docx': clientTerms(),
    'professional-agreement.docx': professionalAgreement(),
    'seller-agreement.docx': sellerAgreement(),
  };
  for (const [name, d] of Object.entries(files)) {
    fs.writeFileSync(path.join(OUT, name), await Packer.toBuffer(d));
    console.log('wrote', name);
  }
})();
