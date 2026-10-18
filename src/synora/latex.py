"""A12 — LaTeX şablonu: kural setinden Overleaf'e yüklenebilir bir tez şablonu üretir.

Synora .docx denetler; LaTeX ile yazan öğrenci için aynı kural setinden biçimi hazır ayarlanmış bir
belge sınıfı (.cls), örnek tez, örnek kaynakça ve açıklama üretilir. Hiçbir şey derlenmez, hiçbir
kullanıcı girdisi okunmaz: girdi yalnızca doğrulanmış `Ruleset`. Aynı kural seti her zaman bayt
bayt aynı .zip'i verir (zaman damgası yok).
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field

from synora.model import Alignment, Role
from synora.ruleset import LineSpacingRule, PageNumberFormat, RoleRules, Ruleset

# \ProvidesClass tarihi: şablon üreticisinin sürümü (kural setinin değil).
GENERATOR_DATE = "2026/10/18"
GENERATOR_VERSION = 1

# Yazı tipi adı LaTeX komutuna yazılacağı için yalnızca bu karakterlere izin verilir.
_SAFE_FONT = re.compile(r"[A-Za-z0-9 ._-]{1,64}")

# Kılavuzlarda sık geçen yazı tipleri → (pdfLaTeX paketi, XeLaTeX/LuaLaTeX yedek yazı tipi).
_FONTS: dict[str, tuple[str, str]] = {
    "times new roman": ("\\RequirePackage{newtxtext,newtxmath}", "TeX Gyre Termes"),
    "arial": ("\\RequirePackage[scaled]{helvet}\n"
              "  \\renewcommand{\\familydefault}{\\sfdefault}", "TeX Gyre Heros"),
    "calibri": ("\\RequirePackage[sfdefault,lf]{carlito}", "Carlito"),
}

_PAPER = {"A4": "a4paper", "A5": "a5paper", "B5": "b5paper", "Letter": "letterpaper"}
_PAGENUM = {PageNumberFormat.ARABIC: "arabic", PageNumberFormat.LOWER_ROMAN: "roman",
            PageNumberFormat.UPPER_ROMAN: "Roman"}
_ALIGN_CMD = {Alignment.LEFT: "\\raggedright", Alignment.CENTER: "\\centering",
              Alignment.RIGHT: "\\raggedleft", Alignment.JUSTIFY: ""}
_ALIGN_CAPTION = {Alignment.LEFT: "justification=raggedright,singlelinecheck=false",
                  Alignment.CENTER: "justification=centering",
                  Alignment.RIGHT: "justification=raggedleft,singlelinecheck=false",
                  Alignment.JUSTIFY: "justification=justified"}
_POSITION = {"bottom_left": ("foot", "L"), "bottom_center": ("foot", "C"),
             "bottom_right": ("foot", "R"), "top_left": ("head", "L"),
             "top_center": ("head", "C"), "top_right": ("head", "R")}
_HEADINGS = ((Role.HEADING_1, "chapter"), (Role.HEADING_2, "section"),
             (Role.HEADING_3, "subsection"))
# LaTeX'te karşılığı ayrıca kurulmayan roller: açıklamada "elle" bölümüne düşer.
_HANDLED = {Role.BODY, Role.HEADING_1, Role.HEADING_2, Role.HEADING_3, Role.FIGURE_CAPTION,
            Role.TABLE_CAPTION, Role.BLOCK_QUOTE, Role.REFERENCE_ENTRY, Role.FOOTNOTE,
            Role.FRONT_MATTER}
_ROLE_TR = {Role.BODY: "ana metin", Role.HEADING_1: "1. düzey başlık",
            Role.HEADING_2: "2. düzey başlık", Role.HEADING_3: "3. düzey başlık",
            Role.FIGURE_CAPTION: "şekil yazısı", Role.TABLE_CAPTION: "tablo başlığı",
            Role.BLOCK_QUOTE: "blok alıntı", Role.REFERENCE_ENTRY: "kaynakça",
            Role.FOOTNOTE: "dipnot", Role.FRONT_MATTER: "ön sayfalar"}


@dataclass
class LatexTemplate:
    """Üretilen dosyalar (yol → içerik) ve kural → LaTeX eşlemesi."""

    class_name: str
    files: dict[str, str] = field(default_factory=dict)
    mapping: list[tuple[str, str]] = field(default_factory=list)
    manual: list[tuple[str, str]] = field(default_factory=list)


def _num(x: float) -> str:
    """3.0 → '3', 2.5 → '2.5', 1.25 → '1.25'."""
    return f"{x:.3f}".rstrip("0").rstrip(".")


def _spacing(rule: LineSpacingRule | None, size_pt: float) -> tuple[str, str] | None:
    """Satır aralığı kuralı → (setspace komutu, açıklama)."""
    if rule is None:
        return None
    if rule.multiple is not None:
        m = rule.multiple
        named = {1.0: "\\singlespacing", 1.5: "\\onehalfspacing", 2.0: "\\doublespacing"}
        return named.get(m, f"\\setstretch{{{_num(m)}}}"), f"{_num(m)} satır"
    # Word'deki "tam"/"en az" aralık: LaTeX'te satır yüksekliği yaklaşık 1,2 × punto.
    pt = rule.exact_pt if rule.exact_pt is not None else rule.at_least_pt
    assert pt is not None
    return f"\\setstretch{{{_num(pt / (1.2 * size_pt))}}}", f"{_num(pt)} pt (yaklaşık)"


def _fontsize(size_pt: float) -> str:
    return f"\\fontsize{{{_num(size_pt)}}}{{{_num(round(size_pt * 1.2, 2))}}}\\selectfont"


def _base_class(body_pt: float) -> tuple[str, str, str]:
    """Ana metin puntosu → (temel sınıf, punto seçeneği, not)."""
    if body_pt in (10, 11, 12):
        return "report", f"{int(body_pt)}pt", ""
    ext = (8, 9, 10, 11, 12, 14, 17, 20)
    nearest = min(ext, key=lambda s: abs(s - body_pt))
    note = "" if nearest == body_pt else f" (en yakın desteklenen: {nearest} pt)"
    return "extreport", f"{nearest}pt", note


class _Builder:
    def __init__(self, rules: Ruleset) -> None:
        self.r = rules
        self.t = LatexTemplate(class_name=f"synora-{rules.ruleset}")
        self.body = rules.roles.get(Role.BODY, RoleRules())
        self.body_pt = self.body.size_pt or 12.0
        self.out: list[str] = []

    def map(self, rule_id: str, latex: str) -> None:
        self.t.mapping.append((rule_id, latex))

    def manual(self, rule_id: str, why: str) -> None:
        self.t.manual.append((rule_id, why))

    def emit(self, *lines: str) -> None:
        self.out.extend(lines)

    # --- .cls ------------------------------------------------------------------------------

    def build_class(self) -> str:
        r = self.r
        base, size_opt, size_note = _base_class(self.body_pt)
        self.emit(
            f"% {self.t.class_name}.cls",
            f"% Synora tarafından \"{r.ruleset}\" kural setinin {r.version}. sürümünden üretildi.",
            f"% Kılavuz: {_comment(r.name)}",
            *([f"% Kaynak: {_comment(r.source)}"] if r.source else []),
            "% Bu dosyayı değiştirmeyin: kılavuz değişince Synora'dan yenisini indirin.",
            "% Resmi bir şablon değildir; son onay fakültenizde ya da enstitünüzdedir.",
            "\\NeedsTeXFormat{LaTeX2e}[2022-06-01]",
            f"\\ProvidesClass{{{self.t.class_name}}}[{GENERATOR_DATE} "
            f"v{GENERATOR_VERSION}.{r.version} Synora tez sablonu]",
            f"\\DeclareOption*{{\\PassOptionsToClass{{\\CurrentOption}}{{{base}}}}}",
            "\\ProcessOptions\\relax",
            f"\\LoadClass[{size_opt},oneside,openany]{{{base}}}",
            "",
        )
        self.map("body.size_pt", f"{size_opt} sınıf seçeneği{size_note}")
        self.emit("\\RequirePackage{amsmath}  % newtxmath'ten önce yüklenmeli")
        self._fonts()
        self.emit(
            "% Türkçe: başlık ve dizin adları, heceleme, büyük harfe çevirmede i → İ.",
            "\\RequirePackage[turkish,shorthands=:!]{babel}",
            "\\RequirePackage{etoolbox}",
            "\\RequirePackage{graphicx}",
            "\\RequirePackage{booktabs}",
            "",
        )
        self._page()
        self._body()
        self._headings()
        self._captions()
        self._quote()
        self._bibliography()
        self._footnote()
        self._page_numbers()
        self._front_matter()
        self._manual_roles()
        self.emit(
            "% Dizinlerde tıklanabilir bağlantılar; en sonda yüklenmeli.",
            "\\RequirePackage[hidelinks]{hyperref}",
            "",
            "\\endinput",
        )
        return "\n".join(self.out) + "\n"

    def _fonts(self) -> None:
        allowed = self.r.fonts.allowed
        if not allowed:
            return
        name = allowed[0]
        if not _SAFE_FONT.fullmatch(name):
            self.manual("*.font", f"yazı tipi adı şablona yazılamadı; {name!r} elle ayarlanmalı")
            return
        pdf, fallback = _FONTS.get(name.lower(), ("", ""))
        self.emit("\\RequirePackage{iftex}", "\\ifPDFTeX", "  \\RequirePackage[T1]{fontenc}")
        if pdf:
            self.emit(f"  % {name} ve benzeri", f"  {pdf}")
        else:
            self.emit(f"  % {name} için pdfLaTeX karşılığı yok: XeLaTeX ya da LuaLaTeX "
                      "ile derleyin.")
        self.emit("\\else", "  \\RequirePackage{fontspec}")
        if fallback:
            self.emit(f"  \\IfFontExistsTF{{{name}}}{{\\setmainfont{{{name}}}}}"
                      f"{{\\setmainfont{{{fallback}}}}}")
        else:
            self.emit(f"  \\setmainfont{{{name}}}")
        self.emit("\\fi", "")
        how = f"pdfLaTeX: benzer yazı tipi; XeLaTeX: {name}" if pdf else f"XeLaTeX: {name}"
        self.map("*.font", how)

    def _page(self) -> None:
        p = self.r.page
        opts: list[str] = []
        if p.size:
            opts.append(_PAPER[p.size])
            self.map("page.size", f"geometry: {_PAPER[p.size]}")
        if p.orientation:
            opts.append(p.orientation)
            self.map("page.orientation", f"geometry: {p.orientation}")
        m = p.margins_cm
        if m is not None:
            for side in ("top", "bottom", "left", "right"):
                v = getattr(m, side)
                if v is not None:
                    opts.append(f"{side}={_num(v)}cm")
                    self.map(f"page.margin.{side}", f"geometry: {side}={_num(v)}cm")
        if opts:
            self.emit("% Kâğıt ve kenar boşlukları (sayfa numarası alt boşluğun içinde kalır).",
                      f"\\RequirePackage[{','.join(opts)}]{{geometry}}", "")

    def _body(self) -> None:
        b = self.body
        self.emit("\\RequirePackage{setspace}")
        sp = _spacing(b.spacing_rule(), self.body_pt)
        if sp:
            self.emit(sp[0])
            self.map("body.line_spacing", f"setspace: {sp[0]} ({sp[1]})")
        if b.first_line_indent_cm is not None:
            self.emit(f"\\setlength{{\\parindent}}{{{_num(b.first_line_indent_cm)}cm}}",
                      "% Başlıktan sonraki ilk paragraf da girintili (Word'deki gibi).",
                      "\\RequirePackage{indentfirst}")
            self.map("body.first_line_indent_cm",
                     f"\\parindent={_num(b.first_line_indent_cm)}cm + indentfirst")
        gap = (b.space_before_pt or 0) + (b.space_after_pt or 0)
        if b.space_before_pt is not None or b.space_after_pt is not None:
            self.emit(f"\\setlength{{\\parskip}}{{{_num(gap)}pt}}")
            self.map("body.space_after_pt", f"\\parskip={_num(gap)}pt")
        if b.alignment is not None:
            cmd = _ALIGN_CMD[b.alignment]
            if cmd:
                self.emit(f"\\AtBeginDocument{{{cmd}}}")
            self.map("body.alignment", cmd or "iki yana yaslı (LaTeX varsayılanı)")
        for flag in ("bold", "italic", "all_caps"):
            if getattr(b, flag):
                self.manual(f"body.{flag}", "ana metin için LaTeX'te ayarlanmadı")
        self.emit("")

    def _headings(self) -> None:
        self.emit("% Başlıklar: \\chapter = 1., \\section = 2., \\subsection = 3. düzey.",
                  "\\RequirePackage{titlesec}")
        for role, cmd in _HEADINGS:
            h = self.r.roles.get(role)
            if h is None:
                continue
            rid = role.value
            size = h.size_pt or self.body_pt
            parts = [_fontsize(size)]
            self.map(f"{rid}.size_pt", f"\\{cmd}: {_num(size)} pt")
            if h.bold is False:
                parts.append("\\mdseries")
            else:
                parts.append("\\bfseries")
                if h.bold:
                    self.map(f"{rid}.bold", f"\\{cmd}: \\bfseries")
            if h.italic:
                parts.append("\\itshape")
                self.map(f"{rid}.italic", f"\\{cmd}: \\itshape")
            if h.alignment is not None:
                if _ALIGN_CMD[h.alignment]:
                    parts.append(_ALIGN_CMD[h.alignment])
                self.map(f"{rid}.alignment", f"\\{cmd}: {_ALIGN_CMD[h.alignment] or 'yaslı'}")
            sp = _spacing(h.spacing_rule(), size)
            if sp:
                parts.append(sp[0])
                self.map(f"{rid}.line_spacing", f"\\{cmd}: {sp[0]}")
            label = "\\thechapter." if cmd == "chapter" else f"\\the{cmd}."
            after = "\\MakeUppercase" if h.all_caps else ""
            if h.all_caps:
                self.map(f"{rid}.all_caps", f"\\{cmd}: \\MakeUppercase (Türkçe i → İ)")
            shape = "[block]" if cmd == "chapter" else ""
            self.emit(f"\\titleformat{{\\{cmd}}}{shape}{{{''.join(parts)}}}"
                      f"{{{label}}}{{0.5em}}{{{after}}}")
            before = h.space_before_pt if h.space_before_pt is not None else (
                0 if cmd == "chapter" else 12)
            after_pt = h.space_after_pt if h.space_after_pt is not None else (
                18 if cmd == "chapter" else 6)
            self.emit(f"\\titlespacing*{{\\{cmd}}}{{0pt}}{{{_num(before)}pt}}{{{_num(after_pt)}pt}}")
            if h.space_before_pt is not None:
                self.map(f"{rid}.space_before_pt", f"\\titlespacing: {_num(before)}pt")
            if h.space_after_pt is not None:
                self.map(f"{rid}.space_after_pt", f"\\titlespacing: {_num(after_pt)}pt")
            if cmd == "chapter":
                if h.page_break_before is False:
                    self.emit("\\titleclass{\\chapter}{straight}")
                    self.map(f"{rid}.page_break_before", "\\chapter yeni sayfa açmaz")
                elif h.page_break_before:
                    self.map(f"{rid}.page_break_before", "\\chapter yeni sayfadan başlar")
            elif h.page_break_before:
                self.manual(f"{rid}.page_break_before",
                            f"\\{cmd} öncesine \\clearpage koyun")
            if h.case == "title":
                self.manual(f"{rid}.case", "Her Sözcüğün İlk Harfini Büyük yazın "
                            "(bağlaçlar küçük); LaTeX bunu değiştirmez")
            elif h.case == "sentence":
                self.manual(f"{rid}.case", "yalnızca ilk sözcüğün ilk harfini büyük yazın; "
                            "LaTeX bunu değiştirmez")
            for name in ("first_line_indent_cm", "indent_left_cm", "font"):
                if getattr(h, name) is not None:
                    self.manual(f"{rid}.{name}", "başlıklar için LaTeX'te ayarlanmadı")
        self.emit("")

    def _captions(self) -> None:
        self.emit("\\RequirePackage{caption}",
                  "\\captionsetup{labelsep=period}")
        for role, env in ((Role.FIGURE_CAPTION, "figure"), (Role.TABLE_CAPTION, "table")):
            c = self.r.roles.get(role)
            if c is None:
                continue
            rid = role.value
            opts: list[str] = []
            fonts: list[str] = []
            if c.size_pt is not None:
                font = f"synora{env}"
                self.emit(f"\\DeclareCaptionFont{{{font}}}{{{_fontsize(c.size_pt)}}}")
                fonts.append(font)
                self.map(f"{rid}.size_pt", f"caption: {_num(c.size_pt)} pt")
            if c.bold:
                fonts.append("bf")
                self.map(f"{rid}.bold", "caption: bf")
            if c.italic:
                fonts.append("it")
                self.map(f"{rid}.italic", "caption: it")
            sp = _spacing(c.spacing_rule(), c.size_pt or self.body_pt)
            if sp:
                key = {"\\singlespacing": "singlespacing", "\\onehalfspacing": "onehalfspacing",
                       "\\doublespacing": "doublespacing"}.get(sp[0])
                fonts.append(key or "stretch=" + sp[0].removeprefix("\\setstretch{")[:-1])
                self.map(f"{rid}.line_spacing", f"caption: {sp[1]}")
            if fonts:
                opts.append("font={" + ",".join(fonts) + "}")
            if c.alignment is not None:
                opts.append(_ALIGN_CAPTION[c.alignment])
                self.map(f"{rid}.alignment", f"caption: {_ALIGN_CAPTION[c.alignment]}")
            if c.position is not None:
                opts.append(f"position={c.position}")
                where = "altına" if c.position == "below" else "üstüne"
                self.manual(f"{rid}.position",
                            f"\\caption komutunu {'şeklin' if env == 'figure' else 'tablonun'} "
                            f"{where} yazın (örnek tez.tex'te doğru yerde)")
            if opts:
                self.emit(f"\\captionsetup[{env}]{{{','.join(opts)}}}")
        self.emit("")

    def _env_style(self, rules: RoleRules, rid: str, what: str) -> list[str]:
        """Ortam (alıntı, kaynakça) başında uygulanacak punto/aralık komutları."""
        cmds: list[str] = []
        size = rules.size_pt or self.body_pt
        if rules.size_pt is not None:
            cmds.append(_fontsize(rules.size_pt))
            self.map(f"{rid}.size_pt", f"{what}: {_num(rules.size_pt)} pt")
        sp = _spacing(rules.spacing_rule(), size)
        if sp:
            cmds.append(sp[0])
            self.map(f"{rid}.line_spacing", f"{what}: {sp[0]} ({sp[1]})")
        if rules.italic:
            cmds.append("\\itshape")
            self.map(f"{rid}.italic", f"{what}: \\itshape")
        return cmds

    def _quote(self) -> None:
        q = self.r.roles.get(Role.BLOCK_QUOTE)
        if q is None:
            return
        cmds = self._env_style(q, "block_quote", "quote")
        left = f"{_num(q.indent_left_cm)}cm" if q.indent_left_cm is not None else "\\leftmargini"
        if q.indent_left_cm is not None:
            self.map("block_quote.indent_left_cm", f"quote: sol girinti {left}")
        if q.alignment is not None:
            if _ALIGN_CMD[q.alignment]:
                cmds.append(_ALIGN_CMD[q.alignment])
            self.map("block_quote.alignment", f"quote: {_ALIGN_CMD[q.alignment] or 'yaslı'}")
        self.emit("% Blok alıntı: \\begin{quote} … \\end{quote}",
                  "\\renewenvironment{quote}"
                  f"{{\\list{{}}{{\\leftmargin={left}\\rightmargin=0pt}}\\item\\relax"
                  f"{''.join(cmds)}}}{{\\endlist}}", "")

    def _bibliography(self) -> None:
        ref = self.r.roles.get(Role.REFERENCE_ENTRY)
        if ref is None:
            return
        cmds = self._env_style(ref, "reference_entry", "kaynakça")
        if ref.space_after_pt is not None:
            cmds.append(f"\\setlength{{\\itemsep}}{{{_num(ref.space_after_pt)}pt}}")
            self.map("reference_entry.space_after_pt",
                     f"kaynakça: girdiler arası {_num(ref.space_after_pt)}pt")
        if ref.first_line_indent_cm is not None:
            self.manual("reference_entry.first_line_indent_cm",
                        "numaralı kaynakçada girinti etiket genişliğinden gelir")
        if cmds:
            self.emit("% Kaynakça (\\bibliography ya da thebibliography)",
                      f"\\apptocmd{{\\thebibliography}}{{{''.join(cmds)}}}{{}}{{}}", "")

    def _footnote(self) -> None:
        fn = self.r.roles.get(Role.FOOTNOTE)
        if fn is None:
            return
        if fn.size_pt is not None:
            self.emit("% Dipnot puntosu (\\footnotesize başka yerde de bu boyutu verir)",
                      f"\\renewcommand{{\\footnotesize}}{{{_fontsize(fn.size_pt)}}}")
            self.map("footnote.size_pt", f"\\footnotesize: {_num(fn.size_pt)} pt")
        sp = _spacing(fn.spacing_rule(), fn.size_pt or self.body_pt)
        if sp:
            if sp[0] == "\\singlespacing":
                self.emit("% Dipnotlar tek satır aralıklı (setspace varsayılanı)")
            else:
                self.emit("\\RequirePackage{footmisc}",
                          f"\\renewcommand{{\\footnotelayout}}{{{sp[0]}}}")
            self.map("footnote.line_spacing", f"dipnot: {sp[1]}")
        self.emit("")

    def _page_numbers(self) -> None:
        pn = self.r.page_numbering
        fmts = [_PAGENUM[f] for f in pn.formats_in_order] or ["arabic"]
        front, main = fmts[0], fmts[-1]
        self.emit(
            "% Sayfa numarası biçimleri. Kullanım: kapaktan önce \\onsayfalar,",
            "% ilk bölümden (ör. Giriş) önce \\anametin.",
            f"\\newcommand{{\\onsayfalar}}{{\\clearpage\\pagenumbering{{{front}}}}}",
            f"\\newcommand{{\\anametin}}{{\\clearpage\\pagenumbering{{{main}}}}}",
        )
        if pn.formats_in_order:
            self.map("page_numbering.formats", f"\\onsayfalar: {front}, \\anametin: {main}")
        if len(fmts) > 2:
            self.manual("page_numbering.formats",
                        "ikiden fazla numara biçimi: ara biçimler için \\pagenumbering kullanın")
        if pn.position is not None:
            where, side = _POSITION[pn.position]
            fill = f"\\fancy{where}[{side}]{{\\thepage}}"
            self.emit(
                "\\RequirePackage{fancyhdr}",
                "\\fancypagestyle{plain}{\\fancyhf{}\\renewcommand{\\headrulewidth}{0pt}"
                f"{fill}}}",
                "\\pagestyle{plain}",
            )
            self.map("page_numbering.position", fill)
        if pn.forbid_decoration:
            self.map("page_numbering.decoration", "yalnızca \\thepage (parantez, tire yok)")
        self.emit("")

    def _front_matter(self) -> None:
        self.emit(
            "% Ön sayfa başlıkları (Özet, Önsöz…): numarasız, içindekilere eklenir.",
            "\\newcommand{\\onbolum}[1]{\\chapter*{#1}\\addcontentsline{toc}{chapter}{#1}}",
            "",
        )
        fm = self.r.roles.get(Role.FRONT_MATTER)
        if fm is None:
            return
        if fm.size_pt is not None:
            if fm.size_pt == self.body_pt:
                self.map("front_matter.size_pt", f"ana metinle aynı ({_num(fm.size_pt)} pt)")
            else:
                self.manual("front_matter.size_pt",
                            f"ön sayfalarda {_num(fm.size_pt)} pt için \\fontsize kullanın")

    def _manual_roles(self) -> None:
        for role, rules in self.r.roles.items():
            if role in _HANDLED:
                continue
            for name, value in rules:
                if value is not None:
                    self.manual(f"{role.value}.{name}", "bu rol için LaTeX ayarı üretilmedi")

    # --- Örnek tez, kaynakça, açıklama ------------------------------------------------------

    def build_sample(self) -> str:
        fig = self.r.roles.get(Role.FIGURE_CAPTION)
        tab = self.r.roles.get(Role.TABLE_CAPTION)
        fig_above = fig is not None and fig.position == "above"
        tab_below = tab is not None and tab.position == "below"
        fig_caption = ("  \\caption{Örnek şekil yazısı. Kaynak varsa burada belirtilir.}\n"
                       "  \\label{sek:ornek}\n")
        fig_box = "  \\fbox{\\parbox[c][3cm][c]{.6\\linewidth}{\\centering Şekil alanı}}\n"
        tab_caption = "  \\caption{Örnek tablo başlığı}\n  \\label{tab:ornek}\n"
        tab_body = (
            "  \\begin{tabular}{lrr}\n    \\toprule\n"
            "    Grup & n & Ortalama \\\\\n    \\midrule\n"
            "    Kontrol & 20 & 4,2 \\\\\n    Deney & 22 & 5,1 \\\\\n"
            "    \\bottomrule\n  \\end{tabular}\n"
        )
        figure = ("\\begin{figure}[htbp]\n  \\centering\n"
                  + (fig_caption + fig_box if fig_above else fig_box + fig_caption)
                  + "\\end{figure}\n")
        table = ("\\begin{table}[htbp]\n  \\centering\n"
                 + (tab_body + tab_caption if tab_below else tab_caption + tab_body)
                 + "\\end{table}\n")
        return SAMPLE.format(cls=self.t.class_name, name=_comment(self.r.name),
                             figure=figure, table=table)

    def build_readme(self) -> str:
        r = self.r
        lines = [
            f"# {r.name} · LaTeX şablonu",
            "",
            f"Synora, \"{r.ruleset}\" kural setinin {r.version}. sürümünden üretti."
            + (f" Kaynak: {r.source}." if r.source else ""),
            "",
            "**Resmi bir şablon değildir.** Biçim kuralları Synora'nın .docx denetiminde",
            "kullandığı kural setinden alınmıştır. Son onay fakültenizde ya da enstitünüzdedir.",
            "",
            "## Overleaf'te kullanım",
            "",
            "1. Overleaf'te *New Project › Upload Project* ile bu .zip dosyasını yükleyin.",
            "2. `tez.tex` dosyasını açın ve *Recompile* düğmesine basın.",
            "3. Derleyici varsayılan olarak pdfLaTeX'tir. Gerçek Times New Roman isterseniz",
            "   *Menu › Compiler › XeLaTeX* seçin (yazı tipi yoksa TeX Gyre Termes kullanılır).",
            "",
            "Kendi bilgisayarınızda: `latexmk -pdf tez.tex` (TeX Live 2022 ya da daha yeni).",
            "",
            "## Dosyalar",
            "",
            f"- `{self.t.class_name}.cls`: belge sınıfı. Biçim ayarları burada; değiştirmeyin.",
            "- `tez.tex`: örnek tez iskeleti. Kendi metninizle doldurun.",
            "- `kaynaklar.bib`: örnek kaynakça girdileri.",
            "",
            "## Şablonun ayarladığı kurallar",
            "",
            "| Kural | LaTeX karşılığı |",
            "|---|---|",
            *(f"| `{rid}` | {_md(latex)} |" for rid, latex in self.t.mapping),
            "",
        ]
        if self.t.manual:
            lines += [
                "## Sizin uymanız gerekenler",
                "",
                "LaTeX bu kuralları kendiliğinden uygulamaz:",
                "",
                *(f"- `{rid}`: {_md(why)}" for rid, why in self.t.manual),
                "",
            ]
        lines += [
            "## Komutlar",
            "",
            "- `\\onsayfalar`: kapaktan önce; ön sayfaların numara biçimini başlatır.",
            "- `\\anametin`: ilk bölümden önce; numarayı 1'den başlatır.",
            "- `\\onbolum{Özet}`: numarasız ön sayfa başlığı, içindekilere eklenir.",
            "- `\\chapter`, `\\section`, `\\subsection`: 1., 2. ve 3. düzey başlıklar.",
            "",
        ]
        return "\n".join(lines)


def _comment(text: str) -> str:
    """Tek satırlık yorum: satır sonları atılır (yorumdan taşmasın)."""
    return " ".join(text.split())


def _md(text: str) -> str:
    return text.replace("|", "\\|")


SAMPLE = r"""% tez.tex — Synora örnek tez iskeleti ({name})
% Biçim ayarları {cls}.cls içinde. Bu dosyada yalnızca içerik var.
\documentclass{{{cls}}}

\begin{{document}}

\onsayfalar
% --- Kapak: kılavuzunuzdaki kapak düzenine göre doldurun ---
\begin{{center}}
  \thispagestyle{{empty}}
  \textbf{{ÜNİVERSİTE ADI}}\\
  \textbf{{FAKÜLTE / ENSTİTÜ ADI}}\\[5cm]
  {{\large\textbf{{TEZ BAŞLIĞI}}}}\\[3cm]
  Ad SOYAD\\[1cm]
  Danışman: Unvan Ad SOYAD\\
  \vfill
  ŞEHİR, YIL
\end{{center}}
\clearpage

\onbolum{{Özet}}
Türkçe özet metni buraya yazılır.

\onbolum{{Abstract}}
English abstract goes here.

\tableofcontents
\listoftables
\listoffigures

\anametin
\chapter{{Giriş}}
Ana metin paragrafı. Paragraf başı girintisi, satır aralığı ve iki yana yaslama sınıf dosyasından
gelir; bunları burada ayarlamayın.\footnote{{Dipnot örneği.}}

İkinci paragraf. Kaynaklara metinde geçiş sırasıyla atıf yapılır \cite{{ornek2020,ornek2021}}.

\section{{İkinci Düzey Başlık Örneği}}
Şekillere ve tablolara metinde atıf yapın: Şekil~\ref{{sek:ornek}} ve Tablo~\ref{{tab:ornek}}.

{figure}
{table}
\subsection{{Üçüncü düzey başlık örneği}}
\begin{{quote}}
Uzun alıntılar quote ortamında yazılır.
\end{{quote}}

\chapter{{Gereç ve Yöntem}}
Metin.

\cleardoublepage
\phantomsection
\addcontentsline{{toc}}{{chapter}}{{\bibname}}
% Numaralı, metindeki geçiş sırasıyla.
% Kılavuzunuz Vancouver istiyorsa: \bibliographystyle{{vancouver}}
\bibliographystyle{{unsrt}}
\bibliography{{kaynaklar}}

\end{{document}}
"""

BIB = """% Örnek kaynakça girdileri; kendi kaynaklarınızla değiştirin.
@article{ornek2020,
  author  = {Yazar, Ad and İkinci, Yazar},
  title   = {Örnek makale başlığı},
  journal = {Örnek Dergi},
  year    = {2020},
  volume  = {12},
  number  = {3},
  pages   = {45--52}
}

@book{ornek2021,
  author    = {Yazar, Ad},
  title     = {Örnek Kitap},
  publisher = {Yayınevi},
  address   = {Ankara},
  year      = {2021}
}
"""


def build_template(rules: Ruleset) -> LatexTemplate:
    """Kural setinden şablon dosyalarını üretir (.cls, tez.tex, kaynaklar.bib, BENIOKU.md)."""
    b = _Builder(rules)
    cls = b.build_class()
    b.t.files[f"{b.t.class_name}.cls"] = cls
    b.t.files["tez.tex"] = b.build_sample()
    b.t.files["kaynaklar.bib"] = BIB
    b.t.files["BENIOKU.md"] = b.build_readme()
    return b.t


def build_zip(rules: Ruleset) -> bytes:
    """Şablonu .zip olarak verir. Zaman damgası sabit: aynı kural seti → aynı baytlar."""
    template = build_template(rules)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name in sorted(template.files):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, template.files[name].encode("utf-8"))
    return buf.getvalue()
