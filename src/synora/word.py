"""Kural setinden stilleri hazır Word şablonu (.docx) üretir — A12'nin Word karşılığı.

Girdi yalnızca doğrulanmış `Ruleset`; kullanıcı dosyası alınmaz, yeni saldırı yüzeyi yoktur.
Üretilen şablon sentetik örnek içerik taşır ve **kendi kural setinden sıfır bulguyla geçmek
zorundadır** (testle zorlanır): kılavuz YAML'da değişince şablon da onunla birlikte değişir.
Çıktı deterministiktir (sabit zip zaman damgası): aynı kural seti → aynı baytlar.
"""

from __future__ import annotations

import io
import zipfile

from synora.model import Role
from synora.ruleset import LineSpacingRule, RoleRules, Ruleset

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'

# twips (1/20 pt); A4 210×297 mm vb.
PAGE_SIZES = {"A4": (11906, 16838), "A5": (8391, 11906), "B5": (9979, 14175),
              "Letter": (12240, 15840)}
DEFAULT_MARGIN_CM = 2.5
JC = {"left": "left", "center": "center", "right": "right", "justify": "both"}

# Üretilen stiller: rol → (styleId, Word stil adı). Adlar Word'ün yerleşik adları:
# parser stil kalıtımını ve sınıflandırıcı stil kategorisini bunlardan tanır.
STYLE_OF: dict[Role, tuple[str, str]] = {
    Role.BODY: ("Normal", "Normal"),
    Role.TITLE: ("Title", "Title"),
    Role.HEADING_1: ("Heading1", "heading 1"),
    Role.HEADING_2: ("Heading2", "heading 2"),
    Role.HEADING_3: ("Heading3", "heading 3"),
    Role.FIGURE_CAPTION: ("Caption", "caption"),
    Role.BLOCK_QUOTE: ("Quote", "Quote"),
    Role.REFERENCE_ENTRY: ("Bibliography", "Bibliography"),
}


def escape(text: str) -> str:
    """XML metin kaçışı (yalnızca üretim; parse edilmez — xmlsafe kuralı okuma içindir)."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def quoteattr(text: str) -> str:
    return '"' + escape(text).replace('"', "&quot;") + '"'


def _twips(cm: float) -> int:
    return round(cm / 2.54 * 1440)


def _spacing_attrs(rule: LineSpacingRule | None, rr: RoleRules) -> str:
    parts: list[str] = []
    if rule is not None:
        if rule.multiple is not None:
            parts.append(f'w:line="{round(rule.multiple * 240)}" w:lineRule="auto"')
        elif rule.exact_pt is not None:
            parts.append(f'w:line="{round(rule.exact_pt * 20)}" w:lineRule="exact"')
        elif rule.at_least_pt is not None:
            parts.append(f'w:line="{round(rule.at_least_pt * 20)}" w:lineRule="atLeast"')
    if rr.space_before_pt is not None:
        parts.append(f'w:before="{round(rr.space_before_pt * 20)}"')
    if rr.space_after_pt is not None:
        parts.append(f'w:after="{round(rr.space_after_pt * 20)}"')
    return " ".join(parts)


def _ppr(rr: RoleRules) -> str:
    out: list[str] = []
    if rr.page_break_before:
        out.append("<w:pageBreakBefore/>")
    spacing = _spacing_attrs(rr.spacing_rule(), rr)
    if spacing:
        out.append(f"<w:spacing {spacing}/>")
    ind: list[str] = []
    if rr.indent_left_cm is not None:
        ind.append(f'w:left="{_twips(rr.indent_left_cm)}"')
    if rr.first_line_indent_cm is not None:
        ind.append(f'w:firstLine="{_twips(rr.first_line_indent_cm)}"')
    if ind:
        out.append(f"<w:ind {' '.join(ind)}/>")
    if rr.alignment is not None:
        out.append(f'<w:jc w:val="{JC[rr.alignment.value]}"/>')
    return "".join(out)


def _rpr(rr: RoleRules, rules: Ruleset) -> str:
    out: list[str] = []
    fonts = rr.font or rules.fonts.allowed
    if fonts:
        f = quoteattr(fonts[0])
        out.append(f"<w:rFonts w:ascii={f} w:hAnsi={f} w:cs={f}/>")
    if rr.bold:
        out.append("<w:b/>")
    if rr.italic:
        out.append("<w:i/>")
    if rr.all_caps:
        out.append("<w:caps/>")
    if rr.size_pt is not None:
        half = round(rr.size_pt * 2)
        out.append(f'<w:sz w:val="{half}"/><w:szCs w:val="{half}"/>')
    return "".join(out)


def _style(style_id: str, name: str, rr: RoleRules, rules: Ruleset, *,
           default: bool = False, based_on: str | None = None) -> str:
    ppr, rpr = _ppr(rr), _rpr(rr, rules)
    bits = [f'<w:style w:type="paragraph" w:styleId="{style_id}"'
            + (' w:default="1"' if default else "") + ">",
            f'<w:name w:val="{name}"/>']
    if based_on:
        bits.append(f'<w:basedOn w:val="{based_on}"/>')
    if ppr:
        bits.append(f"<w:pPr>{ppr}</w:pPr>")
    if rpr:
        bits.append(f"<w:rPr>{rpr}</w:rPr>")
    bits.append("</w:style>")
    return "".join(bits)


def _styles_xml(rules: Ruleset) -> str:
    body = rules.roles.get(Role.BODY, RoleRules())
    styles = [_style("Normal", "Normal", body, rules, default=True)]
    for role, (style_id, name) in STYLE_OF.items():
        if role is Role.BODY:
            continue
        rr = rules.roles.get(role)
        if rr is None and role is Role.FIGURE_CAPTION:
            rr = rules.roles.get(Role.TABLE_CAPTION)  # tek 'caption' stili ikisine de hizmet eder
        if rr is None:
            continue
        styles.append(_style(style_id, name, rr, rules, based_on="Normal"))
    if Role.FRONT_MATTER in rules.roles:
        styles.append(_style("OnSayfa", "Ön Sayfa Metni", rules.roles[Role.FRONT_MATTER],
                             rules, based_on="Normal"))
    return f'{XML_DECL}<w:styles xmlns:w="{W_NS}">{"".join(styles)}</w:styles>'


def _p(text: str, style: str | None = None, ppr: str = "") -> str:
    style_xml = f'<w:pStyle w:val="{style}"/>' if style else ""
    ppr_el = f"<w:pPr>{style_xml}{ppr}</w:pPr>" if (style_xml or ppr) else ""
    run = f'<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r>' if text else ""
    return f"<w:p>{ppr_el}{run}</w:p>"


def _sect_pr(rules: Ruleset, fmt: str | None, *, footer_rel: str | None,
             header_rel: str | None, start_one: bool = False) -> str:
    page = rules.page
    w_, h = PAGE_SIZES.get(page.size or "A4", PAGE_SIZES["A4"])
    orient = ""
    if page.orientation == "landscape":
        w_, h = h, w_
        orient = ' w:orient="landscape"'
    m = page.margins_cm
    sides = {s: _twips(getattr(m, s, None) or DEFAULT_MARGIN_CM if m else DEFAULT_MARGIN_CM)
             for s in ("top", "bottom", "left", "right")}
    refs = ""
    if footer_rel:
        refs += f'<w:footerReference w:type="default" r:id="{footer_rel}"/>'
    if header_rel:
        refs += f'<w:headerReference w:type="default" r:id="{header_rel}"/>'
    num = ""
    if fmt:
        start = ' w:start="1"' if start_one else ""
        num = f'<w:pgNumType w:fmt="{fmt}"{start}/>'
    return (f"<w:sectPr>{refs}<w:pgSz w:w=\"{w_}\" w:h=\"{h}\"{orient}/>"
            f'<w:pgMar w:top="{sides["top"]}" w:bottom="{sides["bottom"]}" '
            f'w:left="{sides["left"]}" w:right="{sides["right"]}" '
            f'w:header="709" w:footer="709" w:gutter="0"/>{num}</w:sectPr>')


_PAGE_FIELD = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
               '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
               '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
               "<w:r><w:t>1</w:t></w:r>"
               '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def _number_part(rules: Ruleset, tag: str) -> str:
    position = rules.page_numbering.position or "bottom_center"
    jc = position.split("_", 1)[1]
    return (f'{XML_DECL}<w:{tag} xmlns:w="{W_NS}">'
            f'<w:p><w:pPr><w:jc w:val="{jc}"/></w:pPr>{_PAGE_FIELD}</w:p></w:{tag}>')


def _sample_body(rules: Ruleset, footer_rel: str | None, header_rel: str | None) -> str:
    """Sentetik örnek içerik: ön sayfa bölümü (gerekirse) + ana metin. Gerçek tez metni yok."""
    fmts = [f.value for f in rules.page_numbering.formats_in_order]
    body_sample = ("Bu paragraf, şablonun gövde metni stilini gösteren sentetik bir örnektir. "
                   "Kendi metninizi bu stille yazın; biçim ayarları kılavuzdan hazır gelir.")
    h1 = rules.roles.get(Role.HEADING_1)
    # Başlık örnekleri kuralın istediği düzende: büyük harf kuralı yoksa ve bir
    # büyük/küçük düzeni isteniyorsa "GİRİŞ" yerine "Giriş" yazılır.
    plain_h1 = h1 is not None and not h1.all_caps and h1.case is not None

    def h1_text(upper: str, mixed: str) -> str:
        return mixed if plain_h1 else upper

    parts: list[str] = []
    multi = len(fmts) >= 2
    if multi:
        parts.append(_p(h1_text("ÖNSÖZ", "Önsöz"), "Heading1"))
        parts.append(_p(body_sample, "OnSayfa" if Role.FRONT_MATTER in rules.roles else None))
        front_sect = _sect_pr(rules, fmts[0], footer_rel=footer_rel, header_rel=header_rel)
        parts.append(f"<w:p><w:pPr>{front_sect}</w:pPr></w:p>")
    parts.append(_p(h1_text("GİRİŞ", "Giriş"), "Heading1"))
    parts.append(_p(body_sample, None))
    def heading_sample(role: Role, title_text: str, sentence_text: str) -> str:
        rr = rules.roles.get(role)
        return title_text if rr is not None and rr.case == "title" else sentence_text

    if Role.HEADING_2 in rules.roles:
        parts.append(_p(heading_sample(Role.HEADING_2, "Örnek Alt Başlık",
                                       "Örnek alt başlık"), "Heading2"))
        parts.append(_p(body_sample, None))
    if Role.HEADING_3 in rules.roles:
        parts.append(_p(heading_sample(Role.HEADING_3, "Örnek Üçüncü Düzey Başlık",
                                       "Örnek üçüncü düzey başlık"), "Heading3"))
        parts.append(_p(body_sample, None))
    caption = rules.roles.get(Role.FIGURE_CAPTION) or rules.roles.get(Role.TABLE_CAPTION)
    if caption is not None:
        caption_text = ("Şekil 1.1. Örnek Şekil Açıklaması" if caption.case == "title"
                        else "Şekil 1.1. Örnek şekil açıklaması")
        parts.append(_p(caption_text, "Caption"))
    if Role.REFERENCE_ENTRY in rules.roles:
        parts.append(_p(h1_text("KAYNAKLAR", "Kaynaklar"), "Heading1"))
        parts.append(_p("Yazar, A. (2020). Örnek kaynak başlığı. Örnek Yayınevi.",
                        "Bibliography"))
    body_fmt = fmts[1] if multi else (fmts[0] if fmts else None)
    if len(fmts) <= 2:
        parts.append(_sect_pr(rules, body_fmt, footer_rel=footer_rel, header_rel=header_rel,
                              start_one=multi))
        return "".join(parts)
    # Üç ve daha çok biçim (ör. roman, arabic, ROMAN): kalan her biçim için ek bölüm (EKLER).
    body_sect = _sect_pr(rules, body_fmt, footer_rel=footer_rel, header_rel=header_rel,
                         start_one=True)
    parts.append(f"<w:p><w:pPr>{body_sect}</w:pPr></w:p>")
    for i, fmt in enumerate(fmts[2:]):
        parts.append(_p(h1_text("EKLER", "Ekler"), "Heading1"))
        parts.append(_p(body_sample, None))
        sect = _sect_pr(rules, fmt, footer_rel=footer_rel, header_rel=header_rel,
                        start_one=True)
        if i < len(fmts) - 3:
            parts.append(f"<w:p><w:pPr>{sect}</w:pPr></w:p>")
        else:
            parts.append(sect)
    return "".join(parts)


def build_docx(rules: Ruleset) -> bytes:
    position = rules.page_numbering.position or "bottom_center"
    at_top = position.startswith("top_")
    number_tag, number_name = ("hdr", "header1") if at_top else ("ftr", "footer1")
    footer_rel = None if at_top else "rId2"
    header_rel = "rId2" if at_top else None

    document = (f'{XML_DECL}<w:document xmlns:w="{W_NS}" xmlns:r="{OFFICE_REL}">'
                f"<w:body>{_sample_body(rules, footer_rel, header_rel)}</w:body></w:document>")
    rel_type = "header" if at_top else "footer"
    doc_rels = (f'{XML_DECL}<Relationships xmlns="{REL_NS}">'
                f'<Relationship Id="rId1" Type="{OFFICE_REL}/styles" Target="styles.xml"/>'
                f'<Relationship Id="rId2" Type="{OFFICE_REL}/{rel_type}" '
                f'Target="{number_name}.xml"/></Relationships>')
    number_ct = ("header" if at_top else "footer") + "+xml"
    ct_base = "application/vnd.openxmlformats-officedocument.wordprocessingml"
    content_types = (
        f'{XML_DECL}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType='
        '"application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'<Override PartName="/word/document.xml" ContentType="{ct_base}.document.main+xml"/>'
        f'<Override PartName="/word/styles.xml" ContentType="{ct_base}.styles+xml"/>'
        f'<Override PartName="/word/{number_name}.xml" ContentType="{ct_base}.{number_ct}"/>'
        "</Types>")
    root_rels = (f'{XML_DECL}<Relationships xmlns="{REL_NS}">'
                 f'<Relationship Id="rId1" Type="{OFFICE_REL}/officeDocument" '
                 'Target="word/document.xml"/></Relationships>')
    parts = {
        "[Content_Types].xml": content_types,
        "_rels/.rels": root_rels,
        "word/document.xml": document,
        "word/_rels/document.xml.rels": doc_rels,
        "word/styles.xml": _styles_xml(rules),
        f"word/{number_name}.xml": _number_part(rules, number_tag),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name in sorted(parts):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, parts[name].encode("utf-8"))
    return buf.getvalue()
