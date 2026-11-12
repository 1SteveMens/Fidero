"""Finishes the case kit Word files after case-kit.js. Run:  python3 finish.py

1. Locks the scope and limitation statement in the report template (RUL-04, EN-02):
   wraps the paragraphs between the @@SCOPE_START@@ and @@SCOPE_END@@ markers in a Word
   content control that cannot be edited or deleted, then removes the markers.
2. Cleans every file: removes the highlightCs element docx-js writes (it fails the
   schema check) and the ZIP folder entries some cloud editors refuse.
"""
import os
import re
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(HERE, '..', 'case-kit')
REPORT = 'land-report-template.docx'
VERSION = 'S1'


def para_span(xml, marker):
    i = xml.index(marker)
    starts = [m.start() for m in re.finditer(r'<w:p[ >]', xml[:i])]
    return starts[-1], xml.index('</w:p>', i) + len('</w:p>')


def lock(xml):
    s0, s1 = para_span(xml, '@@SCOPE_START@@')
    e0, e1 = para_span(xml, '@@SCOPE_END@@')
    inner = xml[s1:e0]
    assert inner.count('<w:p') >= 5, 'scope paragraphs missing'
    sdt = (
        '<w:sdt><w:sdtPr>'
        f'<w:alias w:val="Scope statement {VERSION} (locked)"/>'
        f'<w:tag w:val="tenmina-scope-{VERSION}"/>'
        '<w:id w:val="70001"/>'
        '<w:lock w:val="sdtContentLocked"/>'
        '</w:sdtPr><w:sdtContent>' + inner + '</w:sdtContent></w:sdt>'
    )
    xml = xml[:s0] + sdt + xml[e1:]
    assert '@@SCOPE' not in xml
    return xml


def main():
    for name in sorted(os.listdir(KIT)):
        if not name.endswith('.docx'):
            continue
        path = os.path.join(KIT, name)
        with zipfile.ZipFile(path) as z:
            items = {n: z.read(n) for n in z.namelist() if not n.endswith('/')}
        xml = items['word/document.xml'].decode('utf-8')
        xml = re.sub(r'<w:highlightCs [^>]*/>', '', xml)
        if name == REPORT:
            xml = lock(xml)
        items['word/document.xml'] = xml.encode('utf-8')
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
            # [Content_Types].xml first, as Word expects
            for n in sorted(items, key=lambda n: n != '[Content_Types].xml'):
                z.writestr(n, items[n])
        print('finished', name, '(scope statement ' + VERSION + ' locked)' if name == REPORT else '')


if __name__ == '__main__':
    main()
