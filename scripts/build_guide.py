"""Build the public PDF from Markdown and fictitious captures. No network access."""
from html import escape
from pathlib import Path
import re

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph,
                               Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle)

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT/'docs'
OUTPUT = DOCS/'guide-camptocamp-workbench.pdf'
WIDTH, HEIGHT = A4
MARGIN = 43
BODY_WIDTH = WIDTH-2*MARGIN


def inline(text):
    text = escape(text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)
    return re.sub(r'`([^`]+)`', r'<font name="Lato-Bold">\1</font>', text)


def build():
    for name, file in [('Lato', 'Lato-Regular.ttf'), ('Lato-Bold', 'Lato-Bold.ttf')]:
        pdfmetrics.registerFont(TTFont(name, str(ROOT/'web/fonts'/file)))
    pdfmetrics.registerFontFamily('Lato', normal='Lato', bold='Lato-Bold', italic='Lato', boldItalic='Lato-Bold')
    s = getSampleStyleSheet()
    s.add(ParagraphStyle(name='Body', fontName='Lato', fontSize=10.8, leading=15.5,
                         textColor=colors.HexColor('#25313D'), spaceAfter=9))
    s.add(ParagraphStyle(name='Chapter', fontName='Lato-Bold', fontSize=23, leading=28,
                         textColor=colors.HexColor('#25313D'), spaceAfter=18, keepWithNext=True))
    s.add(ParagraphStyle(name='Section', fontName='Lato-Bold', fontSize=13.1, leading=18,
                         spaceBefore=11, spaceAfter=7, keepWithNext=True))
    s.add(ParagraphStyle(name='List', parent=s['Body'], leftIndent=13, firstLineIndent=-10,
                         fontSize=10.5, leading=15, spaceAfter=6))
    s.add(ParagraphStyle(name='Cell', parent=s['Body'], fontSize=9.1, leading=12.5, spaceAfter=0))
    s.add(ParagraphStyle(name='HeadCell', parent=s['Cell'], fontName='Lato-Bold', textColor=colors.white))
    s.add(ParagraphStyle(name='Caption', parent=s['Body'], fontSize=8.6, leading=12,
                         textColor=colors.HexColor('#5D6A77'), spaceAfter=10))
    s.add(ParagraphStyle(name='CodeBlock', fontName='Courier', fontSize=8, leading=11,
                         backColor=colors.HexColor('#F3F5F7'), borderPadding=9,
                         spaceBefore=4, spaceAfter=12, textColor=colors.HexColor('#25313D')))
    s.add(ParagraphStyle(name='CoverTitle', parent=s['Chapter'], fontSize=34, leading=39, spaceAfter=14))
    story, index = [], 0
    lines = (DOCS/'guide.md').read_text(encoding='utf-8').splitlines()
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1; continue
        if line.startswith('# '):
            logo = Image(str(ROOT/'web/brand/camptocamp-logo.png'), width=150, height=54, kind='proportional')
            logo.hAlign = 'LEFT'
            story += [logo, Spacer(1, 48), Paragraph('GUIDE PRATIQUE', s['Caption']),
                      Paragraph(inline(line[2:]), s['CoverTitle'])]
            index += 1; continue
        if line.startswith('## '):
            story += [PageBreak(), Paragraph(inline(line[3:]), s['Chapter'])]
            index += 1; continue
        if line.startswith('### '):
            story.append(Paragraph(inline(line[4:]), s['Section']))
            index += 1; continue
        if line.startswith('```'):
            code = []; index += 1
            while index < len(lines) and not lines[index].startswith('```'):
                code.append(lines[index]); index += 1
            story.append(Preformatted('\n'.join(code), s['CodeBlock'], maxLineLength=98))
            index += 1; continue
        picture = re.fullmatch(r'!\[([^]]*)\]\(([^)]+)\)', line)
        if picture:
            path = (DOCS/picture[2]).resolve()
            if not path.is_relative_to(DOCS) or not path.is_file():
                raise ValueError('Capture absente ou hors du dossier docs')
            img = Image(str(path))
            img.drawHeight = img.imageHeight*BODY_WIDTH/img.imageWidth
            img.drawWidth = BODY_WIDTH
            story.append(KeepTogether([img, Spacer(1, 4), Paragraph(inline(picture[1]), s['Caption'])]))
            index += 1; continue
        if line.startswith('|'):
            rows = []
            while index < len(lines) and lines[index].strip().startswith('|'):
                cells = [c.strip() for c in lines[index].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-+:?', c) for c in cells):
                    rows.append(cells)
                index += 1
            count = len(rows[0])
            widths = [BODY_WIDTH/count]*count if count != 2 else [BODY_WIDTH*.32, BODY_WIDTH*.68]
            data = [[Paragraph(inline(c), s['HeadCell'] if r == 0 else s['Cell']) for c in row] for r, row in enumerate(rows)]
            table = Table(data, colWidths=widths, repeatRows=1, hAlign='LEFT')
            table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#54636E')),
                ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#F3F5F7'), colors.white]),
                ('VALIGN', (0,0), (-1,-1), 'TOP'), ('LEFTPADDING', (0,0), (-1,-1), 9),
                ('RIGHTPADDING', (0,0), (-1,-1), 9), ('TOPPADDING', (0,0), (-1,-1), 9),
                ('BOTTOMPADDING', (0,0), (-1,-1), 9)]))
            story += [table, Spacer(1, 10)]; continue
        listing = line.startswith('- ') or bool(re.match(r'^\d+\. ', line))
        chunk = [line[2:] if line.startswith('- ') else line]; index += 1
        while index < len(lines) and lines[index].strip() and not re.match(r'^(#|```|\||!\[|- |\d+\. )', lines[index].strip()):
            chunk.append(lines[index].strip()); index += 1
        text = ('• ' if listing and line.startswith('- ') else '') + ' '.join(chunk)
        story.append(Paragraph(inline(text), s['List' if listing else 'Body']))

    def decorate(canvas, doc):
        canvas.saveState(); canvas.setFont('Lato', 8); canvas.setFillColor(colors.HexColor('#5D6A77'))
        if doc.page > 1:
            canvas.drawString(MARGIN, HEIGHT-29, 'CAMPTOCAMP WORKBENCH')
        canvas.drawString(MARGIN, 26, 'Guide du consultant  /  10 novembre 2026')
        canvas.drawRightString(WIDTH-MARGIN, 26, str(doc.page)); canvas.restoreState()

    document = SimpleDocTemplate(str(OUTPUT), pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                                 topMargin=56, bottomMargin=48, title='OpenClaw et Camptocamp Workbench - Guide explicatif',
                                 author='Camptocamp Workbench', subject='Installation, emails, releases et méthode de travail')
    document.build(story, onFirstPage=decorate, onLaterPages=decorate)
    print(OUTPUT)


if __name__ == '__main__':
    build()
