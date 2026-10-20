"""A2 — Parser: doğrulanmış paket → DocModel.

Tuhaf ya da bozuk biçim değerleri hata değildir; tanımsız (None) sayılır.
Yalnızca ana part bir Word belgesi değilse ParseError fırlatılır.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from synora.errors import ErrorCode, ParseError
from synora.ingest import DocxPackage
from synora.model import (
    DocModel,
    Margins,
    Paragraph,
    ParaProps,
    RunInfo,
    RunProps,
    Section,
    Story,
)
from synora.ooxml import (
    MC_NS,
    R_NS,
    REL_NUMBERING,
    REL_STYLES,
    REL_THEME,
    W14_NS,
    child,
    measure_twips,
    to_int,
    toggle,
    twips_to_cm,
    val,
    w,
    wattr,
)
from synora.package import parse_part, related_part, relationships, story_parts
from synora.styles import Numbering, StyleSheet, ThemeFonts, read_ppr, read_rpr
from synora.text import TRACKED_CHANGE_TAGS, FieldTracker, iter_runs

_PARA_ID_RE = re.compile(r"[0-9A-Fa-f]{1,8}")
_MC_FALLBACK = f"{{{MC_NS}}}Fallback"
_MC_ALT = f"{{{MC_NS}}}AlternateContent"
_MC_CHOICE = f"{{{MC_NS}}}Choice"
_NOTE_SKIP_TYPES = frozenset({"separator", "continuationSeparator", "continuationNotice"})
_BODY_CONTAINERS = frozenset({w("sdt"), w("sdtContent"), w("customXml")})


@dataclass(frozen=True)
class ParaElements:
    """Bir paragrafın XML öğesi ve metin taşıyan run öğeleri (A5 yazıcısı için)."""

    p: Any
    runs: tuple[tuple[Any, RunInfo], ...]


@dataclass(frozen=True)
class ParseResult:
    """DocModel + yazıcının değiştireceği canlı XML ağaçları. Aynı yürüyüşten çıktıkları için
    para_id → öğe eşlemesi DocModel ile birebir tutarlıdır."""

    doc: DocModel
    roots: dict[str, Any]  # part adı → kök öğe (hikâye part'ları + styles)
    paragraphs: dict[str, ParaElements]
    body: Any | None  # w:body
    section_elements: tuple[Any | None, ...]  # bölüm sırasıyla sectPr (son eksikse None)


@dataclass
class _Ctx:
    pkg: DocxPackage
    styles: StyleSheet
    numbering: Numbering
    main_rels: dict[str, str | None]
    paragraphs: list[Paragraph] = field(default_factory=list)
    elements: dict[str, ParaElements] = field(default_factory=dict)
    used_ids: set[str] = field(default_factory=set)
    counter: int = 0


def parse_package(pkg: DocxPackage) -> DocModel:
    return parse_document(pkg).doc


def parse_document(pkg: DocxPackage) -> ParseResult:
    main_root = parse_part(pkg, pkg.main_part)
    if main_root.tag != w("document"):
        raise ParseError(ErrorCode.NOT_WORDML)

    rels = relationships(pkg, pkg.main_part)

    def optional_root(suffix: str) -> Any | None:
        part = related_part(rels, suffix)
        return parse_part(pkg, part) if part else None

    theme = ThemeFonts.from_xml(optional_root(REL_THEME))
    ctx = _Ctx(
        pkg=pkg,
        styles=StyleSheet(optional_root(REL_STYLES), theme),
        numbering=Numbering(optional_root(REL_NUMBERING)),
        main_rels={r.rel_id: r.target_part for r in rels},
    )

    sections: list[Section] = []
    section_elements: list[Any | None] = []
    body_el: Any | None = None
    roots: dict[str, Any] = {}
    tracked = False
    alt_chunks = embedded = 0
    alt_tag, object_tag = w("altChunk"), w("object")
    for story, part in story_parts(pkg):
        root = main_root if part == pkg.main_part else parse_part(pkg, part)
        roots[part] = root
        for el in root.iter():
            tracked = tracked or el.tag in TRACKED_CHANGE_TAGS
            if el.tag == alt_tag:
                alt_chunks += 1  # içine bakılmaz; yalnızca sayılır (mimari §8)
            elif el.tag == object_tag:
                embedded += 1
        walker = _StoryWalker(ctx, story, part)
        if story is Story.BODY:
            body = child(root, "body")
            body_el = body
            if body is not None:
                walker.walk(body)
                final = child(body, "sectPr")
                walker.section_elements.append(final)
            section_elements = list(walker.section_elements)
            sections = [
                _read_section(i, el, ctx.main_rels)
                for i, el in enumerate(walker.section_elements)
            ]
        elif story in (Story.FOOTNOTE, Story.ENDNOTE):
            note_tag = "footnote" if story is Story.FOOTNOTE else "endnote"
            for note in root.iter(w(note_tag)):
                if wattr(note, "type") not in _NOTE_SKIP_TYPES:
                    walker.walk(note)
        else:
            walker.walk(root)

    doc = DocModel(
        sections=tuple(sections),
        paragraphs=tuple(ctx.paragraphs),
        has_tracked_changes=tracked,
        source_sha256=pkg.sha256,
        alt_chunks=alt_chunks,
        embedded_objects=embedded,
    )
    return ParseResult(doc, roots, dict(ctx.elements), body_el, tuple(section_elements))


class _StoryWalker:
    def __init__(self, ctx: _Ctx, story: Story, part: str) -> None:
        self.ctx = ctx
        self.story = story
        self.part = part
        self.tracker = FieldTracker()
        self.index = 0
        self.section_index = 0
        self.section_elements: list[Any | None] = []

    def walk(self, container: Any, *, in_table: bool = False, in_textbox: bool = False) -> None:
        for c in container:
            tag = c.tag
            if not isinstance(tag, str):
                continue
            if tag == w("p"):
                self._paragraph(c, in_table=in_table, in_textbox=in_textbox)
            elif tag == w("tbl"):
                for row in c.iterchildren(w("tr")):
                    for cell in row.iterchildren(w("tc")):
                        self.walk(cell, in_table=True, in_textbox=in_textbox)
            elif tag in _BODY_CONTAINERS:
                self.walk(c, in_table=in_table, in_textbox=in_textbox)
            elif tag == _MC_ALT:
                choice = c.find(_MC_CHOICE)
                if choice is not None:
                    self.walk(choice, in_table=in_table, in_textbox=in_textbox)

    def _paragraph(self, p: Any, *, in_table: bool, in_textbox: bool) -> None:
        ctx = self.ctx
        styles = ctx.styles
        ppr_el = child(p, "pPr")
        style_id = val(ppr_el, "pStyle") or styles.default_paragraph
        style_ppr, style_rpr = styles.paragraph_style(style_id)
        props: ParaProps = styles.doc_ppr.merge(style_ppr).merge(read_ppr(ppr_el))
        base_rpr = styles.doc_rpr.merge(style_rpr)

        runs: list[RunInfo] = []
        run_elements: list[tuple[Any, RunInfo]] = []
        texts: list[str] = []
        kinds: set[str] = set()
        page_break = False
        for rt in iter_runs(p, self.tracker):
            if rt.deleted or not rt.text:
                continue
            rpr_el = child(rt.run, "rPr")
            char_style = val(rpr_el, "rStyle") or styles.default_character
            rprops = base_rpr.merge(styles.character_style(char_style)).merge(
                read_rpr(rpr_el, styles.theme)
            )
            info = RunInfo(rprops, len(rt.text), rt.field_kind, rt.inserted)
            runs.append(info)
            run_elements.append((rt.run, info))
            texts.append(rt.text)
            page_break = page_break or rt.page_break
            if rt.field_kind:
                kinds.add(rt.field_kind)

        if runs:
            dominant = _dominant(runs)
        else:
            dominant = base_rpr.merge(read_rpr(child(ppr_el, "rPr"), styles.theme))

        para_id = self._para_id(p)
        ctx.elements[para_id] = ParaElements(p, tuple(run_elements))
        ctx.paragraphs.append(
            Paragraph(
                para_id=para_id,
                story=self.story,
                part=self.part,
                index=self.index,
                section_index=self.section_index if self.story is Story.BODY else None,
                style_id=style_id,
                style_name=styles.name_of(style_id),
                props=props,
                numbering=ctx.numbering.lookup(props.num_id, props.num_level),
                runs=tuple(runs),
                dominant=dominant,
                in_table=in_table,
                in_textbox=in_textbox,
                has_page_break=page_break,
                has_drawing=_has_drawing(p),
                field_kinds=frozenset(kinds),
                text="".join(texts),
            )
        )
        self.index += 1

        if self.story is Story.BODY and not in_table and not in_textbox:
            sect = child(ppr_el, "sectPr")
            if sect is not None:
                self.section_elements.append(sect)
                self.section_index += 1

        for txbx in self._textboxes(p):
            self.walk(txbx, in_table=in_table, in_textbox=True)

    def _textboxes(self, p: Any) -> list[Any]:
        """Bu paragrafa doğrudan ait metin kutuları (iç içe olanlar ve Fallback hariç)."""
        out = []
        for txbx in p.iter(w("txbxContent")):
            owner = next(txbx.iterancestors(w("p")), None)
            if owner is not p:
                continue
            if any(a.tag == _MC_FALLBACK for a in txbx.iterancestors()):
                continue
            out.append(txbx)
        return out

    def _para_id(self, p: Any) -> str:
        ctx = self.ctx
        raw = p.get(f"{{{W14_NS}}}paraId")
        if isinstance(raw, str) and _PARA_ID_RE.fullmatch(raw) and raw not in ctx.used_ids:
            ctx.used_ids.add(raw)
            return raw
        while True:
            ctx.counter += 1
            candidate = f"p{ctx.counter}"
            if candidate not in ctx.used_ids:
                ctx.used_ids.add(candidate)
                return candidate


_DRAWING_TAGS = (w("drawing"), w("pict"), w("object"))


def _has_drawing(p: Any) -> bool:
    """Paragrafın kendi run'larında resim/çizim var mı (metin kutusu içi hariç)."""
    for el in p.iter(*_DRAWING_TAGS):
        owner = next(el.iterancestors(w("p")), None)
        if owner is p:
            return True
    return False


def _dominant(runs: list[RunInfo]) -> RunProps:
    weights: Counter[RunProps] = Counter()
    for r in runs:
        weights[r.props] += r.length
    return weights.most_common(1)[0][0]


def _read_section(index: int, sect: Any | None, main_rels: dict[str, str | None]) -> Section:
    pg_sz = child(sect, "pgSz")
    pg_mar = child(sect, "pgMar")
    pg_num = child(sect, "pgNumType")

    def size(attr: str) -> float | None:
        return twips_to_cm(measure_twips(wattr(pg_sz, attr))) if pg_sz is not None else None

    def mar(attr: str) -> float | None:
        if pg_mar is None:
            return None
        return twips_to_cm(measure_twips(wattr(pg_mar, attr)))

    def refs(tag: str) -> dict[str, str]:
        out: dict[str, str] = {}
        if sect is None:
            return out
        for ref in sect.iterchildren(w(tag)):
            rid = ref.get(f"{{{R_NS}}}id")
            part = main_rels.get(rid) if isinstance(rid, str) else None
            if part:
                out[wattr(ref, "type") or "default"] = part
        return out

    return Section(
        index=index,
        page_width_cm=size("w"),
        page_height_cm=size("h"),
        landscape=(wattr(pg_sz, "orient") == "landscape") if pg_sz is not None else False,
        margins=Margins(
            top_cm=mar("top"), bottom_cm=mar("bottom"), left_cm=mar("left"),
            right_cm=mar("right"), header_cm=mar("header"), footer_cm=mar("footer"),
            gutter_cm=mar("gutter"),
        ),
        page_number_format=wattr(pg_num, "fmt") if pg_num is not None else None,
        page_number_start=to_int(wattr(pg_num, "start")) if pg_num is not None else None,
        title_page=bool(toggle(sect, "titlePg")) if sect is not None else False,
        headers=refs("headerReference"),
        footers=refs("footerReference"),
    )
