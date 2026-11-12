from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.comments import Comment
from openpyxl.utils import get_column_letter as L
from datetime import date
import os

# Builds docs/operations/r0-tracker.xlsx (EN-01, EN-02 log, EN-05, EN-06 log, EN-51). Run: python3 tracker.py
OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','r0-tracker.xlsx')
N=300  # data rows per sheet
FIRST=5; LAST=FIRST+N-1
F='Arial'
H_FILL=PatternFill('solid',fgColor='0B0B0B'); H_FONT=Font(name=F,bold=True,color='FFFFFF',size=10)
CALC=PatternFill('solid',fgColor='F3F1EC'); INPUT=PatternFill('solid',fgColor='FFF2A8'); EX=PatternFill('solid',fgColor='EAF7DC')
BODY=Font(name=F,size=10); BOLD=Font(name=F,size=10,bold=True); TITLE=Font(name=F,size=16,bold=True); NOTE=Font(name=F,size=9,italic=True,color='6A675F')
BLUE=Font(name=F,size=10,color='0000FF'); GREEN=Font(name=F,size=10,color='008000')
thin=Side(style='thin',color='D6D3CB'); BOX=Border(bottom=thin)
wb=Workbook()

def sheet(name, title, note, cols, widths):
    ws=wb.create_sheet(name)
    ws['A1']=title; ws['A1'].font=TITLE
    ws['A2']=note; ws['A2'].font=NOTE
    ws['A3']='Grey columns are calculated: do not type in them. Green row = example, starting EX-, left out of every total. Delete it when you start.'; ws['A3'].font=NOTE
    for i,(c,w) in enumerate(zip(cols,widths),1):
        cell=ws.cell(row=4,column=i,value=c); cell.fill=H_FILL; cell.font=H_FONT; cell.alignment=Alignment(wrap_text=True,vertical='center')
        ws.column_dimensions[L(i)].width=w
    ws.row_dimensions[4].height=42
    ws.freeze_panes=ws.cell(row=5,column=2)
    for r in range(FIRST,LAST+1):
        for c in range(1,len(cols)+1): ws.cell(row=r,column=c).font=BODY
    return ws

def dv(ws, col, ref):
    v=DataValidation(type='list',formula1=ref,allow_blank=True); v.error='Choose from the list'; v.errorTitle='Not in the list'
    ws.add_data_validation(v); v.add(f'{col}{FIRST}:{col}{LAST}')
def dates(ws, *cols):
    for col in cols:
        for r in range(FIRST,LAST+1): ws[f'{col}{r}'].number_format='d mmm yyyy'
def calc(ws, col, f, fmt=None):
    for r in range(FIRST,LAST+1):
        c=ws[f'{col}{r}']; c.value=f.replace('{r}',str(r)); c.fill=CALC
        if fmt: c.number_format=fmt
def example(ws, values):
    for col,v in values.items():
        c=ws[f'{col}{FIRST}']; c.value=v
    for c in range(1,ws.max_column+1):
        cell=ws.cell(row=FIRST,column=c)
        if cell.fill!=CALC: cell.fill=EX

# ---------- Lists ----------
ls=wb.create_sheet('Lists')
lists={
 'YesNo':['Yes','No'],
 'Verdict':['Green','Amber','Red'],
 'Source':['Association or church','Webinar or talk','Friend or family','Referral by a client','Remittance company','Social media','Founder network','Professional network','Other'],
 'Need':['Land check before buying','Check land already bought','Looking for land','Pay a school or hospital','Other'],
 'Outcome':['Open','Quoted','Paid','Declined','No reply'],
 'Status':['Open','On hold','Delivered','Cancelled'],
 'CostType':['Lawyer','Surveyor','Runner','Lands Commission fee','Travel','Other'],
 'Search':['Plot search','Seller name search','Other search'],
 'Role':['Lawyer','Surveyor','Runner','Reviewer'],
 'InstType':['School','Hospital','Agency','Other'],
 'PricePoint':['300','450','600','Local GHS price','Other'],
 'EvidenceFolder':['A Client documents','B Searches','C Survey','D Overlays','E Consent','F Site visit','R Report'],
 'AccessFolder':['Whole case','A Client documents','B Searches','C Survey','D Overlays','E Consent','F Site visit','R Report'],
 'AccessLevel':['View only','Add files'],
 'AccessRole':['Founder','Lawyer','Reviewer','Surveyor','Runner','Other'],
 'ScopeVersion':['S1'],
 'TermsVersion':['CT-1'],
 'AgreementVersion':['PA-1'],
 'SellerType':['Estate developer','Land company','Family','Stool or skin','Other'],
 'SellerAgreement':['SA-1'],
 'WhoPaid':['Buyer','Seller'],
}
ls['A1']='Drop-down lists and settings'; ls['A1'].font=TITLE
ls['A2']='Edit these lists if you need new options. Yellow cells are settings you must fill in.'; ls['A2'].font=NOTE
col=1; refs={}
for name,vals in lists.items():
    ls.cell(row=4,column=col,value=name).font=H_FONT; ls.cell(row=4,column=col).fill=H_FILL
    for i,v in enumerate(vals): ls.cell(row=5+i,column=col,value=v).font=BODY
    refs[name]=f"Lists!${L(col)}$5:${L(col)}${4+len(vals)}"
    ls.column_dimensions[L(col)].width=24; col+=1
# FX table
fx=col+1
ls.cell(row=4,column=fx,value='Currency').font=H_FONT; ls.cell(row=4,column=fx).fill=H_FILL
ls.cell(row=4,column=fx+1,value='US dollars per 1 unit').font=H_FONT; ls.cell(row=4,column=fx+1).fill=H_FILL
for i,(cur,rate) in enumerate([('USD',1),('GHS',None),('GBP',None),('EUR',None),('CAD',None)]):
    ls.cell(row=5+i,column=fx,value=cur).font=BODY
    c=ls.cell(row=5+i,column=fx+1,value=rate); c.fill=INPUT; c.font=BLUE; c.number_format='0.0000'
ls.cell(row=10,column=fx,value='Fill in each rate and the date you took it. Rates are not verified data [TO VERIFY].').font=NOTE
ls.cell(row=11,column=fx,value='Rates taken on').font=BOLD; c=ls.cell(row=11,column=fx+1); c.fill=INPUT; c.number_format='d mmm yyyy'
ls.column_dimensions[L(fx)].width=14; ls.column_dimensions[L(fx+1)].width=22
CUR=f"Lists!${L(fx)}$5:${L(fx)}$9"; RATE=f"Lists!${L(fx+1)}$5:${L(fx+1)}$9"
refs['Currency']=CUR
# holidays
hc=fx+3
ls.cell(row=4,column=hc,value='Public holidays (Ghana)').font=H_FONT; ls.cell(row=4,column=hc).fill=H_FILL
for r in range(5,35): c=ls.cell(row=r,column=hc); c.fill=INPUT; c.number_format='d mmm yyyy'
ls.cell(row=36,column=hc,value='Add each public holiday in the 90 days. Working-day counts skip them.').font=NOTE
ls.column_dimensions[L(hc)].width=24
HOL=f"Lists!${L(hc)}$5:${L(hc)}$34"
vc=hc+2
ls.cell(row=4,column=vc,value='Checked plot report valid for (days)').font=H_FONT; ls.cell(row=4,column=vc).fill=H_FILL
c=ls.cell(row=5,column=vc,value=90); c.fill=INPUT; c.font=BLUE
ls.cell(row=6,column=vc,value='Working assumption [TO VERIFY] (RUL-12). A checked plot is offered only while its green report is younger than this.').font=NOTE
ls.column_dimensions[L(vc)].width=30
VALID=f"Lists!${L(vc)}$5"
def usd(amount, currency):
    return f'IF(OR({amount}="",{currency}=""),"",IFERROR({amount}*INDEX({RATE},MATCH({currency},{CUR},0)),"Set rate in Lists"))'

# ---------- Leads ----------
le=sheet('Leads','Leads','Every enquiry, whether or not it becomes a paid report (validation plan section 4).',
 ['Lead ID','Date','Name','Lives in','Diaspora client?','How they heard','What they need','Plot location','Price point offered (USD)','Outcome','Reason or objection','What they compared it to','Case ID if paid','Referred by','Checked plots offered (plot IDs)','Bought a checked plot (plot ID)'],
 [11,13,20,16,11,22,24,20,14,12,28,24,13,18,22,16])
dates(le,'B'); dv(le,'E',refs['YesNo']); dv(le,'F',refs['Source']); dv(le,'G',refs['Need']); dv(le,'I',refs['PricePoint']); dv(le,'J',refs['Outcome'])
example(le,{'A':'EX-L001','B':date(2027,1,11),'C':'Example client','D':'United Kingdom','E':'Yes','F':'Webinar or talk','G':'Land check before buying','H':'Kasoa','I':'450','J':'Paid','K':'','L':'Asking a cousin to look','M':'EX-C001','N':''})

# ---------- Cases ----------
cs=sheet('Cases','Cases','One row per paid report. Dates in each step column are the day that step was finished (validation plan sections 1 and 5).',
 ['Case ID','Lead ID','Client','Diaspora client?','Plot (place, plot number)','Price agreed','Currency','Fee in USD','Price point tested','Date fee paid','Lawyer','Surveyor','Runner','Searches lodged','Search results back','Site visit','Consent meeting','Draft report','Second review done','Delivered to client','Working days to deliver','Verdict','Asked for escrow or a safe way to pay?','Asked about building?','Would recommend?','Total cost (USD)','Cost as share of fee','Status','Notes','Released report fingerprint logged?','Client terms version accepted','Terms accepted on','Who paid for the report'],
 [11,11,20,11,24,11,9,11,12,13,16,16,16,13,13,13,13,13,13,13,12,10,16,12,12,12,12,12,28,14,12,13,12])
dates(cs,'J','N','O','P','Q','R','S','T','AF'); dv(cs,'AE',refs['TermsVersion']); dv(cs,'AG',refs['WhoPaid'])
dv(cs,'D',refs['YesNo']); dv(cs,'G',refs['Currency']); dv(cs,'I',refs['PricePoint']); dv(cs,'V',refs['Verdict']); dv(cs,'W',refs['YesNo']); dv(cs,'X',refs['YesNo']); dv(cs,'Y',refs['YesNo']); dv(cs,'AB',refs['Status'])
calc(cs,'H','='+usd('F{r}','G{r}'),'#,##0.00')
calc(cs,'U',f'=IF(OR(A{{r}}="",LEFT(A{{r}},3)="EX-",J{{r}}="",T{{r}}=""),"",NETWORKDAYS(J{{r}},T{{r}},{HOL}))','0')
calc(cs,'Z','=IF(A{r}="","",SUMIFS(Costs!$H$5:$H$304,Costs!$B$5:$B$304,A{r}))','#,##0.00')
calc(cs,'AA','=IF(OR(A{r}="",H{r}="",H{r}=0),"",IFERROR(Z{r}/H{r},""))','0.0%')
calc(cs,'AD','=IF(OR(A{r}="",LEFT(A{r},3)="EX-",T{r}=""),"",IF(COUNTIFS(\'Reports released\'!$A$5:$A$304,A{r},\'Reports released\'!$L$5:$L$304,"Yes")>0,"Yes","No"))')
cs['AG4'].comment=Comment('Seller when an established seller paid for the check of a plot to be offered as a checked plot. Seller-paid reports are left out of the day-90 demand counts.','Tenmina')
cs['AD4'].comment=Comment('Yes once the delivered report has a row in Reports released with a valid fingerprint (EN-02). Blank until delivery.','Tenmina')
cs['U4'].comment=Comment('Working days from fee paid to delivery, skipping weekends and the holidays in Lists. Blank for the example row.','Tenmina')
example(cs,{'A':'EX-C001','B':'EX-L001','C':'Example client','D':'Yes','E':'Kasoa, plot 14','F':450,'G':'USD','I':'450','J':date(2027,1,13),'K':'Lawyer A','L':'Surveyor A','M':'Runner A','N':date(2027,1,15),'O':date(2027,1,29),'P':date(2027,1,20),'Q':date(2027,1,27),'R':date(2027,2,3),'S':date(2027,2,5),'T':date(2027,2,8),'V':'Amber','W':'Yes','X':'No','Y':'Yes','AB':'Delivered','AE':'CT-1','AF':date(2027,1,12),'AG':'Buyer'})

# ---------- Costs ----------
co=sheet('Costs','Costs','Every cost against a case: professional fees, official fees, travel. Totals feed the Cases sheet.',
 ['Date','Case ID','Type','Paid to','Amount','Currency','Receipt or reference','Amount in USD','Notes'],[13,11,20,22,12,9,20,13,28])
dates(co,'A'); dv(co,'C',refs['CostType']); dv(co,'F',refs['Currency'])
calc(co,'H','='+usd('E{r}','F{r}'),'#,##0.00')
example(co,{'A':date(2027,1,15),'B':'EX-C001','C':'Lawyer','D':'Lawyer A','E':100,'F':'USD','G':'Invoice 001'})

# ---------- Searches ----------
se=sheet('Searches','Lands Commission searches','One row per search, to measure how long the Lands Commission takes (validation plan section 5).',
 ['Case ID','Search','Lodged on','Result back on','Calendar days','What it showed'],[11,20,13,13,12,40])
dates(se,'C','D'); dv(se,'B',refs['Search'])
calc(se,'E','=IF(OR(A{r}="",LEFT(A{r},3)="EX-",C{r}="",D{r}=""),"",D{r}-C{r})','0')
example(se,{'A':'EX-C001','B':'Plot search','C':date(2027,1,15),'D':date(2027,1,29),'F':'No registered interest found'})

# ---------- Institution payments (EN-51) ----------
ip=sheet('Institution payments','Payments to institutions (EN-51)','Every school, hospital or agency paid by hand for a client. Verify the institution before paying; record the receipt.',
 ['Payment ID','Date paid','Client','Family member','Institution','Type','Registration checked?','Bank account in its own name?','Named contact confirmed?','Invoice reference','Amount','Currency','Paid through (bank)','Receipt returned?','Receipt date','Amount in USD','Notes'],
 [11,13,18,18,26,11,13,14,13,16,11,9,18,11,13,12,26])
dates(ip,'B','O')
for c,k in [('F','InstType'),('G','YesNo'),('H','YesNo'),('I','YesNo'),('L','Currency'),('N','YesNo')]: dv(ip,c,refs[k])
calc(ip,'P','='+usd('K{r}','L{r}'),'#,##0.00')
example(ip,{'A':'EX-P001','B':date(2027,2,10),'C':'Example client','D':'Mother','E':'Example Teaching Hospital','F':'Hospital','G':'Yes','H':'Yes','I':'Yes','J':'INV-0001','K':1860,'L':'GHS','M':'Partner bank','N':'Yes','O':date(2027,2,12)})

# ---------- Incidents ----------
inc=sheet('Incidents','Safety incidents','Log every threat or confrontation, however small (validation plan sections 5 and 6).',
 ['Incident ID','Date','Case ID','What happened','Who was involved (roles only)','What we did','Managed by the withdraw rule?','Reported to'],[11,13,11,40,24,32,14,18])
dates(inc,'B'); dv(inc,'G',refs['YesNo'])
example(inc,{'A':'EX-I001','B':date(2027,1,20),'C':'EX-C001','D':'Men on site asked the surveyor to leave','E':'Surveyor, runner','F':'Left the site, rebooked with the family head present','G':'Yes','H':'Founder'})

# ---------- Professionals ----------
pr=sheet('Professionals','Professionals','Two of each role, so one slow person does not stall the service (validation plan section 2).',
 ['Name','Role','Licence or registration number','Licence checked on','Agreement signed on','Fee per job','Currency','Phone','Notes','Agreement version','Own indemnity insurance checked on'],[22,12,22,14,14,11,9,16,30,11,14])
dates(pr,'D','E','K'); dv(pr,'J',refs['AgreementVersion']); dv(pr,'B',refs['Role']); dv(pr,'G',refs['Currency'])

# ---------- Evidence log (EN-06) ----------
HEX='SUMPRODUCT(--ISNUMBER(SEARCH(MID({c},ROW($1:$64),1),"0123456789abcdef")))=64'
def hexok(col):
    c=col+'{r}'
    return f'=IF({c}="","",IF(AND(LEN({c})=64,{HEX.format(c=c)}),"Yes","No"))'
ev=sheet('Evidence log','Evidence log (EN-06)','Every evidence file, with its fingerprint, logged within 24 hours. Paste rows from case-kit/fingerprint.html into column A; it fills A to F.',
 ['Case ID','File name','Fingerprint (SHA-256)','Folder','Logged on','Logged by','What it shows','Taken or received by','Taken or received on','Place (GPS or address)','Second copy made on','Notes','Fingerprint looks right?','Same file elsewhere?','Logged within 24 hours?'],
 [11,34,30,16,12,14,30,18,13,22,13,24,12,16,12])
dates(ev,'E','I','K'); dv(ev,'D',refs['EvidenceFolder'])
calc(ev,'M',hexok('C'))
calc(ev,'N','=IF(OR(C{r}="",LEFT(A{r},3)="EX-"),"",IF(COUNTIFS($C$5:$C$304,C{r},$A$5:$A$304,"<>"&A{r})>0,"Another case",IF(COUNTIFS($C$5:$C$304,C{r},$A$5:$A$304,A{r})>1,"Twice in this case","")))')
calc(ev,'O','=IF(OR(E{r}="",I{r}=""),"",IF(E{r}-I{r}<=1,"Yes","No"))')
ev['N4'].comment=Comment('"Another case" means the same file (same fingerprint) is logged under a different case: a reused photo or a document in two deals. Find out why before any report goes out.','Tenmina')
example(ev,{'A':'EX-C001','B':'C001_F_2027-01-20_pillar-ne.jpg','C':'0000000000000000000000000000000000000000000000000000000000000000','D':'F Site visit','E':date(2027,1,20),'F':'Runner A','G':'North-east pillar, close up','H':'Surveyor A','I':date(2027,1,20),'J':'GA-000-0000','K':date(2027,1,24)})

# ---------- Reports released (EN-02) ----------
rr=sheet('Reports released','Reports released (EN-02)','One row per released PDF. A correction is a new version on a new row, never a change to an old one.',
 ['Case ID','Report reference','Version','Released on','PDF file name','Fingerprint (SHA-256)','Scope statement version','Lawyer who signed','Second reviewer','Reason for this version','Sent to client on','Fingerprint looks right?','Two different reviewers?'],
 [11,20,9,12,34,30,12,18,18,28,12,12,12])
dates(rr,'D','K'); dv(rr,'G',refs['ScopeVersion'])
calc(rr,'L',hexok('F'))
calc(rr,'M','=IF(OR(H{r}="",I{r}=""),"",IF(TRIM(LOWER(H{r}))<>TRIM(LOWER(I{r})),"Yes","No"))')
example(rr,{'A':'EX-C001','B':'TMN-GH-2027-0001','C':1,'D':date(2027,2,8),'E':'C001_R_2027-02-08_report-v1.pdf','F':'0000000000000000000000000000000000000000000000000000000000000000','G':'S1','H':'Lawyer A','I':'Reviewer A','J':'First release','K':date(2027,2,8)})

# ---------- Folder access (EN-06) ----------
fa=sheet('Folder access','Folder access (EN-06)','Every time someone is given or loses access to a case folder. Named people only, never "anyone with the link".',
 ['Case ID','Person','Role','Folder','Access','Given on','Given by','Removed on','Notes','Allowed?'],
 [11,20,12,18,12,12,16,12,28,14])
dates(fa,'F','H'); dv(fa,'C',refs['AccessRole']); dv(fa,'D',refs['AccessFolder']); dv(fa,'E',refs['AccessLevel'])
calc(fa,'J','=IF(OR(C{r}="",D{r}=""),"",IF(AND(OR(D{r}="E Consent",D{r}="Whole case"),OR(C{r}="Surveyor",C{r}="Runner",C{r}="Other")),"Not allowed","Yes"))')
fa['J4'].comment=Comment('Surveyors, runners and others never see the consent folder or the whole case folder (evidence-folders.md section 6).','Tenmina')
example(fa,{'A':'EX-C001','B':'Surveyor A','C':'Surveyor','D':'F Site visit','E':'Add files','F':date(2027,1,15),'G':'Founder','H':date(2027,2,8)})

# ---------- Sellers (checked plots test, validation plan 4a) ----------
sl=sheet('Sellers','Established sellers','Screening of each seller before any of their plots is checked or offered. Being established earns no shortcuts.',
 ['Seller ID','Name','Type','Company registration number','Real Estate Agency Council licence','Licence checked on','Estate title or lease checked at Lands Commission on','Court search on','Court search clear?','Overlay checks clear?','References from past buyers (number)','Seller agreement signed on','Agreement version','Fee per plot checked','Currency','Contact','Notes','Screening complete?'],
 [11,22,14,18,16,13,16,13,11,11,13,13,11,12,9,18,26,12])
dates(sl,'F','G','H','L'); dv(sl,'C',refs['SellerType']); dv(sl,'I',refs['YesNo']); dv(sl,'J',refs['YesNo']); dv(sl,'M',refs['SellerAgreement']); dv(sl,'O',refs['Currency'])
calc(sl,'R','=IF(A{r}="","",IF(AND(D{r}<>"",G{r}<>"",H{r}<>"",I{r}="Yes",J{r}="Yes",N(K{r})>=3,L{r}<>""),"Yes","No"))')
sl['R4'].comment=Comment('Yes only when registration, the Lands Commission check, a clear court search, clear overlays, at least 3 references and a signed agreement are all recorded. The licence is checked where the law requires it [TO VERIFY].','Tenmina')
example(sl,{'A':'EX-S01','B':'Example Estates Ltd','C':'Estate developer','D':'CS000000000','E':'REAC-0000','F':date(2027,1,8),'G':date(2027,1,12),'H':date(2027,1,12),'I':'Yes','J':'Yes','K':3,'L':date(2027,1,15),'M':'SA-1','N':200,'O':'USD'})

# ---------- Checked plots ----------
cp=sheet('Checked plots','Checked plots','Plots from screened sellers, checked in full and offered to buyers whose own plot came back red or who have no plot yet.',
 ['Plot ID','Seller ID','Locality','Plot number','Size','Asking price','Currency','Case ID of the check','Report date','Verdict','Seller fee paid on','Offered to (lead IDs)','Reserved by (lead ID)','Sold on','Paid through escrow?','Notes','Report age (days)','Seller screened?','Can be offered?'],
 [11,11,16,12,12,12,9,13,13,10,13,22,13,13,12,26,11,11,12])
dates(cp,'I','K','N'); dv(cp,'G',refs['Currency']); dv(cp,'J',refs['Verdict']); dv(cp,'O',refs['YesNo'])
calc(cp,'Q','=IF(OR(A{r}="",I{r}=""),"",TODAY()-I{r})','0')
calc(cp,'R','=IF(B{r}="","",IFERROR(INDEX(Sellers!$R$5:$R$304,MATCH(B{r},Sellers!$A$5:$A$304,0)),"Not found"))')
calc(cp,'S','=IF(A{r}="","",IF(AND(J{r}="Green",N(Q{r})<='+VALID+',R{r}="Yes",K{r}<>"",N{r}=""),"Yes","No"))')
cp['S4'].comment=Comment('Yes only for a green report younger than the validity in Lists, from a screened seller who has paid the fixed fee, and not yet sold. A buyer who chooses it still gets a fresh search in their own name.','Tenmina')
example(cp,{'A':'EX-P01','B':'EX-S01','C':'Oyibi','D':'12','E':'70 x 100 ft','F':45000,'G':'USD','H':'EX-C002','I':date(2027,1,25),'J':'Green','K':date(2027,1,16),'L':'EX-L002'})

# ---------- Review (EN-05) ----------
rv=wb.create_sheet('Review',0)
rv['A1']='R0 review'; rv['A1'].font=Font(name=F,size=20,bold=True)
rv['A2']='Fortnightly numbers and the day-90 decision. Targets come from docs/validation-plan.md sections 5 and 6. They are assumptions, not verified data; change a yellow cell if the plan changes.'; rv['A2'].font=NOTE
rv['A3']='Rows whose ID starts with EX- are examples and are left out of every count.'; rv['A3'].font=NOTE
for c,w in zip('ABCDE',[52,14,14,14,46]): rv.column_dimensions[c].width=w

C='Cases!$A$5:$A$304'; Cd=lambda col: f'Cases!${col}$5:${col}$304'
real=f'{C},"?*",{C},"<>EX-*"'
deliv=f'{real},{Cd("T")},"<>"'
delivB=f'{deliv},{Cd("AG")},"<>Seller"'
rv['A5']='Review date'; rv['A5'].font=BOLD; rv['B5']='=TODAY()'; rv['B5'].number_format='d mmm yyyy'
rv['A6']='Service started on'; rv['A6'].font=BOLD; rv['B6'].fill=INPUT; rv['B6'].number_format='d mmm yyyy'
rv['A7']='Days since start'; rv['A7'].font=BOLD; rv['B7']='=IF(B6="","",B5-B6)'; rv['B7'].fill=CALC
rv['A8']='Professional indemnity cover in place?'; rv['A8'].font=BOLD; rv['B8']='No'; rv['B8'].fill=INPUT; rv['B8'].font=BLUE
v=DataValidation(type='list',formula1=refs['YesNo']); rv.add_data_validation(v); v.add('B8')

def hdr(row, names):
    for i,n in enumerate(names):
        c=rv.cell(row=row,column=i+1,value=n); c.fill=H_FILL; c.font=H_FONT
r=10
rv.cell(row=r,column=1,value='Last 14 days').font=Font(name=F,size=13,bold=True); r+=1
hdr(r,['Measure','Count','','','How']); r+=1
fort=[('New leads',f'=COUNTIFS(Leads!$A$5:$A$304,"?*",Leads!$A$5:$A$304,"<>EX-*",Leads!$B$5:$B$304,">="&($B$5-14),Leads!$B$5:$B$304,"<="&$B$5)','Leads dated in the last 14 days'),
      ('Fees paid',f'=COUNTIFS({real},{Cd("J")},">="&($B$5-14),{Cd("J")},"<="&$B$5)','Cases with a fee paid in the last 14 days'),
      ('Reports delivered',f'=COUNTIFS({real},{Cd("T")},">="&($B$5-14),{Cd("T")},"<="&$B$5)','Cases delivered in the last 14 days'),
      ('Cases open',f'=COUNTIFS({real},{Cd("AB")},"Open")+COUNTIFS({real},{Cd("AB")},"On hold")','Status Open or On hold'),
      ('Safety incidents',f'=COUNTIFS(Incidents!$A$5:$A$304,"?*",Incidents!$A$5:$A$304,"<>EX-*",Incidents!$B$5:$B$304,">="&($B$5-14),Incidents!$B$5:$B$304,"<="&$B$5)','Incidents dated in the last 14 days')]
for name,f,how in fort:
    rv.cell(row=r,column=1,value=name).font=BODY; c=rv.cell(row=r,column=2,value=f); c.fill=CALC; c.font=BODY
    rv.cell(row=r,column=5,value=how).font=NOTE; r+=1
r+=1
rv.cell(row=r,column=1,value='Day-90 criteria (go to phase 2 only if all are met)').font=Font(name=F,size=13,bold=True); r+=1
hdr(r,['Criterion','Target','Actual','Met?','How it is counted']); r+=1
crit=[]
def crow(name, target, tfmt, actual, afmt, test, how):
    global r
    rv.cell(row=r,column=1,value=name).font=BODY
    t=rv.cell(row=r,column=2,value=target); t.fill=INPUT; t.font=BLUE; t.number_format=tfmt
    a=rv.cell(row=r,column=3,value=actual); a.fill=CALC; a.font=BODY; a.number_format=afmt
    m=rv.cell(row=r,column=4,value=f'=IF(C{r}="","Not yet",IF({test.format(a=f"C{r}",t=f"B{r}")},"Met","Not yet"))'); m.fill=CALC; m.font=BOLD
    rv.cell(row=r,column=5,value=how).font=NOTE
    crit.append(r); r+=1
crow('Paid reports delivered',30,'0',f'=COUNTIFS({delivB})','0','{a}>={t}','Cases with a delivery date, paid by buyers (seller-paid checks left out)')
crow('Diaspora clients among them',12,'0',f'=COUNTIFS({delivB},{Cd("D")},"Yes")','0','{a}>={t}','Delivered buyer-paid cases marked Diaspora = Yes')
crow('Median working days to deliver (under)',25,'0',f'=IFERROR(MEDIAN({Cd("U")}),"")','0','{a}<{t}','Median of Working days to deliver')
crow('Cost as share of fee (under)',0.5,'0%',f'=IFERROR(SUMIFS({Cd("Z")},{deliv})/SUMIFS({Cd("H")},{deliv}),"")','0.0%','{a}<{t}','All costs of delivered cases ÷ their fees, in USD')
crow('Green-report clients who asked for escrow (at least)',0.3,'0%',f'=IFERROR(COUNTIFS({deliv},{Cd("V")},"Green",{Cd("W")},"Yes")/COUNTIFS({deliv},{Cd("V")},"Green"),"")','0.0%','{a}>={t}','Green reports with Asked for escrow = Yes ÷ all Green reports')
crow('Safety incidents not managed by the withdraw rule (at most)',0,'0',f'=COUNTIFS(Incidents!$A$5:$A$304,"?*",Incidents!$A$5:$A$304,"<>EX-*",Incidents!$G$5:$G$304,"No")','0','{a}<={t}','Incidents marked Managed = No')
crow('Professional indemnity cover in place','Yes','@','=B8','@','{a}={t}','From cell B8')
crow('Institution payments with receipt returned (at least)',5,'0',f'=COUNTIFS(\'Institution payments\'!$A$5:$A$304,"?*",\'Institution payments\'!$A$5:$A$304,"<>EX-*",\'Institution payments\'!$N$5:$N$304,"Yes")','0','{a}>={t}','Payments with Receipt returned = Yes')
dec=r+1
rv.cell(row=dec,column=1,value='Day-90 decision').font=Font(name=F,size=13,bold=True)
c=rv.cell(row=dec,column=2,value=f'=IF($B$6="","Set the start date in B6",IF($B$7<90,"Too early: day "&$B$7&" of 90",IF(COUNTIF(D{crit[0]}:D{crit[-1]},"Met")={len(crit)},"Go to phase 2",IF(OR(AND(ISNUMBER(C{crit[0]}),C{crit[0]}<B{dec+3}),AND(ISNUMBER(C{crit[3]}),C{crit[3]}>B{dec+4}),AND(ISNUMBER(C{crit[2]}),C{crit[2]}>B{dec+5})),"Pause and rework","Not yet"))))')
c.font=Font(name=F,size=13,bold=True); c.fill=CALC
rv.merge_cells(start_row=dec,start_column=2,end_row=dec,end_column=3)
rv.cell(row=dec+1,column=1,value='The decision appears from day 90. "Stop" conditions in the plan need judgement and are not calculated here.').font=NOTE
rv.cell(row=dec+2,column=1,value='Pause and rework if any of these hold').font=BOLD
for i,(name,val,fmt) in enumerate([('Paid reports fewer than',15,'0'),('Cost as share of fee over',0.7,'0%'),('Median working days over',35,'0')]):
    rv.cell(row=dec+3+i,column=1,value=name).font=BODY; t=rv.cell(row=dec+3+i,column=2,value=val); t.fill=INPUT; t.font=BLUE; t.number_format=fmt
r=dec+7
rv.cell(row=r,column=1,value='Other measures').font=Font(name=F,size=13,bold=True); r+=1
hdr(r,['Measure','Value','','','How']); r+=1
L_=f'Leads!$A$5:$A$304,"?*",Leads!$A$5:$A$304,"<>EX-*"'
others=[('Leads in total',f'=COUNTIFS({L_})','0','All leads'),
 ('Lead to paid conversion',f'=IFERROR(COUNTIFS({L_},Leads!$J$5:$J$304,"Paid")/COUNTIFS({L_}),"")','0.0%','Leads with Outcome = Paid ÷ all leads'),
 ('Gross margin per report',f'=IF(C{crit[3]}="","",1-C{crit[3]})','0.0%','1 − cost share (target over 60%, plan section 5)'),
 ('Longest working days to deliver',f'=IF(COUNT({Cd("U")})=0,"",MAX({Cd("U")}))','0','Target: none over 30 (plan section 5)'),
 ('Green reports',f'=COUNTIFS({deliv},{Cd("V")},"Green")','0','Delivered cases'),
 ('Amber reports',f'=COUNTIFS({deliv},{Cd("V")},"Amber")','0','Delivered cases'),
 ('Red reports',f'=COUNTIFS({deliv},{Cd("V")},"Red")','0','Delivered cases. A high Red share is a selling point'),
 ('Clients who asked about building',f'=IFERROR(COUNTIFS({deliv},{Cd("X")},"Yes")/COUNTIFS({deliv}),"")','0.0%','Delivered cases with Asked about building = Yes'),
 ('Would recommend',f'=IFERROR(COUNTIFS({deliv},{Cd("Y")},"Yes")/COUNTIFS({deliv},{Cd("Y")},"?*"),"")','0.0%','Yes ÷ all who answered'),
 ('Median days for a Lands Commission search','=IFERROR(MEDIAN(Searches!$E$5:$E$304),"")','0','Calendar days, lodged to result'),
 ('Delivered reports with a logged fingerprint',f'=IFERROR(COUNTIFS({deliv},{Cd("AD")},"Yes")/COUNTIFS({deliv}),"")','0%','Target 100% (EN-02)'),
 ('Evidence files logged','=COUNTIFS(\'Evidence log\'!$A$5:$A$304,"?*",\'Evidence log\'!$A$5:$A$304,"<>EX-*")','0','Rows in Evidence log'),
 ('Files found in another case','=COUNTIFS(\'Evidence log\'!$A$5:$A$304,"<>EX-*",\'Evidence log\'!$N$5:$N$304,"Another case")','0','Target 0. Each one needs an explanation'),
 ('Evidence logged later than 24 hours','=COUNTIFS(\'Evidence log\'!$A$5:$A$304,"<>EX-*",\'Evidence log\'!$O$5:$O$304,"No")','0','Target 0'),
 ('Folder access not allowed','=COUNTIFS(\'Folder access\'!$A$5:$A$304,"<>EX-*",\'Folder access\'!$J$5:$J$304,"Not allowed")','0','Target 0. Remove the access at once'),
 ('Paid cases without accepted client terms',f'=COUNTIFS({real},{Cd("J")},"<>",{Cd("AF")},"")','0','Fee paid but no terms acceptance date. Target 0'),
 ('Seller-paid checks delivered (checked plots)',f'=COUNTIFS({deliv},{Cd("AG")},"Seller")','0','Not counted in the day-90 demand criteria'),
 ('Leads looking for land',f'=COUNTIFS({L_},Leads!$G$5:$G$304,"Looking for land")','0','Enquiries with no plot yet'),
 ('Leads offered a checked plot',f'=COUNTIFS({L_},Leads!$O$5:$O$304,"?*")','0','Leads with plot IDs in Checked plots offered'),
 ('Bought a checked plot',f'=COUNTIFS({L_},Leads!$P$5:$P$304,"?*")','0','Leads with a plot ID in Bought a checked plot'),
 ('Share of offered leads who bought (test: at least 20%)',f'=IFERROR(COUNTIFS({L_},Leads!$P$5:$P$304,"?*")/COUNTIFS({L_},Leads!$O$5:$O$304,"?*"),"")','0.0%','Working assumption. Decision rule in validation plan 4a'),
 ('Checked plots that can be offered now','=COUNTIFS(\'Checked plots\'!$A$5:$A$304,"<>EX-*",\'Checked plots\'!$S$5:$S$304,"Yes")','0','Green, in date, screened seller, not sold'),
 ('Established sellers\' plots that were not green','=COUNTIFS(\'Checked plots\'!$A$5:$A$304,"<>EX-*",\'Checked plots\'!$J$5:$J$304,"<>Green",\'Checked plots\'!$J$5:$J$304,"?*")','0','Amber or red. Shows how much being established is worth'),
 ('Released reports without two different reviewers','=COUNTIFS(\'Reports released\'!$A$5:$A$304,"<>EX-*",\'Reports released\'!$M$5:$M$304,"No")','0','Target 0')]
for name,f,fmt,how in others:
    rv.cell(row=r,column=1,value=name).font=BODY; c=rv.cell(row=r,column=2,value=f); c.fill=CALC; c.font=BODY; c.number_format=fmt
    rv.cell(row=r,column=5,value=how).font=NOTE; r+=1
r+=1
rv.cell(row=r,column=1,value='Price test (plan section 3): first 20 diaspora clients, one price point each in rotation').font=Font(name=F,size=13,bold=True); r+=1
hdr(r,['Price point (USD)','Offered','Paid','Acceptance','']); r+=1
for pp in ['300','450','600']:
    rv.cell(row=r,column=1,value=pp).font=BODY
    rv.cell(row=r,column=2,value=f'=COUNTIFS({L_},Leads!$I$5:$I$304,A{r})').fill=CALC
    rv.cell(row=r,column=3,value=f'=COUNTIFS({L_},Leads!$I$5:$I$304,A{r},Leads!$J$5:$J$304,"Paid")').fill=CALC
    c=rv.cell(row=r,column=4,value=f'=IFERROR(C{r}/B{r},"")'); c.fill=CALC; c.number_format='0%'
    r+=1
for row in rv.iter_rows():
    for c in row:
        if c.font is None or c.font.name!=F: c.font=Font(name=F,size=c.font.size if c.font else 10,bold=c.font.bold if c.font else False)

# ---------- Start here ----------
st=wb.create_sheet('Start here',0)
st.column_dimensions['A'].width=110
lines=[('Tenmina R0 tracker',TITLE),
('Manual service, months 0 to 3, Ghana. Replaces nothing yet: the R1 platform will take these records over (EN-30).',NOTE),
('',BODY),
('What each tab is for',BOLD),
('Review: the fortnightly numbers and the day-90 decision (EN-05). Open it at every review.',BODY),
('Leads: every enquiry, with where it came from, the price offered, and any checked plots offered or bought (EN-01).',BODY),
('Cases: one row per paid report, with the date each step finished, the verdict and what the client asked for (EN-01).',BODY),
('Costs: every cost against a case. Totals flow into Cases and Review.',BODY),
('Searches: each Lands Commission search, to time them.',BODY),
('Institution payments: every school, hospital or agency paid by hand, with the checks done and the receipt (EN-51).',BODY),
('Incidents: every threat or confrontation, however small.',BODY),
('Professionals: the lawyers, surveyors, runners and reviewers, their agreement version, and when their licences and insurance were checked.',BODY),
('Sellers: screening of each established seller before their plots are checked or offered (validation plan 4a).',BODY),
('Checked plots: plots from screened sellers, their report, and who they were offered to and bought by. Can be offered = green, in date, screened seller, not sold.',BODY),
('Evidence log: every evidence file and its fingerprint, pasted from the fingerprint tool (EN-06). Flags a file used in two cases.',BODY),
('Reports released: every released report PDF, its fingerprint, scope statement version and both reviewers (EN-02).',BODY),
('Folder access: who was given access to which case folder, and when it was removed (EN-06).',BODY),
('Lists: the drop-down choices, exchange rates and public holidays.',BODY),
('',BODY),
('How to fill it in',BOLD),
('Type only in white or yellow cells. Grey cells are calculated. Yellow cells are settings: exchange rates and holidays in Lists, and the start date and insurance answer in Review.',BODY),
('Use the drop-downs, so the counts work. Dates are real dates, not text.',BODY),
('The green row on each tab is an example. Its ID starts with EX- and it is left out of every count. Delete it once you have real rows.',BODY),
('Give every lead an ID (L001, L002 ...) and every case an ID (C001, C002 ...). Write the case ID on the lead when it becomes paid.',BODY),
('Keep client personal data here only as long as the case needs it. Store reports, photos and consent videos in the evidence folders, with their fingerprints logged (EN-02, EN-06).',BODY),
('The case kit is in docs/operations/case-kit: the report template, consent kit, fingerprint tool and evidence-folders.md.',BODY),
('',BODY),
('Every target in this file is a working assumption from docs/validation-plan.md, not verified data.',NOTE)]
for i,(t,f) in enumerate(lines,1):
    c=st.cell(row=i,column=1,value=t); c.font=f; c.alignment=Alignment(wrap_text=True)
wb.remove(wb['Sheet'])
wb.active=0
wb.save(OUT); print('saved')
