"""Readability checks for CVs bound to a positioning selection."""
from __future__ import annotations

from pathlib import Path
import subprocess
from xml.etree import ElementTree


def readable_latex(source: str) -> str:
    """Keep standard small-text commands readable without changing legacy templates."""
    marker = r'\begin{document}'
    if marker not in source:
        raise ValueError('resume template has no document body')
    overrides = '\n'.join(
        '\\renewcommand{\\' + name + r'}{\fontsize{10}{12}\selectfont}'
        for name in ('small', 'footnotesize', 'scriptsize', 'tiny')
    )
    return source.replace(marker, overrides + '\n' + marker, 1)


def validate_pdf_xml(xml: str) -> None:
    """Poppler at zoom=1 reports PDF font sizes rounded to points."""
    document = ElementTree.fromstring(xml)
    pages = document.findall('page')
    if len(pages) != 1:
        raise ValueError('positioned CV must be exactly one page')
    count = 0
    for page in pages:
        width = float(page.attrib.get('width', 0))
        height = float(page.attrib.get('height', 0))
        if abs(width - 595.28) > 2 or abs(height - 841.89) > 2:
            raise ValueError('positioned CV must use portrait A4 paper')
        margin = 12 * 72 / 25.4 - 1.5  # allow Poppler coordinate rounding
        fonts = {font.attrib['id']: float(font.attrib['size']) for font in page.findall('fontspec')}
        for element in page.findall('text'):
            if not ''.join(element.itertext()).strip():
                continue
            count += 1
            if fonts.get(element.attrib.get('font'), 0) < 10:
                raise ValueError('positioned CV contains text below 10pt; revise content or template')
            left = float(element.attrib.get('left', -1))
            top = float(element.attrib.get('top', -1))
            right = left + float(element.attrib.get('width', 0))
            bottom = top + float(element.attrib.get('height', 0))
            if left < margin or top < margin or right > width - margin or bottom > height - margin:
                raise ValueError('positioned CV text exceeds 12mm margins; wrap or revise layout')
    if not count:
        raise ValueError('positioned CV has no readable text')


def validate_pdf(path: Path) -> None:
    result = subprocess.run(
        ['pdftohtml', '-xml', '-stdout', '-zoom', '1', '-hidden', str(path)],
        check=True, capture_output=True, text=True, timeout=30,
    )
    validate_pdf_xml(result.stdout)
