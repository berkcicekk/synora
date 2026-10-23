// Synora arayüzü: yükleme, durum takibi, bulgu süzme. Harici kütüphane yok.
"use strict";

(function () {
  // --- CSP: satır içi stil yok; ölçüler data-* özniteliklerinden uygulanır -----------------
  document.querySelectorAll("[data-w]").forEach((el) => { el.style.width = el.dataset.w + "%"; });
  document.querySelectorAll("[data-wpct]").forEach((el) => { el.style.width = el.dataset.wpct + "%"; });
  const inset = document.querySelector("[data-inset]");
  if (inset) {
    const [l, r, t, b] = inset.dataset.inset.split(",");
    inset.style.left = l + "%"; inset.style.right = r + "%";
    inset.style.top = t + "%"; inset.style.bottom = b + "%";
  }

  // --- Alt menü (aynı sayfadaki bölümler): etkin işaret tıklanan bağlantıya taşınır -------
  document.querySelectorAll(".subnav").forEach((nav) => {
    const links = [...nav.querySelectorAll('a[href^="#"]')];
    const first = links.find((a) => a.hasAttribute("aria-current"));
    const token = first ? first.getAttribute("aria-current") : "location";
    const mark = (target) => links.forEach((a) => {
      if (a === target) a.setAttribute("aria-current", token);
      else a.removeAttribute("aria-current");
    });
    links.forEach((a) => a.addEventListener("click", () => mark(a)));
    const fromHash = links.find((a) => a.getAttribute("href") === location.hash);
    if (fromHash) mark(fromHash);
  });

  // --- Kılavuz seçimi: üniversite → kılavuz kademeli listeler + şablon bağlantıları ----
  const rulesetSelect = document.getElementById("ruleset");
  if (rulesetSelect && rulesetSelect.tagName === "SELECT") {
    const latexLink = document.getElementById("latex-link");
    const latexName = document.getElementById("latex-name");
    const wordLink = document.getElementById("word-link");
    const groups = Array.from(rulesetSelect.querySelectorAll("optgroup")).map((g) => ({
      label: g.label,
      options: Array.from(g.children).map((o) => ({ value: o.value, text: o.textContent })),
    }));
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

    // Üniversite listesi: seçilince kılavuz listesi yalnızca o üniversiteye süzülür.
    const uniFld = document.getElementById("uni-fld");
    const uniSel = document.getElementById("u-uni");
    if (uniFld && uniSel && groups.length > 1) {
      uniFld.hidden = false;
      groups.forEach((g, i) => uniSel.add(new Option(
        g.label, String(i), false, g.options.some((o) => o.value === rulesetSelect.value))));
      const applyUni = () => {
        const g = groups[Number(uniSel.value)];
        if (!g) return;
        const current = rulesetSelect.value;
        rulesetSelect.textContent = "";
        g.options.forEach((o) =>
          rulesetSelect.add(new Option(o.text, o.value, false, o.value === current)));
        if (!g.options.some((o) => o.value === rulesetSelect.value)) {
          rulesetSelect.value = g.options[0].value;
        }
        syncLatex();
      };
      uniSel.addEventListener("change", applyUni);
      applyUni();

      // Arama: üniversite ve kılavuz adlarında, Türkçe büyük/küçük harf duyarlı ("Iğdır", "İzmir").
      const search = document.getElementById("uni-search");
      const count = document.getElementById("uni-count");
      if (search) {
        const fold = (s) => s.replace(/I/g, "ı").replace(/İ/g, "i").toLocaleLowerCase("tr");
        const keys = groups.map((g) => fold(g.label + " " + g.options.map((o) => o.text).join(" ")));
        const fill = (indices) => {
          const current = uniSel.value;
          uniSel.textContent = "";
          indices.forEach((i) => uniSel.add(new Option(groups[i].label, String(i), false, String(i) === current)));
          // Seçili üniversite süzgeç dışında kaldıysa ilk eşleşme seçilir; kılavuz listesi izler.
          if (!indices.some((i) => String(i) === current)) uniSel.value = String(indices[0]);
          applyUni();
        };
        const all = groups.map((_, i) => i);
        search.addEventListener("input", () => {
          const words = fold(search.value).split(/\s+/).filter(Boolean);
          const hits = all.filter((i) => words.every((w) => keys[i].includes(w)));
          if (words.length && !hits.length) {
            fill(all);
            count.textContent = "Eşleşen üniversite yok; tüm liste gösteriliyor.";
          } else {
            fill(hits);
            count.textContent = words.length ? hits.length + " üniversite" : "";
          }
        });
        // Arama kutusunda Enter formu (yüklemeyi) göndermesin.
        search.addEventListener("keydown", (e) => { if (e.key === "Enter") e.preventDefault(); });
      }
    }
  }

  // --- Yükleme: ortak yardımcılar (yükleme sayfası ve paneldeki "hazır" kart) ------------
  const fmtSize = (n) => n < 1048576
    ? Math.max(1, Math.round(n / 1024)) + " KB"
    : (n / 1048576).toFixed(1).replace(/[.,]0$/, "").replace(".", ",") + " MB";
  const SHRINK = "Word'de bir resme tıklayıp Resim Biçimi › Resimleri Sıkıştır deyin (tüm resimlere uygulanır), "
    + "yeniden kaydedip bu küçük dosyayı yükleyin.";
  // Gönderilmeden elenebilecek dosyalar; sorun yoksa null.
  const fileProblem = (f, max) => {
    if (!/\.docx$/i.test(f.name)) {
      return "Yalnızca Word belgesi (.docx) yükleyebilirsiniz. .doc dosyalarını Word'de .docx olarak kaydedin.";
    }
    if (f.size > max) {
      return "Dosya çok büyük (" + fmtSize(f.size) + "). En fazla " + fmtSize(max) + " yükleyebilirsiniz. " + SHRINK;
    }
    return null;
  };
  // fetch yükleme ilerlemesi vermez; büyük dosyalarda öğrenci yüzdeyi görsün diye XHR.
  // Başarıda rapor sayfasına gider; hatada say(mesaj, true) ve onFail() çağrılır.
  const uploadFile = (file, ruleset, csrf, max, say, onFail) => {
    say("Yükleniyor…");
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/jobs");
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.setRequestHeader("X-CSRF-Token", csrf);
    xhr.setRequestHeader("X-Ruleset", ruleset);
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
        onFail();
        return;
      }
      window.location.href = data.url;
    });
    xhr.addEventListener("error", () => {
      // Vekil, sınırı aşan gövdeyi yanıt vermeden kesebilir: büyük dosyada olası neden boyuttur.
      say(file.size > 50 * 1048576
        ? "Bağlantı kesildi. Dosyanız büyük olduğu için ağ katmanında reddedilmiş olabilir; "
          + "Word'de Resim Biçimi › Resimleri Sıkıştır ile küçültüp yeniden deneyin."
        : "Bağlantı hatası. İnternet bağlantınızı kontrol edip yeniden deneyin.", true);
      onFail();
    });
    xhr.send(file);
  };
  const sayer = (el) => (msg, isError) => {
    el.textContent = msg;
    el.classList.toggle("error", Boolean(isError));
  };

  // --- Yükleme sayfası ----------------------------------------------------------------------
  const form = document.getElementById("upload");
  if (form) {
    const input = document.getElementById("file");
    const drop = document.getElementById("drop");
    const submit = document.getElementById("submit");
    const say = sayer(document.getElementById("upload-status"));
    const max = Number(form.dataset.max);
    let file = null;

    // Dosya seçimi bırakma alanının başlığını değiştirir; ilk hâli geri koymak için saklanır.
    const dropTitle = document.getElementById("drop-title");
    const dropHelp = document.getElementById("drop-help");
    const dropInitial = [dropTitle && dropTitle.innerHTML, dropHelp && dropHelp.innerHTML];
    const resetDrop = () => {
      if (dropTitle) dropTitle.innerHTML = dropInitial[0];
      if (dropHelp) dropHelp.innerHTML = dropInitial[1];
    };
    const choose = (f) => {
      file = null;
      submit.disabled = true;
      drop.classList.remove("has-file");
      resetDrop();
      if (!f) return;
      const problem = fileProblem(f, max);
      if (problem) { say(problem, true); return; }
      file = f;
      submit.disabled = false;
      drop.classList.add("has-file");
      if (dropTitle) dropTitle.textContent = f.name;
      if (dropHelp) dropHelp.textContent = "Hazır (" + fmtSize(f.size) + ") · denetim yalnızca bellekte çalışır";
      say("Seçilen dosya: " + f.name + " (" + fmtSize(f.size) + ")");
    };

    input.addEventListener("change", () => choose(input.files[0]));
    ["dragenter", "dragover"].forEach((t) =>
      drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach((t) =>
      drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
    drop.addEventListener("drop", (e) => choose(e.dataTransfer.files[0]));

    form.addEventListener("submit", (e) => {
      e.preventDefault();
      if (!file) return;
      submit.disabled = true;
      uploadFile(file, document.getElementById("ruleset").value, form.dataset.csrf, max, say,
        () => { submit.disabled = false; });
    });
  }

  // --- Panel: "hazır" kart (hiç denetim yokken). Bırakılan dosya onaydan sonra yüklenir. -----
  const ready = document.getElementById("ready-card");
  if (ready) {
    const say = sayer(document.getElementById("ready-status"));
    const box = document.getElementById("ready-confirm");
    const hint = document.getElementById("ready-hint");
    const nameEl = document.getElementById("ready-file");
    const start = document.getElementById("ready-start");
    const max = Number(ready.dataset.max);
    let pending = null;
    let depth = 0;  // iç öğeler arasında gezinirken dragleave yanlışlıkla efekti kapatmasın
    const hasFiles = (e) => e.dataTransfer && [...e.dataTransfer.types].includes("Files");
    const setDrag = (on) => ready.classList.toggle("is-drag", on);
    // Kartın dışına bırakılan dosyayı tarayıcı açmasın (sayfadan çıkılırdı).
    ["dragover", "drop"].forEach((t) => window.addEventListener(t, (e) => {
      if (hasFiles(e)) e.preventDefault();
    }));
    ready.addEventListener("dragenter", (e) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth += 1;
      setDrag(true);
    });
    ready.addEventListener("dragover", (e) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
    });
    ready.addEventListener("dragleave", () => {
      depth = Math.max(0, depth - 1);
      if (!depth) setDrag(false);
    });
    ready.addEventListener("drop", (e) => {
      e.preventDefault();
      depth = 0;
      setDrag(false);
      const f = e.dataTransfer.files[0];
      if (!f) return;
      const problem = fileProblem(f, max);
      if (problem) { say(problem, true); return; }
      pending = f;
      nameEl.textContent = f.name + " · " + fmtSize(f.size);
      hint.hidden = true;
      box.hidden = false;
      say("");
      start.focus();
    });
    document.getElementById("ready-cancel").addEventListener("click", () => {
      pending = null;
      box.hidden = true;
      hint.hidden = false;
      say("");
    });
    start.addEventListener("click", () => {
      if (!pending) return;
      start.disabled = true;
      uploadFile(pending, ready.dataset.ruleset, ready.dataset.csrf, max, say,
        () => { start.disabled = false; });
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
        stop("Denetim beklenenden uzun sürüyor. Birkaç dakika sonra sayfayı yenileyin ya da paneldeki son denetimler listesine bakın.");
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
    // Tez metin görünümünde açıldıysa (docview.js, aynı dosya doğrulandı) kopya için yeniden sorulmaz.
    let openFile = null;
    document.addEventListener("payper:docfile", (e) => { openFile = e.detail || null; });
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
      if (openFile) send(openFile);
    }));
    document.getElementById("output-close").addEventListener("click", close);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !panel.hidden) close(); });
    choose.addEventListener("click", () => { picker.value = ""; picker.click(); });
    picker.addEventListener("cancel", () => say("Dosya seçilmedi. Kopya için denetlediğiniz dosyayı seçin."));
    ["dragenter", "dragover"].forEach((t) =>
      zone.addEventListener(t, (e) => { e.preventDefault(); zone.classList.add("over"); }));
    ["dragleave", "drop"].forEach((t) =>
      zone.addEventListener(t, (e) => { e.preventDefault(); zone.classList.remove("over"); }));
    // Kopya için seçilen dosya metin görünümünü de açar (docview.js aynı dosya özetini doğrular).
    const picked = (file) => {
      if (file) document.dispatchEvent(new CustomEvent("payper:pickfile", { detail: file }));
      send(file);
    };
    zone.addEventListener("drop", (e) => picked(e.dataTransfer.files[0]));
    picker.addEventListener("change", () => picked(picker.files[0]));
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
        a.download = kind === "fixed" ? "payper-duzeltilmis.docx" : "payper-yorumlu.docx";
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
