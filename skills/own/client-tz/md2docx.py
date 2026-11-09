#!/usr/bin/env -S python3 -I
"""Markdown to .docx for client documents (ТЗ, proposals, estimates). Stdlib only: no pandoc, no python-docx.

Supports what client documents use: # to #### headings, paragraphs, "-" / "*" bullets (two levels by indent),
"1." numbered lists (each list restarts at 1), pipe tables (first row is the header), **bold**, *italic*, `code`,
[text](url), "---" (a gap between sections) and a line "<!-- pagebreak -->". Images, HTML, quotes, code blocks and
footnotes are printed as plain text with a warning. Control characters are removed with a warning.
Look: A4, 2 cm margins, Calibri 10.5 pt, dark blue headings, tables with a light header row and thin grey borders,
page numbers in the footer.

Long dashes (‒ – — ―) are not allowed in client texts: they are reported with line numbers, and --strict makes that
an error before anything is written. --pdf also converts the result with LibreOffice and prints the page count;
no LibreOffice or a failed conversion is an error (exit 1).

Usage: md2docx.py INPUT.md OUTPUT.docx [--title "Document title"] [--strict] [--pdf]
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import zipfile
from xml.sax.saxutils import escape

ACCENT, BORDER, HEADER_FILL = "1F4E79", "BFBFBF", "DCE6F2"
PAGE_W, MARGIN = 11906, 1134            # A4 width and 2 cm margins, in twips
TEXT_W = PAGE_W - 2 * MARGIN
HEADING_SIZE = {1: 32, 2: 26, 3: 23, 4: 21}  # half-points
SOFFICE = ("soffice", "/Applications/LibreOffice.app/Contents/MacOS/soffice")
INLINE = re.compile(r"\*\*(.+?)\*\*|(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])|`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\)")
TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
DASHES = re.compile("[‒–—―]")
CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")  # not allowed in XML: Word would not open the file
UNSUPPORTED = re.compile(r"^\s*(!\[|<[a-zA-Z/]|>|```|~~~)|\[\^|<br", re.I)
warnings = []


def run(text, bold=False, italic=False, mono=False, size=None, color=None):
    props = ("<w:b/>" if bold else "") + ("<w:i/>" if italic else "")
    if mono:
        props += '<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:cs="Consolas"/>'
    if color:
        props += f'<w:color w:val="{color}"/>'
    if size:
        props += f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>'
    return f'<w:r><w:rPr>{props}</w:rPr><w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def inline(text, **base):
    """Runs for one line of markdown text with **bold**, *italic*, `code` and [text](url)."""
    out, pos = [], 0
    for m in INLINE.finditer(text):
        if m.start() > pos:
            out.append(run(text[pos:m.start()], **base))
        bold, italic, code, label, url = m.groups()
        if bold is not None:
            out.append(inline(bold, **{**base, "bold": True}))
        elif italic is not None:
            out.append(run(italic, **{**base, "italic": True}))
        elif code is not None:
            out.append(run(code, **{**base, "mono": True}))
        else:
            out.append(run(label if label == url else f"{label} ({url})", **base))
        pos = m.end()
    if pos < len(text):
        out.append(run(text[pos:], **base))
    return "".join(out)


def para(runs, style=None, num=None, level=0, keep_next=False, page_break=False):
    props = f'<w:pStyle w:val="{style}"/>' if style else ""
    if keep_next:
        props += "<w:keepNext/>"
    if num is not None:
        props += f'<w:numPr><w:ilvl w:val="{level}"/><w:numId w:val="{num}"/></w:numPr>'
    body = '<w:r><w:br w:type="page"/></w:r>' if page_break else runs
    return f"<w:p><w:pPr>{props}</w:pPr>{body}</w:p>"


def table(rows, header=True):
    cols = max(len(r) for r in rows)
    # column widths follow the longest text in each column (bounded), so short number columns stay narrow
    weight = [min(60, max(6, max(len(r[c].strip()) if c < len(r) else 0 for r in rows))) for c in range(cols)]
    widths = [TEXT_W * w // sum(weight) for w in weight]
    border = "".join(f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="{BORDER}"/>'
                     for side in ("top", "left", "bottom", "right", "insideH", "insideV"))
    xml = [f'<w:tbl><w:tblPr><w:tblW w:w="{TEXT_W}" w:type="dxa"/><w:tblBorders>{border}</w:tblBorders>'
           '<w:tblCellMar><w:left w:w="80" w:type="dxa"/><w:right w:w="80" w:type="dxa"/></w:tblCellMar>'
           '</w:tblPr><w:tblGrid>' + "".join(f'<w:gridCol w:w="{w}"/>' for w in widths) + '</w:tblGrid>']
    for i, row in enumerate(rows):
        cells = row + [""] * (cols - len(row))
        head = header and i == 0
        xml.append("<w:tr>" + ('<w:trPr><w:tblHeader/></w:trPr>' if head else ""))
        for cell, width in zip(cells, widths):
            shade = f'<w:shd w:val="clear" w:color="auto" w:fill="{HEADER_FILL}"/>' if head else ""
            xml.append(f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/>{shade}</w:tcPr>'
                       f'{para(inline(cell.strip(), bold=head), style="TableText")}</w:tc>')
        xml.append("</w:tr>")
    xml.append("</w:tbl>")
    return "".join(xml) + para("", style="AfterTable")


def split_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    return [c.replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line)]


def convert(lines):
    """Body XML and the start number of each ordered list (each list gets its own w:num and restarts)."""
    body, i, starts, current_ol, para_buf = [], 0, [], None, []

    def flush():
        if para_buf:
            body.append(para(inline(" ".join(s.strip() for s in para_buf))))
            para_buf.clear()

    while i < len(lines):
        line = lines[i].rstrip("\n")
        stripped = line.strip()
        bullet = re.match(r"^(\s*)[-*+]\s+(.*)$", line)
        number = re.match(r"^(\s*)(\d{1,3})[.)]\s+(.*)$", line)  # "2026. Рік ..." stays a paragraph
        heading = re.match(r"^(#{1,6})\s+(.*?)(?:\s+#+)?\s*$", line)  # "## C#" keeps its "#"
        if not stripped:
            flush()
            current_ol = None
        elif heading:
            flush()
            level = min(len(heading.group(1)), 4)
            body.append(para(inline(heading.group(2)), style=f"Heading{level}", keep_next=True))
            current_ol = None
        elif stripped == "<!-- pagebreak -->":
            flush()
            body.append(para("", page_break=True))
        elif stripped in ("---", "***", "___"):
            flush()
            body.append(para("", style="AfterTable"))
        elif stripped.startswith("|") and i + 1 < len(lines) and TABLE_SEP.match(lines[i + 1]):
            flush()
            rows = [split_row(line)]
            header = any(c.strip() for c in rows[0])
            if not header:
                rows = []  # "| | |" header: a table without a header row
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                if UNSUPPORTED.search(lines[i]):
                    warnings.append(f"рядок {i + 1}: HTML чи зображення в таблиці стануть звичайним текстом")
                rows.append(split_row(lines[i]))
                i += 1
            if rows:
                body.append(table(rows, header=header))
            current_ol = None
            continue
        elif bullet:
            flush()
            level = 1 if len(bullet.group(1).replace("\t", "  ")) >= 2 else 0
            body.append(para(inline(bullet.group(2)), style="ListParagraph", num=1, level=level))
        elif number:
            flush()
            if current_ol is None:
                starts.append(int(number.group(2)))
                current_ol = len(starts) + 1  # numId 1 is the bullet list
            body.append(para(inline(number.group(3)), style="ListParagraph", num=current_ol))
        else:
            if UNSUPPORTED.search(line):
                warnings.append(f"рядок {i + 1}: зображення, HTML, цитата, блок коду чи виноска стануть звичайним текстом")
            para_buf.append(line)
        i += 1
    flush()
    return "".join(body), starts


STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri" w:eastAsia="Calibri"/>
<w:sz w:val="21"/><w:szCs w:val="21"/><w:lang w:val="uk-UA"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="100" w:line="264" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
{"".join(f'''<w:style w:type="paragraph" w:styleId="Heading{n}"><w:name w:val="heading {n}"/><w:basedOn w:val="Normal"/>
<w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="{240 if n < 3 else 160}" w:after="80"/>
<w:outlineLvl w:val="{n - 1}"/></w:pPr><w:rPr><w:b/><w:color w:val="{ACCENT}"/><w:sz w:val="{s}"/><w:szCs w:val="{s}"/></w:rPr></w:style>'''
         for n, s in HEADING_SIZE.items())}
<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/>
<w:pPr><w:spacing w:after="40"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="TableText"><w:name w:val="Table Text"/><w:basedOn w:val="Normal"/>
<w:pPr><w:spacing w:before="40" w:after="40" w:line="240" w:lineRule="auto"/></w:pPr><w:rPr><w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="AfterTable"><w:name w:val="After Table"/><w:basedOn w:val="Normal"/>
<w:pPr><w:spacing w:after="60"/></w:pPr><w:rPr><w:sz w:val="8"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Footer"><w:name w:val="footer"/><w:basedOn w:val="Normal"/>
<w:pPr><w:jc w:val="center"/></w:pPr><w:rPr><w:color w:val="7F7F7F"/><w:sz w:val="18"/></w:rPr></w:style>
</w:styles>"""


def numbering(starts):
    def level(i, fmt, text, indent):
        return (f'<w:lvl w:ilvl="{i}"><w:start w:val="1"/><w:numFmt w:val="{fmt}"/><w:lvlText w:val="{text}"/>'
                f'<w:lvlJc w:val="left"/><w:pPr><w:ind w:left="{indent}" w:hanging="300"/></w:pPr></w:lvl>')
    bullets = level(0, "bullet", "•", 360) + level(1, "bullet", "◦", 720)
    numbers = level(0, "decimal", "%1.", 360) + level(1, "lowerLetter", "%2)", 720)
    nums = '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>' + "".join(
        f'<w:num w:numId="{n + 2}"><w:abstractNumId w:val="1"/>'
        f'<w:lvlOverride w:ilvl="0"><w:startOverride w:val="{start}"/></w:lvlOverride></w:num>'
        for n, start in enumerate(starts))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="hybridMultilevel"/>{bullets}</w:abstractNum>'
            f'<w:abstractNum w:abstractNumId="1"><w:multiLevelType w:val="hybridMultilevel"/>{numbers}</w:abstractNum>'
            f"{nums}</w:numbering>")


W_NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
FOOTER = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr {W_NS}><w:p><w:pPr><w:pStyle w:val="Footer"/></w:pPr>'
          '<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
          '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>1</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r>'
          "</w:p></w:ftr>")


def write_docx(path, body, starts, title):
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {W_NS}><w:body>{body}'
                f'<w:sectPr><w:footerReference w:type="default" r:id="rId3"/><w:pgSz w:w="{PAGE_W}" w:h="16838"/>'
                f'<w:pgMar w:top="{MARGIN}" w:right="{MARGIN}" w:bottom="{MARGIN}" w:left="{MARGIN}" w:header="567" '
                'w:footer="567" w:gutter="0"/></w:sectPr></w:body></w:document>')
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
            '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
            '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            "</Types>"),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{REL}/officeDocument" Target="word/document.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" '
            'Target="docProps/core.xml"/></Relationships>'),
        "word/_rels/document.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{REL}/styles" Target="styles.xml"/>'
            f'<Relationship Id="rId2" Type="{REL}/numbering" Target="numbering.xml"/>'
            f'<Relationship Id="rId3" Type="{REL}/footer" Target="footer1.xml"/></Relationships>'),
        "docProps/core.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f"<dc:title>{escape(title)}</dc:title></cp:coreProperties>"),
        "word/document.xml": document,
        "word/styles.xml": STYLES,
        "word/numbering.xml": numbering(starts),
        "word/footer1.xml": FOOTER,
    }
    tmp = path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    os.replace(tmp, path)


def to_pdf(docx):
    """PDF next to the docx and its page count; None (with the reason on stderr) when there is no fresh PDF."""
    exe = next((p for p in (shutil.which(SOFFICE[0]), SOFFICE[1]) if p and os.path.exists(p)), None)
    if not exe:
        print("pdf: LibreOffice не знайдено, сторінки не пораховано", file=sys.stderr)
        return None
    docx = os.path.abspath(docx)
    pdf = os.path.splitext(docx)[0] + ".pdf"
    if os.path.exists(pdf):
        os.remove(pdf)  # a PDF from an earlier run must not pass for a fresh one
    try:
        r = subprocess.run([exe, "--headless", "--convert-to", "pdf", "--outdir", os.path.dirname(docx), docx],
                           capture_output=True, text=True, timeout=180)
    except (subprocess.SubprocessError, OSError) as e:
        print(f"pdf: конвертація не вдалася: {e}", file=sys.stderr)
        return None
    if r.returncode != 0 or not os.path.exists(pdf):
        detail = (r.stderr or r.stdout).strip().splitlines()[-3:]
        print(f"pdf: конвертація не вдалася (код {r.returncode}): {' | '.join(detail) or 'PDF не створено'}",
              file=sys.stderr)
        return None
    with open(pdf, "rb") as f:
        data = f.read()
    pages = len(re.findall(rb"/Type\s*/Page[^s]", data)) or max(map(int, re.findall(rb"/Count\s+(\d+)", data)), default=0)
    if not pages:
        print(f"pdf: {pdf} створено, але сторінок не знайдено", file=sys.stderr)
        return None
    print(f"pdf: {pdf} ({pages} стор.)")
    return pages


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--title", help="document title in the file properties (default: first heading)")
    ap.add_argument("--strict", action="store_true", help="long dashes are an error, not a warning")
    ap.add_argument("--pdf", action="store_true", help="also convert to PDF with LibreOffice and count pages")
    a = ap.parse_args()
    if not a.output.lower().endswith(".docx"):
        ap.error("OUTPUT must end with .docx")
    try:
        with open(a.input, encoding="utf-8-sig") as f:  # -sig: a BOM must not hide the first heading
            lines = f.read().replace("\r\n", "\n").split("\n")
    except (OSError, UnicodeDecodeError) as e:
        sys.exit(f"помилка: не можу прочитати {a.input}: {e}")
    bad = [n + 1 for n, line in enumerate(lines) if CONTROL.search(line)]
    if bad:
        warnings.append(f"керівні символи прибрано в рядках: {', '.join(map(str, bad[:20]))}")
        lines = [CONTROL.sub("", line) for line in lines]
    title = CONTROL.sub("", a.title or next((re.sub(r"^#+\s*", "", l).strip() for l in lines if l.startswith("#")),
                                            "Документ"))
    dashes = [n + 1 for n, line in enumerate(lines) if DASHES.search(line)]
    title_dash = bool(DASHES.search(title))
    if dashes or title_dash:
        where = ([f"рядки {', '.join(map(str, dashes[:20]))}" + (" …" if len(dashes) > 20 else "")] if dashes else []) \
            + (["назва документа"] if title_dash else [])
        warnings.append("довгі тире: " + "; ".join(where))
    body, starts = convert(lines)
    for w in warnings:
        print("увага: " + w, file=sys.stderr)
    if a.strict and (dashes or title_dash):
        sys.exit("помилка: у клієнтському тексті є довгі тире; файли не записано")
    write_docx(a.output, body, starts, title)
    print(f"docx: {a.output}")
    if a.pdf and to_pdf(a.output) is None:
        sys.exit("помилка: PDF не отримано, сторінки не перевірено")


if __name__ == "__main__":
    main()
