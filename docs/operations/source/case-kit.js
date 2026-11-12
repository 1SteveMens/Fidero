// Builds the R0 case kit Word files (EN-02 report template, EN-07 consent kit).
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

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const files = {
    'land-report-template.docx': reportTemplate(),
    'consent-form.docx': consentForm(),
    'consent-video-script.docx': videoScript(),
    'witness-sheet.docx': witnessSheet(),
  };
  for (const [name, d] of Object.entries(files)) {
    fs.writeFileSync(path.join(OUT, name), await Packer.toBuffer(d));
    console.log('wrote', name);
  }
})();
