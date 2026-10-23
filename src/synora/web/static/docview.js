// Payper rapor sayfası: tezin metnini Word'deki gibi gösterir.
// Dosya YALNIZCA bu tarayıcıda açılır: hiçbir yere gönderilmez, saklanmaz; sayfa kapanınca gider.
// Sunucudaki rapor metin taşımaz; bloklar yalnızca gövde paragraf sırasını (data-i) bilir.
// Burada .docx okunur, paragraflar aynı sırayla yürünür (synora.parse ile aynı yürüyüş) ve
// her blok kendi paragraflarıyla doldurulur. Metin DOM'a yalnızca textContent ile girer.
"use strict";

(function () {
  const root = document.getElementById("docview");
  const paper = document.querySelector(".paper");
  if (!root || !paper) return;

  const W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
  const R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
  const MC = "http://schemas.openxmlformats.org/markup-compatibility/2006";
  const A = "http://schemas.openxmlformats.org/drawingml/2006/main";
  const WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing";
  const V = "urn:schemas-microsoft-com:vml";
  const REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/";

  // Sunucudaki A1 sınırlarıyla aynı mertebede: tarayıcıyı zip bombasına karşı korur.
  const MAX_FILE = 110 * 1048576;
  const MAX_ENTRIES = 4000;
  const MAX_RATIO = 100;
  const MAX_PART = 200 * 1048576;
  const MAX_IMAGE = 20 * 1048576;
  const IMAGE_TYPES = { png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", gif: "image/gif",
                        bmp: "image/bmp", webp: "image/webp" };

  const status = document.getElementById("docview-status");
  const openBtn = document.getElementById("docview-open");
  const picker = document.getElementById("docview-file");
  const say = (msg, isError) => {
    status.textContent = msg;
    status.classList.toggle("error", Boolean(isError));
  };
  class ViewError extends Error {}
  const fail = (msg) => { throw new ViewError(msg); };
  const UNREADABLE = "Dosya bu tarayıcıda açılamadı. Rapor ve bulgular yine geçerli; Word'de açıp kontrol edebilirsiniz.";

  // --- Zip -----------------------------------------------------------------------------------
  function readZip(buf) {
    const dv = new DataView(buf);
    const len = buf.byteLength;
    let eocd = -1;
    for (let o = len - 22; o >= Math.max(0, len - 65557); o--) {
      if (dv.getUint32(o, true) === 0x06054b50) { eocd = o; break; }
    }
    if (eocd < 0) fail(UNREADABLE);
    const count = dv.getUint16(eocd + 10, true);
    let off = dv.getUint32(eocd + 16, true);
    if (count > MAX_ENTRIES || off === 0xffffffff) fail(UNREADABLE);
    const names = new TextDecoder("utf-8");
    const entries = new Map();
    for (let k = 0; k < count; k++) {
      if (off + 46 > len || dv.getUint32(off, true) !== 0x02014b50) fail(UNREADABLE);
      const nlen = dv.getUint16(off + 28, true);
      const entry = {
        flags: dv.getUint16(off + 8, true),
        method: dv.getUint16(off + 10, true),
        comp: dv.getUint32(off + 20, true),
        size: dv.getUint32(off + 24, true),
        local: dv.getUint32(off + 42, true),
      };
      entries.set(names.decode(new Uint8Array(buf, off + 46, Math.min(nlen, len - off - 46))), entry);
      off += 46 + nlen + dv.getUint16(off + 30, true) + dv.getUint16(off + 32, true);
    }
    return { buf, dv, entries };
  }

  async function readEntry(zip, name, cap) {
    const e = zip.entries.get(name);
    if (!e) return null;
    const { buf, dv } = zip;
    if (e.flags & 1) fail("Dosya parolalı; Word'de parolasını kaldırıp yeniden deneyin.");
    if (e.local + 30 > buf.byteLength || dv.getUint32(e.local, true) !== 0x04034b50) fail(UNREADABLE);
    const start = e.local + 30 + dv.getUint16(e.local + 26, true) + dv.getUint16(e.local + 28, true);
    if (start + e.comp > buf.byteLength) fail(UNREADABLE);
    const raw = new Uint8Array(buf, start, e.comp);
    if (e.method === 0) return raw.length > cap ? fail(UNREADABLE) : raw;
    if (e.method !== 8) fail(UNREADABLE);
    const limit = Math.min(cap, Math.max(e.comp * MAX_RATIO, 1048576));
    const reader = new Blob([raw]).stream().pipeThrough(new DecompressionStream("deflate-raw")).getReader();
    const chunks = [];
    let total = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.length;
      if (total > limit) { reader.cancel(); fail(UNREADABLE); }
      chunks.push(value);
    }
    const out = new Uint8Array(total);
    let at = 0;
    chunks.forEach((c) => { out.set(c, at); at += c.length; });
    return out;
  }

  // --- XML -----------------------------------------------------------------------------------
  function parseXml(bytes) {
    const utf16 = bytes.length > 1 && bytes[0] === 0xff && bytes[1] === 0xfe;
    const text = new TextDecoder(utf16 ? "utf-16le" : "utf-8").decode(bytes);
    if (text.includes("<!DOCTYPE")) fail(UNREADABLE); // docx'te DTD olmaz; varlık genişletmesi yok
    const doc = new DOMParser().parseFromString(text, "application/xml");
    if (doc.getElementsByTagName("parsererror").length) fail(UNREADABLE);
    return doc;
  }
  const isW = (el, local) => el.namespaceURI === W && el.localName === local;
  const kid = (el, local) => {
    if (!el) return null;
    for (const c of el.children) if (isW(c, local)) return c;
    return null;
  };
  const kids = (el, local) => (el ? [...el.children].filter((c) => isW(c, local)) : []);
  const attr = (el, name) => (el ? el.getAttributeNS(W, name) || null : null);
  const val = (el) => attr(el, "val");
  const num = (v) => { const n = Number.parseFloat(v); return Number.isFinite(n) ? n : undefined; };
  const on = (el) => {
    if (!el) return undefined;
    const v = val(el);
    return !(v === "0" || v === "false" || v === "off" || v === "none");
  };
  const clean = (o) => { Object.keys(o).forEach((k) => o[k] === undefined && delete o[k]); return o; };

  function dirOf(path) { const i = path.lastIndexOf("/"); return i < 0 ? "" : path.slice(0, i + 1); }
  function resolve(base, target) {
    const parts = (target.startsWith("/") ? target.slice(1) : base + target).split("/");
    const out = [];
    parts.forEach((p) => { if (p === "..") out.pop(); else if (p && p !== ".") out.push(p); });
    return out.join("/");
  }
  async function readRels(zip, part) {
    const map = new Map();
    const bytes = await readEntry(zip, dirOf(part) + "_rels/" + part.slice(dirOf(part).length) + ".rels", MAX_PART);
    if (!bytes) return map;
    for (const r of parseXml(bytes).documentElement.children) {
      const target = r.getAttribute("Target") || "";
      map.set(r.getAttribute("Id"), {
        type: r.getAttribute("Type") || "",
        path: r.getAttribute("TargetMode") === "External" ? null : resolve(dirOf(part), target),
      });
    }
    return map;
  }
  const relOfType = (rels, type) => [...rels.values()].find((r) => r.type === REL + type && r.path);

  // --- Biçim özellikleri ---------------------------------------------------------------------
  function readPPr(pPr) {
    if (!pPr) return {};
    const ind = kid(pPr, "ind");
    const sp = kid(pPr, "spacing");
    const numPr = kid(pPr, "numPr");
    return clean({
      jc: val(kid(pPr, "jc")) || undefined,
      left: num(attr(ind, "left") ?? attr(ind, "start")),
      right: num(attr(ind, "right") ?? attr(ind, "end")),
      firstLine: num(attr(ind, "firstLine")),
      hanging: num(attr(ind, "hanging")),
      before: num(attr(sp, "before")),
      after: num(attr(sp, "after")),
      line: num(attr(sp, "line")),
      lineRule: attr(sp, "lineRule") || undefined,
      numId: numPr ? val(kid(numPr, "numId")) ?? undefined : undefined,
      ilvl: numPr ? num(val(kid(numPr, "ilvl"))) : undefined,
    });
  }
  function readRPr(rPr) {
    if (!rPr) return {};
    const fonts = kid(rPr, "rFonts");
    const u = kid(rPr, "u");
    const shd = kid(rPr, "shd");
    const fill = attr(shd, "fill");
    return clean({
      font: attr(fonts, "ascii") || attr(fonts, "hAnsi") || undefined,
      fontTheme: attr(fonts, "asciiTheme") || attr(fonts, "hAnsiTheme") || undefined,
      size: num(val(kid(rPr, "sz"))),
      b: on(kid(rPr, "b")),
      i: on(kid(rPr, "i")),
      u: u ? val(u) !== "none" : undefined,
      strike: on(kid(rPr, "strike")) || on(kid(rPr, "dstrike")),
      caps: on(kid(rPr, "caps")),
      smallCaps: on(kid(rPr, "smallCaps")),
      vanish: on(kid(rPr, "vanish")),
      color: val(kid(rPr, "color")) || undefined,
      highlight: val(kid(rPr, "highlight")) || undefined,
      fill: fill && fill !== "auto" ? fill : undefined,
      vert: val(kid(rPr, "vertAlign")) || undefined,
    });
  }
  function readBorders(el) {
    if (!el) return {};
    const out = {};
    for (const c of el.children) {
      if (c.namespaceURI !== W) continue;
      const v = val(c);
      if (v === "none" || v === "nil") { out[c.localName] = "none"; continue; }
      const px = Math.max(1, Math.round((num(attr(c, "sz")) || 4) / 6));
      const color = /^[0-9A-Fa-f]{6}$/.test(attr(c, "color") || "") ? "#" + attr(c, "color") : "#000";
      const style = v === "double" ? "double" : v === "dotted" ? "dotted" : /dash/.test(v || "") ? "dashed" : "solid";
      out[c.localName] = (style === "double" ? Math.max(3, px) : px) + "px " + style + " " + color;
    }
    if (out.start && !out.left) out.left = out.start;
    if (out.end && !out.right) out.right = out.end;
    return out;
  }

  function loadStyles(sdoc) {
    const byId = new Map();
    let defPara = null;
    let defChar = null;
    let docP = {};
    let docR = {};
    if (sdoc) {
      const defaults = sdoc.getElementsByTagNameNS(W, "docDefaults")[0];
      if (defaults) {
        docP = readPPr(kid(kid(defaults, "pPrDefault"), "pPr"));
        docR = readRPr(kid(kid(defaults, "rPrDefault"), "rPr"));
      }
      for (const s of sdoc.getElementsByTagNameNS(W, "style")) {
        const id = attr(s, "styleId");
        const type = attr(s, "type");
        if (!id) continue;
        const isDefault = ["1", "true", "on"].includes(attr(s, "default") || "");
        if (isDefault && type === "paragraph") defPara = id;
        if (isDefault && type === "character") defChar = id;
        byId.set(id, {
          type, basedOn: val(kid(s, "basedOn")),
          p: readPPr(kid(s, "pPr")), r: readRPr(kid(s, "rPr")),
          borders: readBorders(kid(kid(s, "tblPr"), "tblBorders")),
        });
      }
    }
    const memo = new Map();
    const chain = (id, depth) => {
      const s = id && byId.get(id);
      if (!s || depth > 20) return { p: {}, r: {}, borders: {} };
      const key = id + "|" + depth;
      if (memo.has(key)) return memo.get(key);
      const base = chain(s.basedOn, depth + 1);
      const out = { p: { ...base.p, ...s.p }, r: { ...base.r, ...s.r }, borders: { ...base.borders, ...s.borders } };
      memo.set(key, out);
      return out;
    };
    return {
      defPara, defChar,
      para: (id) => { const c = chain(id || defPara, 0); return { p: { ...docP, ...c.p }, r: { ...docR, ...c.r } }; },
      char: (id) => chain(id || defChar, 0).r,
      table: (id) => chain(id, 0).borders,
      docR,
    };
  }

  function loadTheme(tdoc) {
    const out = {};
    if (!tdoc) return out;
    for (const [key, tag] of [["major", "majorFont"], ["minor", "minorFont"]]) {
      const scheme = tdoc.getElementsByTagNameNS(A, tag)[0];
      const latin = scheme && [...scheme.children].find((c) => c.localName === "latin");
      if (latin) out[key] = latin.getAttribute("typeface");
    }
    return out;
  }

  // --- Numaralandırma ------------------------------------------------------------------------
  function loadNumbering(ndoc) {
    const abstracts = new Map();
    const nums = new Map();
    if (ndoc) {
      for (const an of ndoc.getElementsByTagNameNS(W, "abstractNum")) {
        const lvls = new Map();
        kids(an, "lvl").forEach((l) => lvls.set(num(attr(l, "ilvl")) || 0, {
          fmt: val(kid(l, "numFmt")) || "decimal",
          text: val(kid(l, "lvlText")) ?? "",
          start: num(val(kid(l, "start"))) ?? 1,
        }));
        abstracts.set(attr(an, "abstractNumId"), lvls);
      }
      for (const n of ndoc.getElementsByTagNameNS(W, "num")) {
        const starts = new Map();
        kids(n, "lvlOverride").forEach((o) => {
          const s = num(val(kid(o, "startOverride")));
          if (s !== undefined) starts.set(num(attr(o, "ilvl")) || 0, s);
        });
        nums.set(attr(n, "numId"), { abs: val(kid(n, "abstractNumId")), starts });
      }
    }
    const counters = new Map();
    const roman = (n) => {
      const t = [[1000, "m"], [900, "cm"], [500, "d"], [400, "cd"], [100, "c"], [90, "xc"], [50, "l"],
                 [40, "xl"], [10, "x"], [9, "ix"], [5, "v"], [4, "iv"], [1, "i"]];
      let s = "";
      for (const [v, r] of t) while (n >= v) { s += r; n -= v; }
      return s;
    };
    const letter = (n) => { let s = ""; while (n > 0) { n -= 1; s = String.fromCharCode(97 + (n % 26)) + s; n = Math.floor(n / 26); } return s; };
    const format = (n, fmt) => {
      switch (fmt) {
        case "lowerRoman": return roman(n);
        case "upperRoman": return roman(n).toUpperCase();
        case "lowerLetter": return letter(n);
        case "upperLetter": return letter(n).toUpperCase();
        case "decimalZero": return n < 10 ? "0" + n : String(n);
        default: return String(n);
      }
    };
    const BULLETS = { "\uF0B7": "•", "\uF0A7": "▪", "\uF0D8": "➢", "\uF076": "❖", "\uF0FC": "✓", "\uF0A8": "◦", o: "◦" };
    return function label(numId, ilvl) {
      const n = nums.get(numId);
      const lvls = n && abstracts.get(n.abs);
      const lvl = lvls && lvls.get(ilvl);
      if (!lvl) return null;
      const startOf = (k) => (n.starts.has(k) ? n.starts.get(k) : (lvls.get(k) || { start: 1 }).start);
      const c = counters.get(numId) || new Array(9).fill(null);
      counters.set(numId, c);
      for (let k = 0; k < ilvl; k++) if (c[k] === null) c[k] = startOf(k);
      c[ilvl] = c[ilvl] === null ? startOf(ilvl) : c[ilvl] + 1;
      for (let k = ilvl + 1; k < 9; k++) c[k] = null;
      if (lvl.fmt === "none") return "";
      if (lvl.fmt === "bullet") {
        const ch = lvl.text.charAt(0);
        return BULLETS[ch] || (ch && ch.charCodeAt(0) < 0xf000 ? ch : "•");
      }
      return lvl.text.replace(/%([1-9])/g, (_, d) => {
        const k = Number(d) - 1;
        return format(c[k] ?? startOf(k), (lvls.get(k) || lvl).fmt);
      });
    };
  }

  // --- Görünüm yardımcıları ------------------------------------------------------------------
  const cm = (twips) => (twips / 567).toFixed(2) + "cm";
  const HIGHLIGHT = { yellow: "#FFFF00", green: "#00FF00", cyan: "#00FFFF", magenta: "#FF00FF",
                      blue: "#0000FF", red: "#FF0000", darkBlue: "#000080", darkCyan: "#008080",
                      darkGreen: "#008000", darkMagenta: "#800080", darkRed: "#800000",
                      darkYellow: "#808000", darkGray: "#808080", lightGray: "#C0C0C0", black: "#000000" };
  // Symbol yazı tipindeki sık karakterler (w:sym): ± ≤ ≥ × Yunan harfleri…
  const SYMBOL = { 0xb1: "±", 0xa3: "≤", 0xb3: "≥", 0xb4: "×", 0xb8: "÷", 0xb9: "≠", 0xbb: "≈", 0xb0: "°",
                   0xae: "→", 0xac: "←", 0xd6: "√", 0xa5: "∞", 0xb6: "∂", 0xe5: "∑", 0xb7: "•", 0xa2: "′" };
  const GREEK = "αβχδεφγηιϕκλμνοπθρστυϖωξψζ";
  function symbolChar(code, font) {
    const c = code >= 0xf000 ? code - 0xf000 : code;
    if (/symbol/i.test(font || "") || code >= 0xf000) {
      if (SYMBOL[c]) return SYMBOL[c];
      if (c >= 0x61 && c <= 0x7a) return GREEK[c - 0x61];
      if (c >= 0x41 && c <= 0x5a) return GREEK[c - 0x41].toUpperCase();
      if (code >= 0xf000) return "•";
    }
    return String.fromCodePoint(code);
  }
  const safeFont = (name) => String(name).replace(/["\\<>;{}]/g, "").slice(0, 64);

  // --- Belge → DOM ---------------------------------------------------------------------------
  function render(ctx, body) {
    const items = [];
    walk(body, (start, node) => items.push({ start, node }), ctx);
    return items;
  }

  // synora.parse._StoryWalker.walk ile aynı sıra: paragraf, tablo hücreleri, sdt/customXml, Choice.
  function walk(container, sink, ctx) {
    for (const c of container.children) {
      if (c.namespaceURI === W) {
        if (c.localName === "p") paragraph(c, sink, ctx);
        else if (c.localName === "tbl") { const start = ctx.index; sink(start, table(c, ctx)); }
        else if (c.localName === "sdt" || c.localName === "sdtContent" || c.localName === "customXml") walk(c, sink, ctx);
      } else if (c.namespaceURI === MC && c.localName === "AlternateContent") {
        const choice = [...c.children].find((x) => x.namespaceURI === MC && x.localName === "Choice");
        if (choice) walk(choice, sink, ctx);
      }
    }
  }

  function paragraph(p, sink, ctx) {
    const start = ctx.index;
    const pPr = kid(p, "pPr");
    const style = ctx.styles.para(val(kid(pPr, "pStyle")));
    const props = { ...style.p, ...readPPr(pPr) };
    const mark = { ...style.r, ...readRPr(kid(pPr, "rPr")) };
    const el = document.createElement("p");
    el.className = "wv-p";
    applyPara(el, props, mark, ctx);
    const plain = [];
    if (props.numId && props.numId !== "0") {
      const label = ctx.label(props.numId, props.ilvl || 0);
      if (label) {
        const n = document.createElement("span");
        n.className = "wv-num";
        applyRun(n, mark, ctx);
        n.textContent = label;
        el.append(n, tab());
      }
    }
    runs(p, el, style.r, ctx, false, plain);
    if (!plain.join("").trim() && !el.querySelector("img, .wv-ph")) el.append("\u200b");
    ctx.plain.set(start, plain.join("").replace(/\s+/g, " ").trim());
    ctx.index += 1;
    sink(start, el);
    for (const txbx of textboxes(p)) {
      const box = document.createElement("div");
      box.className = "wv-tbx";
      const boxStart = ctx.index;
      walk(txbx, (_, node) => box.append(node), ctx);
      if (box.childNodes.length) sink(boxStart, box);
    }
  }

  function textboxes(p) {
    const out = [];
    for (const t of p.getElementsByTagNameNS(W, "txbxContent")) {
      let owner = null;
      let fallback = false;
      for (let a = t.parentElement; a; a = a.parentElement) {
        if (a.namespaceURI === MC && a.localName === "Fallback") fallback = true;
        if (isW(a, "p")) { owner = a; break; }
      }
      if (owner === p && !fallback) out.push(t);
    }
    return out;
  }

  function applyPara(el, props, mark, ctx) {
    const s = el.style;
    const jc = props.jc;
    s.textAlign = jc === "both" || jc === "distribute" ? "justify" : jc === "center" ? "center"
      : jc === "right" || jc === "end" ? "right" : "left";
    // Girintiler değişkenle: telefonda (is-reflow) CSS bunları orantılı küçültür.
    if (props.left) s.setProperty("--ml", cm(props.left));
    if (props.right) s.setProperty("--mr", cm(props.right));
    if (props.firstLine) s.textIndent = cm(props.firstLine);
    else if (props.hanging) s.textIndent = cm(-props.hanging);
    if (props.before) s.paddingTop = (props.before / 20) + "pt";
    if (props.after) s.paddingBottom = (props.after / 20) + "pt";
    const size = (mark.size || 20) / 2;
    if (props.lineRule === "exact" && props.line) s.lineHeight = (props.line / 20) + "pt";
    else if (props.lineRule === "atLeast" && props.line) s.lineHeight = Math.max(props.line / 20, size * 1.15) + "pt";
    else s.lineHeight = String(((props.line || 240) / 240) * 1.15);
    s.fontSize = size + "pt";
    const font = fontOf(mark, ctx);
    if (font) s.fontFamily = font;
  }

  function fontOf(props, ctx) {
    let name = props.font;
    if (props.fontTheme) name = ctx.theme[props.fontTheme.startsWith("major") ? "major" : "minor"] || name;
    return name ? '"' + safeFont(name) + '", "Times New Roman", serif' : null;
  }

  function applyRun(el, props, ctx) {
    const s = el.style;
    const font = fontOf(props, ctx);
    if (font) s.fontFamily = font;
    if (props.size) s.fontSize = (props.size / 2) + "pt";
    if (props.b) s.fontWeight = "700";
    if (props.i) s.fontStyle = "italic";
    const deco = [props.u && "underline", props.strike && "line-through"].filter(Boolean).join(" ");
    if (deco) s.textDecoration = deco;
    if (props.caps) s.textTransform = "uppercase";
    else if (props.smallCaps) s.fontVariant = "small-caps";
    if (props.color && /^[0-9A-Fa-f]{6}$/.test(props.color)) s.color = "#" + props.color;
    const bg = HIGHLIGHT[props.highlight] || (props.fill && /^[0-9A-Fa-f]{6}$/.test(props.fill) ? "#" + props.fill : null);
    if (bg) s.backgroundColor = bg;
    if (props.vert === "superscript" || props.vert === "subscript") {
      s.verticalAlign = props.vert === "superscript" ? "super" : "sub";
      s.fontSize = ((props.size || 20) / 2 * 0.66).toFixed(1) + "pt";
    }
  }

  function tab() {
    const t = document.createElement("span");
    t.className = "wv-tab";
    t.textContent = "\t";
    return t;
  }

  // synora.text.iter_runs ile aynı kurallar: silinen metin yok, alan komutu yok, sonuç var.
  function runs(container, out, baseR, ctx, deleted, plain) {
    for (const c of container.children) {
      if (c.namespaceURI === MC && c.localName === "AlternateContent") {
        const choice = [...c.children].find((x) => x.namespaceURI === MC && x.localName === "Choice");
        if (choice) runs(choice, out, baseR, ctx, deleted, plain);
        continue;
      }
      if (c.namespaceURI !== W) continue;
      switch (c.localName) {
        case "r": run(c, deleted ? null : out, baseR, ctx, plain); break;
        case "del": case "moveFrom": runs(c, out, baseR, ctx, true, plain); break;
        case "ins": case "moveTo": runs(c, out, baseR, ctx, deleted, plain); break;
        case "fldSimple":
          ctx.fields.push("result");
          runs(c, out, baseR, ctx, deleted, plain);
          ctx.fields.pop();
          break;
        case "hyperlink": case "smartTag": case "customXml": case "sdtContent": case "bdo": case "dir": case "sdt":
          runs(c, out, baseR, ctx, deleted, plain);
          break;
        default: break;
      }
    }
  }

  function run(r, out, baseR, ctx, plain) {
    const rPr = kid(r, "rPr");
    const props = { ...baseR, ...ctx.styles.char(val(kid(rPr, "rStyle"))), ...readRPr(rPr) };
    let span = null;
    const visible = () => out && !props.vanish && !ctx.fields.includes("instr");
    const emit = (node) => {
      if (!span) { span = document.createElement("span"); applyRun(span, props, ctx); out.append(span); }
      span.append(node);
    };
    // plain, sunucudaki Paragraph.text ile aynı tanımı izler (gizli metin dahil); başlık eşleşmesi için.
    const text = (s) => {
      if (!out || ctx.fields.includes("instr")) return;
      plain.push(s);
      if (!props.vanish) emit(s);
    };
    for (const c of r.children) {
      if (c.namespaceURI === MC && c.localName === "AlternateContent") {
        const choice = [...c.children].find((x) => x.namespaceURI === MC && x.localName === "Choice");
        const pic = choice && [...choice.children].find((x) => isW(x, "drawing"));
        if (pic && visible()) { const node = picture(pic, ctx); if (node) emit(node); }
        continue;
      }
      if (c.namespaceURI !== W) continue;
      switch (c.localName) {
        case "t": text(c.textContent); break;
        case "fldChar": {
          const type = attr(c, "fldCharType");
          if (type === "begin") ctx.fields.push("instr");
          else if (type === "separate" && ctx.fields.length) ctx.fields[ctx.fields.length - 1] = "result";
          else if (type === "end") ctx.fields.pop();
          break;
        }
        case "tab": case "ptab": if (visible()) { emit(tab()); plain.push("\t"); } break;
        case "br": case "cr":
          if (visible()) {
            plain.push("\n");
            if (attr(c, "type") !== "page") emit(document.createElement("br"));
          }
          break;
        case "sym": {
          const code = Number.parseInt(attr(c, "char") || "", 16);
          if (Number.isFinite(code) && code > 0 && code < 0x110000) text(symbolChar(code, attr(c, "font")));
          break;
        }
        case "noBreakHyphen": text("\u2011"); break;
        case "softHyphen": text("\u00AD"); break;
        case "drawing": case "pict": case "object":
          if (visible()) { const node = picture(c, ctx); if (node) emit(node); }
          break;
        case "footnoteReference": case "endnoteReference":
          if (visible()) {
            ctx.notes += 1;
            const sup = document.createElement("sup");
            sup.className = "wv-note";
            sup.textContent = String(ctx.notes);
            emit(sup);
          }
          break;
        default: break;
      }
    }
  }

  function picture(el, ctx) {
    const blip = el.getElementsByTagNameNS(A, "blip")[0];
    const vml = el.getElementsByTagNameNS(V, "imagedata")[0];
    const rid = blip ? blip.getAttributeNS(R, "embed") : vml ? vml.getAttributeNS(R, "id") : null;
    const extent = el.getElementsByTagNameNS(WP, "extent")[0];
    const width = extent ? Number(extent.getAttribute("cx")) / 360000 : 0;
    const height = extent ? Number(extent.getAttribute("cy")) / 360000 : 0;
    const placeholder = (label) => {
      const ph = document.createElement("span");
      ph.className = "wv-ph";
      ph.textContent = label;
      if (width > 0) ph.style.width = Math.min(width, 40).toFixed(2) + "cm";
      if (height > 0) ph.style.height = Math.min(height, 40).toFixed(2) + "cm";
      return ph;
    };
    if (!rid) {
      // Resimsiz çizim: grafik ya da büyük çizim (akış şeması…) yer tutucuyla gösterilir;
      // çizgi, ok, küçük kutu ve metin kutusu çerçeveleri gösterilmez (kutu metni ayrıca yürünür).
      const chart = [...el.getElementsByTagName("*")].some((x) => x.localName === "chart");
      if (chart) return placeholder("Grafik");
      const large = width >= 4 && height >= 2.5;
      return large && !el.getElementsByTagNameNS(W, "txbxContent").length ? placeholder("Çizim") : null;
    }
    const rel = ctx.rels.get(rid);
    const ext = rel && rel.path ? rel.path.split(".").pop().toLowerCase() : "";
    if (!IMAGE_TYPES[ext]) return placeholder(ext ? "Görsel (" + ext.toUpperCase() + ")" : "Görsel");
    const img = document.createElement("img");
    img.className = "wv-img";
    img.alt = "Belgedeki görsel";
    if (width > 0) img.style.width = Math.min(width, 40).toFixed(2) + "cm";
    if (width > 0 && height > 0) img.style.aspectRatio = width + " / " + height;
    ctx.images.push({ img, path: rel.path, type: IMAGE_TYPES[ext] });
    return img;
  }

  function table(tbl, ctx) {
    const tblPr = kid(tbl, "tblPr");
    const borders = { ...ctx.styles.table(val(kid(tblPr, "tblStyle"))), ...readBorders(kid(tblPr, "tblBorders")) };
    const t = document.createElement("table");
    t.className = "wv-table";
    if (val(kid(tblPr, "jc")) === "center") t.classList.add("is-center");
    const body = document.createElement("tbody");
    t.append(body);
    const rows = kids(tbl, "tr");
    const owners = [];
    rows.forEach((tr, ri) => {
      const row = document.createElement("tr");
      body.append(row);
      let col = 0;
      const cells = kids(tr, "tc");
      cells.forEach((tc, ci) => {
        const tcPr = kid(tc, "tcPr");
        const span = Math.max(1, Math.min(64, num(val(kid(tcPr, "gridSpan"))) || 1));
        const vm = kid(tcPr, "vMerge");
        const above = owners[col];
        if (vm && val(vm) !== "restart" && above) {
          above.rowSpan += 1;
          walk(tc, (_, node) => { if (node.textContent.replace(/\u200b/g, "").trim()) above.append(node); }, ctx);
          col += span;
          return;
        }
        const td = document.createElement("td");
        td.colSpan = span;
        const own = readBorders(kid(tcPr, "tcBorders"));
        const last = ci === cells.length - 1;
        const side = (name, fallback) => own[name] || borders[fallback];
        const css = {
          borderTop: side("top", ri === 0 ? "top" : "insideH"),
          borderBottom: side("bottom", ri === rows.length - 1 ? "bottom" : "insideH"),
          borderLeft: side("left", col === 0 ? "left" : "insideV"),
          borderRight: side("right", last ? "right" : "insideV"),
        };
        Object.entries(css).forEach(([k, v]) => { if (v) td.style[k] = v; });
        const fill = attr(kid(tcPr, "shd"), "fill");
        if (fill && /^[0-9A-Fa-f]{6}$/.test(fill)) td.style.backgroundColor = "#" + fill;
        const w = kid(tcPr, "tcW");
        if (w && attr(w, "type") === "dxa" && num(attr(w, "w"))) td.style.width = cm(num(attr(w, "w")));
        walk(tc, (_, node) => td.append(node), ctx);
        row.append(td);
        for (let k = 0; k < span; k++) owners[col + k] = td;
        col += span;
      });
    });
    return t;
  }

  // --- Görselleri görününce yükle (büyük tezde belleği korur) ---------------------------------
  function loadImages(ctx, zip) {
    if (!ctx.images.length) return;
    const byImg = new Map(ctx.images.map((x) => [x.img, x]));
    const load = async (x) => {
      try {
        const bytes = await readEntry(zip, x.path, MAX_IMAGE);
        if (!bytes) return;
        const reader = new FileReader();
        reader.onload = () => { x.img.src = reader.result; };
        reader.readAsDataURL(new Blob([bytes], { type: x.type }));
      } catch (err) {
        x.img.replaceWith(Object.assign(document.createElement("span"), { className: "wv-ph", textContent: "Görsel" }));
      }
    };
    if (!("IntersectionObserver" in window)) { ctx.images.forEach(load); return; }
    const io = new IntersectionObserver((entries) => entries.forEach((e) => {
      if (!e.isIntersecting) return;
      io.unobserve(e.target);
      load(byImg.get(e.target));
    }), { rootMargin: "600px 0px" });
    ctx.images.forEach((x) => io.observe(x.img));
  }

  // --- Sayfa ölçüsü ve ölçekleme -------------------------------------------------------------
  function pageGeometry(body) {
    const sects = body.getElementsByTagNameNS(W, "sectPr");
    const sect = kid(body, "sectPr") || sects[sects.length - 1];
    const pgSz = kid(sect, "pgSz");
    const pgMar = kid(sect, "pgMar");
    const g = (el, name, d) => num(attr(el, name)) || d;
    return { width: g(pgSz, "w", 11906), top: g(pgMar, "top", 1418), bottom: g(pgMar, "bottom", 1418),
             left: g(pgMar, "left", 1418), right: g(pgMar, "right", 1418) };
  }

  function fit(geo) {
    const pane = paper.parentElement;
    const avail = pane.clientWidth - 48;
    const px = (geo.width / 1440) * 96;
    const reflow = avail < 520;
    paper.classList.toggle("is-reflow", reflow);
    if (reflow) {
      paper.style.width = "";
      paper.style.zoom = "";
      return;
    }
    paper.style.width = cm(geo.width);
    paper.style.zoom = avail < px ? (avail / px).toFixed(3) : "";
  }

  // --- Rapor bloklarına yerleştir --------------------------------------------------------------
  function place(items, ctx) {
    const blocks = [...paper.querySelectorAll(".blk[data-i]")];
    const starts = blocks.map((b) => Number(b.dataset.i));
    // Güvenlik ağı: başlık bloklarının metni dosyadakiyle eşleşmeli (yanlış dosya, eski rapor).
    let checked = 0;
    let wrong = 0;
    blocks.forEach((b, k) => {
      const label = b.querySelector(".blk-text");
      if (!label) return;
      checked += 1;
      const want = label.textContent.replace(/\s+/g, " ").trim().replace(/…$/, "");
      if (!(ctx.plain.get(starts[k]) || "").startsWith(want)) wrong += 1;
    });
    if (checked && wrong > Math.max(1, checked * 0.2)) {
      fail("Bu dosya rapordaki belgeyle eşleşmedi. Denetlediğiniz dosyanın kendisini seçin.");
    }
    const buckets = blocks.map(() => []);
    let k = 0;
    items.forEach((item) => {
      while (k + 1 < starts.length && item.start >= starts[k + 1]) k += 1;
      buckets[k].push(item.node);
    });
    blocks.forEach((b, j) => {
      [...b.children].forEach((c) => { if (!c.matches(".pins, .role-pick")) c.remove(); });
      const holder = document.createElement("div");
      holder.className = "wv";
      holder.append(...buckets[j]);
      // Şekil bloğu yalnızca vektör çizim taşıyorsa (gösterilmez) bulgunun bir yeri kalsın.
      if (b.classList.contains("blk-figure") && !holder.textContent.replace(/​/g, "").trim()
          && !holder.querySelector("img, .wv-ph, table")) {
        const ph = document.createElement("span");
        ph.className = "wv-ph";
        ph.textContent = "Çizim";
        holder.append(ph);
      }
      b.append(holder);
      // Düğme rolü içeriği ekran okuyucudan gizler; metin görünürken bölge olarak sunulur.
      if (b.getAttribute("role") === "button") b.setAttribute("role", "group");
    });
  }

  // --- Akış ----------------------------------------------------------------------------------
  let busy = false;
  let shown = false;
  async function open(file, buf) {
    if (busy || shown) return;
    if (typeof DecompressionStream !== "function") {
      say("Tarayıcınız bu özelliği desteklemiyor. Chrome, Edge, Firefox ya da Safari'nin güncel sürümünü kullanın.", true);
      return;
    }
    busy = true;
    if (openBtn) openBtn.disabled = true;
    say("Teziniz bu tarayıcıda açılıyor…");
    try {
      if (!buf) {
        if (!/\.docx$/i.test(file.name)) fail("Yalnızca Word belgesi (.docx) açılabilir. Denetlediğiniz dosyayı seçin.");
        if (file.size > MAX_FILE) fail("Dosya çok büyük. Denetlediğiniz dosyanın kendisini seçin.");
        buf = await file.arrayBuffer();
      }
      if (root.dataset.sha && window.crypto && crypto.subtle) {
        const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", buf));
        const hex = [...digest].map((b) => b.toString(16).padStart(2, "0")).join("");
        if (hex !== root.dataset.sha) {
          fail("Bu dosya, bu raporda denetlenen dosya değil. Denetlediğiniz dosyanın kendisini seçin; "
            + "dosyayı değiştirdiyseniz yeni bir denetim başlatın.");
        }
      }
      const zip = readZip(buf);
      const top = await readRels(zip, "");
      const main = relOfType(top, "officeDocument");
      const mainPath = main ? main.path : "word/document.xml";
      const docBytes = await readEntry(zip, mainPath, MAX_PART);
      if (!docBytes) fail(UNREADABLE);
      const rels = await readRels(zip, mainPath);
      const part = async (type) => {
        const r = relOfType(rels, type);
        const bytes = r ? await readEntry(zip, r.path, MAX_PART) : null;
        return bytes ? parseXml(bytes) : null;
      };
      const doc = parseXml(docBytes);
      const body = doc.getElementsByTagNameNS(W, "body")[0];
      if (!body) fail(UNREADABLE);
      const ctx = {
        styles: loadStyles(await part("styles")),
        theme: loadTheme(await part("theme")),
        label: loadNumbering(await part("numbering")),
        rels, index: 0, fields: [], notes: 0, images: [], plain: new Map(),
      };
      const items = render(ctx, body);
      place(items, ctx);
      const geo = pageGeometry(body);
      paper.style.setProperty("--pl", cm(geo.left));
      paper.style.setProperty("--pr", cm(geo.right));
      paper.style.paddingTop = cm(geo.top);
      paper.style.paddingBottom = cm(geo.bottom);
      paper.style.paddingLeft = cm(geo.left);
      paper.style.paddingRight = cm(geo.right);
      const base = fontOf(ctx.styles.docR, ctx);
      if (base) paper.style.fontFamily = base;
      paper.classList.add("is-real");
      fit(geo);
      let timer = 0;
      window.addEventListener("resize", () => { clearTimeout(timer); timer = setTimeout(() => fit(geo), 120); });
      loadImages(ctx, zip);
      shown = true;
      root.classList.add("is-open");
      const note = document.getElementById("legend-note");
      if (note) {
        note.textContent = root.dataset.sample
          ? "Sentetik örnek tez; bulgular metnin üzerinde işaretli."
          : "Metin yalnızca bu tarayıcıda, kendi dosyanızdan gösteriliyor; sunucuya gönderilmedi.";
      }
      if (openBtn) openBtn.hidden = true;
      say(root.dataset.sample ? "Örnek tez açıldı." : "Teziniz açıldı" + (file ? ": " + file.name : "") + ". Sayfayı kapatınca ekrandan gider.");
      if (file) document.dispatchEvent(new CustomEvent("payper:docfile", { detail: file }));
    } catch (err) {
      say(err instanceof ViewError ? err.message : UNREADABLE, true);
      if (openBtn) openBtn.disabled = false;
    } finally {
      busy = false;
    }
  }

  if (openBtn && picker) {
    openBtn.addEventListener("click", () => { picker.value = ""; picker.click(); });
    picker.addEventListener("change", () => { if (picker.files[0]) open(picker.files[0]); });
    // Kopya için seçilen dosya da (aynı dosya) metni gösterir.
    document.addEventListener("payper:pickfile", (e) => { if (!shown && e.detail) open(e.detail); });
    const canvas = document.querySelector(".pane-canvas");
    if (canvas) {
      const hasFiles = (e) => e.dataTransfer && [...e.dataTransfer.types].includes("Files");
      canvas.addEventListener("dragover", (e) => { if (hasFiles(e) && !shown) { e.preventDefault(); canvas.classList.add("is-drop"); } });
      canvas.addEventListener("dragleave", (e) => { if (!canvas.contains(e.relatedTarget)) canvas.classList.remove("is-drop"); });
      canvas.addEventListener("drop", (e) => {
        if (!hasFiles(e)) return;
        e.preventDefault();
        canvas.classList.remove("is-drop");
        if (e.dataTransfer.files[0]) open(e.dataTransfer.files[0]);
      });
    }
  }

  if (root.dataset.sample) {
    fetch(root.dataset.sample).then((res) => (res.ok ? res.arrayBuffer() : Promise.reject(new Error()))).then(
      (buf) => open(null, buf),
      () => say("Örnek tez yüklenemedi; çizgili görünüm gösteriliyor.", true));
  }
})();
