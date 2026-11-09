"""Build a resume from reviewed, source-backed content; never contacts recruiters."""
import argparse
import json
from pathlib import Path


def build(data, output):
    from docx import Document
    from docx.shared import Cm, Pt, RGBColor
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.top_margin, section.bottom_margin = Cm(1.7), Cm(1.6)
    section.left_margin = section.right_margin = Cm(1.9)
    for name in ('Normal', 'Title', 'Heading 1', 'Heading 2', 'List Bullet'):
        style = document.styles[name]
        style.font.name = 'Arial Unicode MS'
        fonts = style._element.rPr.rFonts
        for attribute in list(fonts.attrib):
            if attribute.endswith('Theme') or attribute.endswith('theme'):del fonts.attrib[attribute]
        fonts.set(qn('w:eastAsia'), 'Arial Unicode MS')
        style.font.color.rgb = RGBColor(0, 0, 0)
    for border in document.styles.element.xpath('//w:pBdr'):
        border.getparent().remove(border)
    normal = document.styles['Normal']
    normal.font.size = Pt(10.5)
    normal.paragraph_format.line_spacing = 1.16
    normal.paragraph_format.space_after = Pt(5)
    for name, size in [('Title', 23), ('Heading 1', 13), ('Heading 2', 11)]:
        style = document.styles[name]
        style.font.size = Pt(size)
        style.paragraph_format.space_before = Pt(10)
        style.paragraph_format.space_after = Pt(5)
        style.paragraph_format.keep_with_next = True
    document.add_paragraph(data['name'], 'Title')
    document.add_paragraph(data['target'])
    document.add_paragraph('  |  '.join(data['contacts']))
    for page_index, page in enumerate(data['pages']):
        if page_index:
            document.add_page_break()
        for block in page:
            if block.get('heading'):
                document.add_paragraph(block['heading'], 'Heading 1')
            if block.get('subheading'):
                document.add_paragraph(block['subheading'], 'Heading 2')
            for text in block.get('paragraphs', []):
                document.add_paragraph(text)
            for text in block.get('bullets', []):
                paragraph = document.add_paragraph(text, 'List Bullet')
                paragraph.paragraph_format.keep_together = True
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    document.core_properties.author = data['name']
    document.core_properties.title = data['name'] + ' ' + data['target']
    document.save(output)
    output.chmod(0o600)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(build(json.loads(Path(args.input).read_text()), args.output).resolve())
