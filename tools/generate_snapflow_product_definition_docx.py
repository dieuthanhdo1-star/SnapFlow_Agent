#!/usr/bin/env python3
"""Generate the one-page SnapFlow product-definition DOCX without external deps."""

from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "deliverables" / "snapflow" / "SnapFlow_截图行动Agent_产品定义_V0.1.docx"


def run_props(*, size=19, bold=False, color="24364B"):
    parts = [
        '<w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="Microsoft YaHei"/>',
        f'<w:color w:val="{color}"/>',
        f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>',
    ]
    if bold:
        parts.append("<w:b/><w:bCs/>")
    return "<w:rPr>" + "".join(parts) + "</w:rPr>"


def paragraph(text="", *, size=19, bold=False, color="24364B", before=0, after=55,
              line=260, align=None, keep=False, shade=None):
    ppr = [f'<w:spacing w:before="{before}" w:after="{after}" w:line="{line}" w:lineRule="auto"/>']
    if align:
        ppr.append(f'<w:jc w:val="{align}"/>')
    if keep:
        ppr.append("<w:keepNext/><w:keepLines/>")
    if shade:
        ppr.append(f'<w:shd w:val="clear" w:color="auto" w:fill="{shade}"/>')
    safe = escape(text)
    return (
        "<w:p><w:pPr>" + "".join(ppr) + "</w:pPr><w:r>" +
        run_props(size=size, bold=bold, color=color) +
        f'<w:t xml:space="preserve">{safe}</w:t></w:r></w:p>'
    )


def heading(number, title):
    return paragraph(f"{number} ｜ {title}", size=22, bold=True, color="1F4E79", before=75, after=45, keep=True)


def bullet(text):
    return paragraph(f"•  {text}", size=18, after=25, line=245)


def cell(contents, width=4800, fill="FFFFFF"):
    return (
        "<w:tc><w:tcPr>"
        f'<w:tcW w:w="{width}" w:type="dxa"/>'
        f'<w:shd w:val="clear" w:color="auto" w:fill="{fill}"/>'
        '<w:tcMar><w:top w:w="120" w:type="dxa"/><w:left w:w="145" w:type="dxa"/>'
        '<w:bottom w:w="110" w:type="dxa"/><w:right w:w="145" w:type="dxa"/></w:tcMar>'
        "</w:tcPr>" + "".join(contents) + "</w:tc>"
    )


def table(cells, *, widths, borders=True, gap=110):
    if borders:
        border_xml = (
            '<w:tblBorders><w:top w:val="single" w:sz="5" w:color="D9E2EC"/>'
            '<w:left w:val="single" w:sz="5" w:color="D9E2EC"/>'
            '<w:bottom w:val="single" w:sz="5" w:color="D9E2EC"/>'
            '<w:right w:val="single" w:sz="5" w:color="D9E2EC"/>'
            '<w:insideH w:val="nil"/><w:insideV w:val="single" w:sz="5" w:color="D9E2EC"/>'
            '</w:tblBorders>'
        )
    else:
        border_xml = '<w:tblBorders><w:top w:val="nil"/><w:left w:val="nil"/><w:bottom w:val="nil"/><w:right w:val="nil"/><w:insideH w:val="nil"/><w:insideV w:val="nil"/></w:tblBorders>'
    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)
    return (
        '<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/>'
        '<w:tblLayout w:type="fixed"/>'
        f'<w:tblCellSpacing w:w="{gap}" w:type="dxa"/>' + border_xml +
        '</w:tblPr><w:tblGrid>' + grid + '</w:tblGrid><w:tr>' + "".join(cells) + '</w:tr></w:tbl>'
    )


def build_document_xml():
    title = paragraph("SnapFlow 截图行动 Agent", size=48, bold=True, color="102A43", after=20, line=500)
    subtitle = paragraph("从“以后再看”到“现在能做”的多模态行动助手", size=21, color="627D98", after=105)
    callout = table(
        [cell([paragraph("一句话价值：将截图中未被处理的用户意图，转化为可确认、可执行、可跟进的任务与日程。", size=21, bold=True, color="163B65", after=0)], width=9700, fill="EEF5FF")],
        widths=[9700], borders=False, gap=0,
    )

    left = [
        heading("01", "目标用户"),
        paragraph("经常使用截图保存活动、作业、报名和资料，但很少再次整理或打开的大学生。", size=18),
        heading("02", "核心问题"),
        bullet("截图只完成了“保存”，没有承接后续行动。"),
        bullet("活动时间、报名截止日期和地点混在图片中。"),
        bullet("用户容易忘记、错过或重复整理信息。"),
        heading("03", "产品解法"),
        paragraph("用户上传截图后，Agent 理解图片内容和潜在意图，提取标题、时间、截止日期和地点，自主建议创建日程、任务或收藏；经用户确认后调用工具，并在未来持续跟进。", size=18),
    ]

    right = [
        heading("04", "MVP 范围"),
        paragraph("支持：活动海报 → 日程；作业/报名 → 任务；普通资料 → 收藏。", size=18, bold=True, color="1F5FAA"),
        paragraph("暂不支持：自动读取整个相册、商品比价、地图推荐、自动报名/下单、未经确认的外部操作。", size=18),
        heading("05", "核心闭环"),
        paragraph("上传截图 → 识别内容与意图 → 建议行动", size=18, bold=True, color="FFFFFF", align="center", after=20, line=250, shade="102A43"),
        paragraph("用户确认 → 调用工具 → 保存状态 → 定时跟进", size=18, bold=True, color="FFFFFF", align="center", after=50, line=250, shade="102A43"),
        paragraph("Agent 的关键不是“识图后回答”，而是根据上下文选择行动，记住任务状态，并在合适时间重新触发。", size=18),
        heading("06", "产品原则与指标"),
        bullet("准确优先：不确定时主动询问，不自行猜测。"),
        bullet("用户掌控：外部动作前必须获得确认。"),
        bullet("隐私默认：只处理用户主动上传的截图。"),
        bullet("核心指标：意图识别准确率、建议接受率、工具执行成功率。"),
    ]

    columns = table(
        [cell(left, width=4800), cell(right, width=4800)],
        widths=[4800, 4800], borders=True, gap=100,
    )
    footer = paragraph("项目阶段：4天 MVP 验证版　·　建议路线：扣子低代码应用 + 视觉模型 + 数据库 + 飞书任务/日程", size=16, color="829AB1", before=85, after=0)

    body = paragraph("PRODUCT DEFINITION  ·  V0.1", size=16, bold=True, color="3E7BFA", after=25) + title + subtitle + callout + columns + footer
    sect = (
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="680" w:right="720" w:bottom="620" w:left="720" w:header="300" w:footer="300" w:gutter="0"/>'
        '<w:cols w:space="720"/><w:docGrid w:linePitch="312"/></w:sectPr>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<w:body>' + body + sect + '</w:body></w:document>'
    )


def write_docx():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    files = {
        "[Content_Types].xml": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>''',
        "_rels/.rels": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>''',
        "word/document.xml": build_document_xml(),
        "word/_rels/document.xml.rels": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>
</Relationships>''',
        "word/styles.xml": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="Microsoft YaHei"/><w:sz w:val="19"/><w:szCs w:val="19"/><w:lang w:val="zh-CN" w:eastAsia="zh-CN"/></w:rPr></w:rPrDefault></w:docDefaults>
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
</w:styles>''',
        "word/settings.xml": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:zoom w:percent="100"/><w:defaultTabStop w:val="420"/><w:characterSpacingControl w:val="doNotCompress"/></w:settings>''',
        "docProps/core.xml": f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>SnapFlow 截图行动 Agent｜产品定义 V0.1</dc:title><dc:subject>4天 MVP 验证版</dc:subject><dc:creator>SnapFlow Project</dc:creator><cp:lastModifiedBy>SnapFlow Project</cp:lastModifiedBy><dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created><dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified></cp:coreProperties>''',
        "docProps/app.xml": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><Application>Microsoft Office Word</Application><DocSecurity>0</DocSecurity><ScaleCrop>false</ScaleCrop><Company></Company><LinksUpToDate>false</LinksUpToDate><SharedDoc>false</SharedDoc><HyperlinksChanged>false</HyperlinksChanged><AppVersion>16.0000</AppVersion></Properties>''',
    }
    with ZipFile(OUTPUT, "w", ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content.encode("utf-8"))
    return OUTPUT


if __name__ == "__main__":
    print(write_docx())
