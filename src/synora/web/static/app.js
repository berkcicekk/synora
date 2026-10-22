// Synora arayüzü: yükleme, durum takibi, bulgu süzme. Harici kütüphane yok.
"use strict";

(function () {
  // --- Kılavuz seçimi: aranabilir seçici (combobox) ve seçime göre şablon bağlantıları ------
  const rulesetSelect = document.getElementById("ruleset");
  if (rulesetSelect && rulesetSelect.tagName === "SELECT") {
    const latexLink = document.getElementById("latex-link");
    const latexName = document.getElementById("latex-name");
    const wordLink = document.getElementById("word-link");
    // Türkçe büyük/küçük harf: "Iğdır" → "ığdır", "İzmir" → "izmir".
    const fold = (s) => s.replace(/I/g, "ı").replace(/İ/g, "i").toLocaleLowerCase("tr");
    const groups = Array.from(rulesetSelect.querySelectorAll("optgroup")).map((g) => ({
      label: g.label,
      options: Array.from(g.children).map((o) => ({
        value: o.value, text: o.textContent, inst: g.label, key: fold(o.textContent + " " + g.label),
      })),
    }));
    const total = groups.reduce((n, g) => n + g.options.length, 0);
    const byValue = new Map();
    groups.forEach((g) => g.options.forEach((o) => byValue.set(o.value, o)));

    const syncLatex = () => {
      const opt = byValue.get(rulesetSelect.value);
      if (!opt) return;
      if (latexLink) {
        latexLink.href = "/sablon/" + encodeURIComponent(opt.value) + "/latex.zip";
        latexName.textContent = opt.text;
      }
      if (wordLink) wordLink.href = "/sablon/" + encodeURIComponent(opt.value) + "/sablon.docx";
    };
    rulesetSelect.addEventListener("change", syncLatex);

    // Seçici: select değer taşıyıcı olarak gizli kalır; az seçenekte yalın select yeter.
    const field = document.getElementById("ruleset-field");
    if (field && total > 8) {
      const SVG = "http://www.w3.org/2000/svg";
      const icon = (cls, parts) => {
        const s = document.createElementNS(SVG, "svg");
        s.setAttribute("viewBox", "0 0 24 24");
        s.setAttribute("class", cls);
        s.setAttribute("aria-hidden", "true");
        parts.forEach(([tag, attrs]) => {
          const el = document.createElementNS(SVG, tag);
          Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
          s.appendChild(el);
        });
        return s;
      };
      const el = (tag, cls, text) => {
        const node = document.createElement(tag);
        if (cls) node.className = cls;
        if (text) node.textContent = text;
        return node;
      };

      const btn = el("button", "picker-btn");
      btn.type = "button";
      btn.id = "ruleset-btn";
      btn.setAttribute("aria-haspopup", "listbox");
      btn.setAttribute("aria-expanded", "false");
      const sel = el("span");
      const instEl = el("span", "picker-inst");
      const nameEl = el("span", "picker-name");
      sel.append(instEl, nameEl);
      btn.append(sel, icon("picker-chev", [["path", { d: "M6 9l6 6 6-6" }]]));

      const pop = el("div", "picker-pop");
      pop.hidden = true;
      const searchWrap = el("div", "picker-search-wrap");
      const search = el("input", "picker-search");
      search.type = "text";
      search.autocomplete = "off";
      search.placeholder = "Üniversite ya da kılavuz ara";
      search.setAttribute("role", "combobox");
      search.setAttribute("aria-expanded", "true");
      search.setAttribute("aria-controls", "picker-list");
      search.setAttribute("aria-autocomplete", "list");
      search.setAttribute("aria-label", "Kılavuz listesinde ara");
      searchWrap.append(
        icon("", [["circle", { cx: "11", cy: "11", r: "7" }], ["path", { d: "M21 21l-4.3-4.3" }]]),
        search);
      const list = el("ul", "picker-list");
      list.id = "picker-list";
      list.setAttribute("role", "listbox");
      list.setAttribute("aria-labelledby", "ruleset-label");
      const countBar = el("p", "picker-count");
      countBar.setAttribute("role", "status");
      pop.append(searchWrap, list, countBar);

      rulesetSelect.hidden = true;
      const label = document.getElementById("ruleset-label");
      if (label) label.htmlFor = "ruleset-btn";
      field.append(btn, pop);

      let items = [];      // görünür seçenek li'leri (klavye gezinmesi için)
      let vals = [];       // items ile aynı sırada kural seti kimlikleri
      let active = -1;
      const setActive = (i) => {
        if (active >= 0 && items[active]) items[active].classList.remove("active");
        active = i;
        if (i < 0 || !items[i]) { search.removeAttribute("aria-activedescendant"); return; }
        items[i].classList.add("active");
        search.setAttribute("aria-activedescendant", items[i].id);
        items[i].scrollIntoView({ block: "nearest" });
      };
      const render = (query) => {
        const words = fold(query).split(/\s+/).filter(Boolean);
        list.textContent = "";
        items = [];
        vals = [];
        active = -1;
        search.removeAttribute("aria-activedescendant");
        groups.forEach((g) => {
          const opts = g.options.filter((o) => words.every((w) => o.key.includes(w)));
          if (!opts.length) return;
          list.appendChild(el("li", "picker-group", g.label)).setAttribute("role", "presentation");
          opts.forEach((o) => {
            const li = el("li", "picker-opt", o.text);
            li.id = "po-" + items.length;
            li.setAttribute("role", "option");
            li.setAttribute("aria-selected", String(o.value === rulesetSelect.value));
            li.addEventListener("mouseenter", () => setActive(items.indexOf(li)));
            list.appendChild(li);
            items.push(li);
            vals.push(o.value);
          });
        });
        if (!items.length) list.appendChild(el("li", "picker-empty", "Eşleşen kılavuz yok."));
        countBar.textContent = (words.length ? items.length + " / " : "") + total + " kılavuz";
        return items.length;
      };
      const updateBtn = () => {
        const o = byValue.get(rulesetSelect.value);
        if (!o) return;
        instEl.textContent = o.inst;
        nameEl.textContent = o.text;
      };
      const open = () => {
        search.value = "";
        render("");
        pop.hidden = false;
        btn.setAttribute("aria-expanded", "true");
        setActive(vals.indexOf(rulesetSelect.value));
        search.focus();
      };
      const close = (toBtn) => {
        if (pop.hidden) return;
        pop.hidden = true;
        btn.setAttribute("aria-expanded", "false");
        if (toBtn) btn.focus();
      };
      const choose = (value) => {
        rulesetSelect.value = value;
        rulesetSelect.dispatchEvent(new Event("change"));
        updateBtn();
        close(true);
      };

      btn.addEventListener("click", () => (pop.hidden ? open() : close(true)));
      search.addEventListener("input", () => { render(search.value); if (items.length) setActive(0); });
      search.addEventListener("keydown", (e) => {
        if (e.key === "ArrowDown" || e.key === "ArrowUp") {
          e.preventDefault();
          if (!items.length) return;
          const dir = e.key === "ArrowDown" ? 1 : -1;
          setActive(active < 0 ? (dir > 0 ? 0 : items.length - 1)
                               : (active + dir + items.length) % items.length);
        } else if (e.key === "Enter") {
          e.preventDefault();
          if (active >= 0 && vals[active] !== undefined) choose(vals[active]);
        } else if (e.key === "Escape") {
          e.preventDefault();
          close(true);
        } else if (e.key === "Tab") {
          close(false);
        }
      });
      list.addEventListener("click", (e) => {
        const li = e.target.closest(".picker-opt");
        const i = li ? items.indexOf(li) : -1;
        if (i >= 0) choose(vals[i]);
      });
      document.addEventListener("pointerdown", (e) => {
        if (!pop.hidden && !field.contains(e.target)) close(false);
      });
      updateBtn();
    }
  }

  // --- Yükleme ---------------------------------------------------------------------------
  const form = document.getElementById("upload");
  if (form) {
    const input = document.getElementById("file");
    const drop = document.getElementById("drop");
    const submit = document.getElementById("submit");
    const status = document.getElementById("upload-status");
    const max = Number(form.dataset.max);
    let file = null;

    const say = (msg, isError) => {
      status.textContent = msg;
      status.classList.toggle("error", Boolean(isError));
    };
    const fmtSize = (n) => n < 1048576
      ? Math.max(1, Math.round(n / 1024)) + " KB"
      : (n / 1048576).toFixed(1).replace(/[.,]0$/, "").replace(".", ",") + " MB";

    const choose = (f) => {
      file = null;
      submit.disabled = true;
      drop.classList.remove("has-file");
      if (!f) return;
      if (!/\.docx$/i.test(f.name)) {
        say("Yalnızca Word belgesi (.docx) yükleyebilirsiniz. .doc dosyalarını Word'de .docx olarak kaydedin.", true);
        return;
      }
      if (f.size > max) {
        say("Dosya çok büyük (" + fmtSize(f.size) + "). En fazla " + fmtSize(max) + " yükleyebilirsiniz. "
          + "Word'de bir resme tıklayıp Resim Biçimi › Resimleri Sıkıştır deyin (tüm resimlere uygulanır), "
          + "yeniden kaydedip bu küçük dosyayı yükleyin.", true);
        return;
      }
      file = f;
      submit.disabled = false;
      drop.classList.add("has-file");
      say("Seçilen dosya: " + f.name + " (" + fmtSize(f.size) + ")");
    };

    input.addEventListener("change", () => choose(input.files[0]));
    ["dragenter", "dragover"].forEach((t) =>
      drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach((t) =>
      drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
    drop.addEventListener("drop", (e) => choose(e.dataTransfer.files[0]));

    // fetch yükleme ilerlemesi vermez; büyük dosyalarda öğrenci yüzdeyi görsün diye XHR.
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      if (!file) return;
      submit.disabled = true;
      say("Yükleniyor…");
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/jobs");
      xhr.setRequestHeader("Content-Type", "application/octet-stream");
      xhr.setRequestHeader("X-CSRF-Token", form.dataset.csrf);
      xhr.setRequestHeader("X-Ruleset", document.getElementById("ruleset").value);
      let shown = -1;
      xhr.upload.addEventListener("progress", (ev) => {
        if (!ev.lengthComputable) return;
        const pct = Math.floor((ev.loaded / ev.total) * 100);
        // Ekran okuyucuyu boğmamak için yalnızca 10'luk adımlarda güncelle.
        if (pct >= shown + 10 || pct === 100) {
          shown = pct;
          say(pct < 100 ? "Yükleniyor… %" + pct : "Yüklendi. Denetim başlıyor…");
        }
      });
      xhr.addEventListener("load", () => {
        let data = {};
        try { data = JSON.parse(xhr.responseText); } catch (err) { /* boş ya da JSON olmayan yanıt (ör. vekilin 413 sayfası) */ }
        if (xhr.status < 200 || xhr.status >= 300) {
          // Uygulamaya ulaşamayan istekler (Cloudflare/nginx sınırı) Türkçe JSON dönmez;
          // duruma göre anlaşılır bir mesaj üret.
          const fallback = {
            413: "Dosya çok büyük. En fazla " + fmtSize(max) + " yükleyebilirsiniz. Word'de "
              + "Resim Biçimi › Resimleri Sıkıştır ile resimleri küçültüp yeniden deneyin.",
            429: "Çok fazla istek gönderildi. Birkaç dakika sonra yeniden deneyin.",
            503: "Sunucu şu an yoğun. Bir dakika sonra yeniden deneyin.",
          }[xhr.status];
          say(data.error || fallback
            || "Yükleme başarısız oldu (HTTP " + xhr.status + "). Sayfayı yenileyip yeniden deneyin.", true);
          submit.disabled = false;
          return;
        }
        window.location.href = data.url;
      });
      xhr.addEventListener("error", () => {
        // Vekil, sınırı aşan gövdeyi yanıt vermeden kesebilir: büyük dosyada olası neden boyuttur.
        say(file && file.size > 50 * 1048576
          ? "Bağlantı kesildi. Dosyanız büyük olduğu için ağ katmanında reddedilmiş olabilir; "
            + "Word'de Resim Biçimi › Resimleri Sıkıştır ile küçültüp yeniden deneyin."
          : "Bağlantı hatası. İnternet bağlantınızı kontrol edip yeniden deneyin.", true);
        submit.disabled = false;
      });
      xhr.send(file);
    });
  }

  // --- Durum takibi -------------------------------------------------------------------------
  const poller = document.querySelector("[data-poll]");
  if (poller) {
    const url = poller.dataset.poll;
    const started = Date.now();
    const live = poller.querySelector("[role=status]");
    const stop = (msg) => {
      const bar = poller.querySelector(".progress");
      if (bar) bar.hidden = true;
      if (live) live.textContent = msg;
    };
    const tick = async () => {
      let res;
      try {
        res = await fetch(url, { headers: { Accept: "application/json" } });
      } catch (err) { setTimeout(tick, 2500); return; } // geçici ağ hatası: yeniden dene
      // Oturum düşmüş ya da iş silinmişse yönlendirme HTML döner: sessizce sonsuza dek bekleme.
      if (!res.ok || !(res.headers.get("content-type") || "").includes("application/json")) {
        stop("Durum alınamadı: oturumunuz sona ermiş ya da denetim silinmiş olabilir. Sayfayı yenileyin.");
        return;
      }
      const data = await res.json();
      if (data.status !== "queued" && data.status !== "running") {
        window.location.reload();
        return;
      }
      if (Date.now() - started > 180000) {
        stop("Denetim beklenenden uzun sürüyor. Birkaç dakika sonra sayfayı yenileyin ya da Belgelerim listesine bakın.");
        return;
      }
      setTimeout(tick, 1200);
    };
    setTimeout(tick, 800);
  }

  // --- Bulgu süzme --------------------------------------------------------------------------
  const filters = document.querySelectorAll(".filter");
  filters.forEach((btn) => btn.addEventListener("click", () => {
    filters.forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
    const f = btn.dataset.filter;
    document.querySelectorAll(".card").forEach((card) => {
      const show = f === "all"
        || (f === "fixable" && card.dataset.fixable === "yes")
        || (f === "manual" && card.dataset.fixable === "no")
        || card.dataset.severity === f;
      card.hidden = !show;
    });
    const shown = document.querySelectorAll(".card:not([hidden])").length;
    const empty = document.getElementById("filter-empty");
    if (empty) empty.hidden = shown > 0;
    const pos = document.getElementById("step-pos");
    if (pos) pos.textContent = shown + " yorum";
    // Editör: görünür yorumu olmayan paragrafları soluklaştır.
    const visible = new Set([...document.querySelectorAll(".comment:not([hidden])")].map((c) => c.dataset.card));
    document.querySelectorAll(".blk[data-cards]").forEach((blk) => {
      const cards = blk.dataset.cards.split(" ").filter(Boolean);
      blk.classList.toggle("dim", f !== "all" && cards.length > 0 && !cards.some((n) => visible.has(n)));
    });
  }));

  // Özet kutuları: ilgili süzgeci uygular; "Kontrol edin" ilk belirsiz paragrafa götürür.
  document.querySelectorAll("[data-apply-filter]").forEach((btn) => btn.addEventListener("click", () => {
    const target = document.querySelector('.filter[data-filter="' + btn.dataset.applyFilter + '"]');
    if (target) { target.click(); target.focus(); }
  }));
  const jumpUnsure = document.querySelector("[data-jump-unsure]");
  if (jumpUnsure) jumpUnsure.addEventListener("click", () => {
    const first = document.querySelector(".blk.is-unsure");
    if (!first) return;
    first.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    const sel = first.querySelector("select");
    if (sel) sel.focus({ preventScroll: true });
  });

  // --- Editör: yorum ↔ paragraf ------------------------------------------------------------
  const canvas = document.querySelector(".pane-canvas");
  const commentsPane = document.querySelector(".pane-comments");
  if (canvas && commentsPane) {
    const clearActive = () => document.querySelectorAll(".blk.active, .comment.active")
      .forEach((el) => el.classList.remove("active"));
    const scrollInto = (pane, el) => {
      // Telefonda bölmeler kaydırılmaz (tek sütun); sayfanın kendisi kayar.
      if (pane.scrollHeight <= pane.clientHeight + 1) {
        el.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
        return;
      }
      const top = el.getBoundingClientRect().top - pane.getBoundingClientRect().top + pane.scrollTop - 80;
      pane.scrollTo({ top, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    };
    // Tek sütunda sayfa görünümü yorumların altında kalır; karta dokununca oraya kaydırılmaz.
    const singleColumn = () => matchMedia("(max-width: 760px), (max-height: 500px)").matches;
    const activateCard = (comment, scrollCanvas) => {
      clearActive();
      comment.classList.add("active");
      showPos(comment);
      const blocks = comment.dataset.blocks.split(" ").filter(Boolean)
        .map((i) => document.getElementById("b" + i)).filter(Boolean);
      blocks.forEach((b) => b.classList.add("active"));
      if (scrollCanvas && blocks[0]) scrollInto(canvas, blocks[0]);
    };
    // Önceki/sonraki: yalnızca süzgeçte görünen yorumlar arasında gezilir.
    const stepPos = document.getElementById("step-pos");
    const visibleCards = () => [...document.querySelectorAll(".comment:not([hidden])")];
    const showPos = (comment) => {
      const list = visibleCards();
      if (stepPos) stepPos.textContent = (list.indexOf(comment) + 1) + " / " + list.length;
    };
    const step = (dir) => {
      const list = visibleCards();
      if (!list.length) return;
      const current = list.indexOf(document.querySelector(".comment.active"));
      const next = list[current === -1 ? (dir > 0 ? 0 : list.length - 1)
                                       : (current + dir + list.length) % list.length];
      activateCard(next, true);
      next.focus({ preventScroll: true });
      scrollInto(commentsPane, next);
    };
    document.querySelectorAll("[data-step-card]").forEach((b) =>
      b.addEventListener("click", () => step(Number(b.dataset.stepCard))));
    document.querySelectorAll(".comment").forEach((c) => {
      c.addEventListener("click", (e) => { if (!e.target.closest("summary")) activateCard(c, !singleColumn()); });
      c.addEventListener("keydown", (e) => {
        if (e.target !== c) return; // kart içindeki "Word'de nasıl düzeltilir" vb. kendi tuşlarını kullanır
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activateCard(c, true); }
        else if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); step(e.key === "ArrowDown" ? 1 : -1); }
      });
    });
    document.querySelectorAll(".blk[data-cards]").forEach((blk) => {
      const open = () => {
        const first = blk.dataset.cards.split(" ").filter(Boolean)[0];
        const comment = first && document.getElementById("c" + first);
        if (!comment) return;
        activateCard(comment, false);
        blk.classList.add("active");
        scrollInto(commentsPane, comment);
      };
      if (!blk.dataset.cards) return;
      blk.addEventListener("click", open);
      blk.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
    });
    document.querySelectorAll("[data-jump]").forEach((a) => a.addEventListener("click", (e) => {
      const target = document.getElementById("b" + a.dataset.jump);
      if (!target) return;
      e.preventDefault();
      document.querySelectorAll(".outline a.current").forEach((x) => x.classList.remove("current"));
      a.classList.add("current");
      scrollInto(canvas, target);
    }));
  }

  // --- Tanıtım: parallax ve kaydırınca beliren adımlar -------------------------------------
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const layers = [...document.querySelectorAll(".parallax-layer[data-speed]")];
  if (layers.length && !reduced) {
    // Her katman, kendi (dönüşümsüz) konumunun ekran ortasına uzaklığıyla orantılı kayar;
    // böylece sayfanın derinindeki öğeler de yalnızca birkaç on piksel hareket eder.
    const docTop = (el) => { let y = 0; for (let n = el; n; n = n.offsetParent) y += n.offsetTop; return y; };
    let tops = layers.map((el) => docTop(el) + el.offsetHeight / 2);
    window.addEventListener("resize", () => { tops = layers.map((el) => docTop(el) + el.offsetHeight / 2); });
    let ticking = false;
    const update = () => {
      const mid = window.scrollY + window.innerHeight / 2;
      layers.forEach((el, i) => {
        // İlk ekrandaki katmanlar açılışta yerinde durur (referans: ekran ortası).
        const anchor = Math.max(tops[i], window.innerHeight / 2);
        const shift = Math.max(-80, Math.min(80, (mid - anchor) * Number(el.dataset.speed)));
        el.style.transform = "translate3d(0," + shift.toFixed(1) + "px,0)";
      });
      ticking = false;
    };
    window.addEventListener("scroll", () => { if (!ticking) { ticking = true; requestAnimationFrame(update); } }, { passive: true });
    update();
  }
  // Kahraman metni kaydırdıkça yavaşça yükselir ve solar.
  const heroContent = document.getElementById("hero-content");
  if (heroContent && !reduced) {
    let pending = false;
    const fade = () => {
      const p = Math.min(1, window.scrollY / (window.innerHeight * 0.75));
      heroContent.style.opacity = String(1 - p * 0.9);
      heroContent.style.transform = "translate3d(0," + (p * -60).toFixed(1) + "px,0)";
      pending = false;
    };
    window.addEventListener("scroll", () => { if (!pending) { pending = true; requestAnimationFrame(fade); } }, { passive: true });
    fade();
  }

  // Amblem, kahraman alanında (ve giriş/kayıt panelinde) imlecin yönüne hafifçe döner ve kayar.
  const logo = document.querySelector("#hero-logo .hero-logo-inner, #auth-logo .hero-logo-inner");
  const hero = document.querySelector(".hero, .auth-art");
  if (logo && hero && !reduced && matchMedia("(hover: hover)").matches) {
    hero.addEventListener("mousemove", (e) => {
      const r = logo.getBoundingClientRect();
      const dx = Math.max(-1, Math.min(1, (e.clientX - (r.left + r.width / 2)) / 600));
      const dy = Math.max(-1, Math.min(1, (e.clientY - (r.top + r.height / 2)) / 400));
      logo.style.transform = "translate(" + (dx * 10).toFixed(1) + "px," + (dy * 8).toFixed(1) + "px) rotate(" + (dx * 6).toFixed(1) + "deg)";
    });
    hero.addEventListener("mouseleave", () => { logo.style.transform = ""; });
  }

  // Gizlilik anlatısı: ekranın ortasına gelen adım, yapışkan sahnedeki kareyi seçer.
  const visual = document.getElementById("story-visual");
  const steps = [...document.querySelectorAll(".story-step")];
  if (visual && steps.length && "IntersectionObserver" in window) {
    const show = (step) => {
      steps.forEach((s) => s.classList.toggle("active", s === step));
      visual.className = "story-visual is-" + step.dataset.step;
    };
    const so = new IntersectionObserver((entries) => entries.forEach((en) => {
      if (en.isIntersecting) show(en.target);
    }), { rootMargin: "-45% 0px -45% 0px" });
    steps.forEach((s) => so.observe(s));
  }

  const reveals = document.querySelectorAll(".reveal");
  if (reveals.length && "IntersectionObserver" in window && !reduced) {
    const io = new IntersectionObserver((entries) => entries.forEach((en) => {
      if (en.isIntersecting) { en.target.classList.remove("pending"); io.unobserve(en.target); }
    }), { threshold: 0.2 });
    reveals.forEach((el) => {
      // Ekranın altında kalanlar sonradan belirir; görünenler hemen görünür kalır.
      if (el.getBoundingClientRect().top > window.innerHeight) { el.classList.add("pending"); io.observe(el); }
    });
  }

  // --- Düzeltilmiş / yorumlu kopya --------------------------------------------------------
  const outputs = document.getElementById("outputs");
  if (outputs) {
    const picker = document.getElementById("output-file");
    const status = document.getElementById("output-status");
    const panel = document.getElementById("output-panel");
    const choose = document.getElementById("output-choose");
    const zone = document.getElementById("output-drop");
    let kind = null;
    let opener = null;
    const say = (msg, isError) => {
      status.textContent = msg;
      status.classList.toggle("error", Boolean(isError));
    };
    const openers = [...document.querySelectorAll("[data-output]")];
    openers.forEach((b) => { b.setAttribute("aria-controls", "output-panel"); b.setAttribute("aria-expanded", "false"); });
    // Dosya sunucuda saklanmadığı için önce neden yeniden seçileceğini açıklayan panel açılır;
    // dosya seçici ancak kullanıcı "Dosyayı seç"e bastığında açılır.
    const close = () => {
      panel.hidden = true;
      kind = null;
      openers.forEach((b) => b.setAttribute("aria-expanded", "false"));
      // Klavye kullanıcısı kaldığı yere döner.
      if (opener) { opener.focus(); opener = null; }
    };
    const titles = { fixed: "Düzeltilmiş kopya", annotated: "Yorumlu kopya", recheck: "Yeniden denetim" };
    const helps = {
      copy: "Dosyanızı sunucuda saklamıyoruz. Kopyayı hazırlamak için denetlediğiniz dosyayı yeniden seçin; metninize dokunulmadan hazırlanıp indirilir.",
      recheck: "Dosyanızı sunucuda saklamıyoruz. Seçtiğiniz paragraf türleriyle yeniden denetlemek için denetlediğiniz dosyayı yeniden seçin.",
    };
    openers.forEach((btn) => btn.addEventListener("click", () => {
      kind = btn.dataset.output;
      opener = btn;
      openers.forEach((b) => b.setAttribute("aria-expanded", String(b === btn)));
      document.getElementById("output-title").textContent = titles[kind];
      document.getElementById("output-help").textContent = kind === "recheck" ? helps.recheck : helps.copy;
      say("");
      panel.hidden = false;
      choose.focus();
    }));
    document.getElementById("output-close").addEventListener("click", close);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !panel.hidden) close(); });
    choose.addEventListener("click", () => { picker.value = ""; picker.click(); });
    picker.addEventListener("cancel", () => say("Dosya seçilmedi. Kopya için denetlediğiniz dosyayı seçin."));
    ["dragenter", "dragover"].forEach((t) =>
      zone.addEventListener(t, (e) => { e.preventDefault(); zone.classList.add("over"); }));
    ["dragleave", "drop"].forEach((t) =>
      zone.addEventListener(t, (e) => { e.preventDefault(); zone.classList.remove("over"); }));
    zone.addEventListener("drop", (e) => send(e.dataTransfer.files[0]));
    picker.addEventListener("change", () => send(picker.files[0]));
    // Uygulamaya ulaşamayan ya da genel yanıtlar için duruma göre anlaşılır mesaj.
    const httpFallback = (res, data) => data.error || {
      413: "Dosya çok büyük. Denetlediğiniz dosyanın kendisini seçtiğinizden emin olun.",
      429: "Çok fazla istek gönderildi. Birkaç dakika sonra yeniden deneyin.",
      503: "Sunucu şu an yoğun. Bir dakika sonra yeniden deneyin.",
    }[res.status];
    const send = async (file) => {
      if (!file || !kind) return;
      // Gönderilmeden önce elenebilecek yanlış seçimler: uzantı ve boyut (denetlenen
      // dosya sınırı zaten geçmişti; büyüğü ancak yanlış dosyadır).
      if (!/\.docx$/i.test(file.name)) {
        say("Yalnızca Word belgesi (.docx) seçilebilir. Denetlediğiniz dosyanın kendisini seçin.", true);
        return;
      }
      const maxBytes = Number(outputs.dataset.max || 0);
      if (maxBytes && file.size > maxBytes) {
        say("Dosya çok büyük. Denetlediğiniz dosyanın kendisini seçtiğinizden emin olun.", true);
        return;
      }
      const buttons = [...document.querySelectorAll("[data-output]"), choose];
      buttons.forEach((b) => { b.disabled = true; });
      if (kind === "recheck") {
        say("Yeniden denetleniyor…");
        try {
          const res = await fetch("/jobs/" + outputs.dataset.job + "/recheck", {
            method: "POST",
            headers: { "Content-Type": "application/octet-stream",
                       "X-CSRF-Token": outputs.dataset.csrf },
            body: file,
          });
          const data = await res.json().catch(() => ({}));
          if (res.ok) { window.location.reload(); return; }
          say(httpFallback(res, data) || "Yeniden denetlenemedi. Sayfayı yenileyip yeniden deneyin.", true);
        } catch (err) {
          say("Bağlantı hatası. Yeniden deneyin.", true);
        }
        buttons.forEach((b) => { b.disabled = false; });
        return;
      }
      say("Hazırlanıyor… Metninizin değişmediği doğrulanıyor.");
      try {
        const res = await fetch("/jobs/" + outputs.dataset.job + "/output/" + kind, {
          method: "POST",
          headers: { "Content-Type": "application/octet-stream",
                     "X-CSRF-Token": outputs.dataset.csrf },
          body: file,
        });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          say(httpFallback(res, data) || "Kopya hazırlanamadı. Sayfayı yenileyip yeniden deneyin.", true);
          return;
        }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = kind === "fixed" ? "synora-duzeltilmis.docx" : "synora-yorumlu.docx";
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
        say(kind === "fixed"
          ? "İndirildi. Word'de açıp Gözden Geçir › Tümünü Kabul Et deyin."
          : "İndirildi. Yorumlar Word'ün sağ kenarında görünür.");
      } catch (err) {
        say("Bağlantı hatası. Yeniden deneyin.", true);
      } finally {
        buttons.forEach((b) => { b.disabled = false; });
      }
    };
  }

  // --- Rolü belirsiz paragraflar: öğrencinin tür seçimi ---------------------------------------
  // Yalnızca paragraf kimliği ve rol adı gönderilir; metin sayfada bile yok.
  const rolesBar = document.getElementById("roles-bar");
  if (outputs && rolesBar) {
    const rolesStatus = document.getElementById("roles-status");
    const collect = document.getElementById("collect");
    if (collect) collect.addEventListener("change", () => {
      fetch("/jobs/" + outputs.dataset.job + "/roles", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": outputs.dataset.csrf },
        body: JSON.stringify({ roles: {}, collect: collect.checked }),
      }).catch(() => {});
    });
    document.querySelectorAll("select[data-pid]").forEach((sel) => {
      sel.addEventListener("click", (e) => e.stopPropagation());
      sel.addEventListener("change", async () => {
        rolesStatus.textContent = "Kaydediliyor…";
        rolesStatus.classList.remove("error");
        try {
          const res = await fetch("/jobs/" + outputs.dataset.job + "/roles", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-CSRF-Token": outputs.dataset.csrf },
            body: JSON.stringify({ roles: { [sel.dataset.pid]: sel.value } }),
          });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(data.error || "");
          rolesBar.hidden = !data.changed;
          rolesStatus.textContent = "";
        } catch (err) {
          rolesStatus.textContent = err.message || "Kaydedilemedi. Sayfayı yenileyip yeniden deneyin.";
          rolesStatus.classList.add("error");
        }
      });
    });
  }

  // --- "Bu bulgu yanlış mı?" geri bildirimi (Ö1) ---------------------------------------------
  const fbOutputs = document.getElementById("outputs");
  if (fbOutputs && fbOutputs.dataset.job) {
    document.querySelectorAll("[data-feedback]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          const res = await fetch("/jobs/" + fbOutputs.dataset.job + "/feedback", {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded",
                       "X-CSRF-Token": fbOutputs.dataset.csrf },
            body: new URLSearchParams({ rule_id: btn.dataset.feedback, verdict: "wrong" }),
          });
          btn.textContent = res.ok ? "Teşekkürler, not edildi."
                                   : "Gönderilemedi; sonra yeniden deneyin.";
          if (!res.ok) btn.disabled = false;
        } catch {
          btn.textContent = "Gönderilemedi; sonra yeniden deneyin.";
          btn.disabled = false;
        }
      });
    });
  }

  // --- İstek / Öneri popup'ı -----------------------------------------------------------------
  const suggest = document.getElementById("suggest");
  const suggestDialog = document.getElementById("suggest-dialog");
  if (suggest && suggestDialog && typeof suggestDialog.showModal === "function") {
    const openBtn = document.getElementById("suggest-open");
    const cancelBtn = document.getElementById("suggest-cancel");
    const sform = document.getElementById("suggest-form");
    const sstatus = document.getElementById("suggest-status");
    const smessage = document.getElementById("suggest-message");
    const ssay = (msg, isError) => {
      sstatus.textContent = msg;
      sstatus.classList.toggle("error", Boolean(isError));
    };
    openBtn.hidden = false; // JS yoksa düğme hiç görünmez (dialog JS'siz açılamaz)
    openBtn.addEventListener("click", () => {
      ssay("");
      suggestDialog.showModal();
      smessage.focus();
    });
    cancelBtn.addEventListener("click", () => suggestDialog.close());
    // Karartılmış arka plana tıklanınca kapanır; form kutusu tıklamayı kendi yutar.
    suggestDialog.addEventListener("click", (e) => { if (e.target === suggestDialog) suggestDialog.close(); });
    sform.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!smessage.value.trim()) { ssay("Mesaj boş olamaz.", true); smessage.focus(); return; }
      const sendBtn = sform.querySelector("[type=submit]");
      sendBtn.disabled = true;
      ssay("Gönderiliyor…");
      const body = new URLSearchParams({ message: smessage.value, page: location.pathname });
      const semail = document.getElementById("suggest-email");
      if (semail && semail.value) body.set("email", semail.value);
      const honeypot = sform.querySelector("[name=website]");
      if (honeypot && honeypot.value) body.set("website", honeypot.value);
      const headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Requested-With": "fetch",
      };
      if (suggest.dataset.csrf) headers["X-CSRF-Token"] = suggest.dataset.csrf;
      try {
        const res = await fetch("/oneri", { method: "POST", headers, body });
        if (res.ok) {
          ssay("Teşekkürler! Öneriniz bize ulaştı.");
          sform.reset();
          setTimeout(() => suggestDialog.close(), 1600);
        } else {
          const data = await res.json().catch(() => ({}));
          ssay(data.error || "Gönderilemedi. Birkaç dakika sonra yeniden deneyin.", true);
        }
      } catch (err) {
        ssay("Bağlantı hatası. Yeniden deneyin.", true);
      }
      sendBtn.disabled = false;
    });
  }

  // --- Silme onayı (tarayıcı confirm() yerine sayfa içi) ------------------------------------
  document.querySelectorAll("[data-confirm]").forEach((btn) => {
    const real = btn.parentElement.querySelector("button[type=submit]");
    const cancel = btn.parentElement.querySelector("[data-cancel-delete]");
    btn.addEventListener("click", () => {
      btn.hidden = true;
      real.hidden = false;
      if (cancel) cancel.hidden = false;
      real.focus();
    });
    if (cancel) cancel.addEventListener("click", () => {
      real.hidden = true;
      cancel.hidden = true;
      btn.hidden = false;
      btn.focus();
    });
  });
})();
