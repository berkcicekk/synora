// Synora arayüzü: yükleme, durum takibi, bulgu süzme. Harici kütüphane yok.
"use strict";

(function () {
  // --- Kılavuz seçimi: arama kutusu ve seçime göre LaTeX bağlantısı -------------------------
  const rulesetSelect = document.getElementById("ruleset");
  if (rulesetSelect && rulesetSelect.tagName === "SELECT") {
    const filter = document.getElementById("ruleset-filter");
    const count = document.getElementById("ruleset-count");
    const latexLink = document.getElementById("latex-link");
    const latexName = document.getElementById("latex-name");
    // Türkçe büyük/küçük harf: "Iğdır" → "ığdır", "İzmir" → "izmir".
    const fold = (s) => s.replace(/I/g, "ı").replace(/İ/g, "i").toLocaleLowerCase("tr");
    const groups = Array.from(rulesetSelect.querySelectorAll("optgroup")).map((g) => ({
      label: g.label,
      options: Array.from(g.children).map((o) => ({
        value: o.value, text: o.textContent, key: fold(o.textContent + " " + g.label),
      })),
    }));
    const total = groups.reduce((n, g) => n + g.options.length, 0);

    const syncLatex = () => {
      const opt = rulesetSelect.selectedOptions[0];
      if (!opt || !latexLink) return;
      latexLink.href = "/sablon/" + encodeURIComponent(opt.value) + "/latex.zip";
      latexName.textContent = opt.textContent;
    };

    const show = (words) => {
      const current = rulesetSelect.value;
      rulesetSelect.textContent = "";
      let shown = 0;
      groups.forEach((g) => {
        const opts = g.options.filter((o) => words.every((w) => o.key.includes(w)));
        if (!opts.length) return;
        const og = document.createElement("optgroup");
        og.label = g.label;
        opts.forEach((o) => og.appendChild(new Option(o.text, o.value, false, o.value === current)));
        rulesetSelect.appendChild(og);
        shown += opts.length;
      });
      return shown;
    };

    if (filter && total > 8) {
      filter.hidden = false;
      filter.addEventListener("input", () => {
        const words = fold(filter.value).split(/\s+/).filter(Boolean);
        let shown = show(words);
        if (words.length && !shown) {
          // Seçim hiç boş kalmasın: eşleşme yoksa tüm liste geri gelir.
          shown = show([]);
          count.textContent = "Eşleşen kılavuz yok; tüm liste gösteriliyor.";
        } else {
          count.textContent = words.length ? shown + " kılavuz" : "";
        }
        syncLatex();
      });
      // Arama kutusunda Enter formu göndermesin.
      filter.addEventListener("keydown", (e) => { if (e.key === "Enter") e.preventDefault(); });
    }
    rulesetSelect.addEventListener("change", syncLatex);
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
        say("Dosya çok büyük. En fazla " + Math.round(max / 1048576) + " MB yükleyebilirsiniz.", true);
        return;
      }
      file = f;
      submit.disabled = false;
      drop.classList.add("has-file");
      const size = f.size < 1048576
        ? Math.max(1, Math.round(f.size / 1024)) + " KB"
        : (f.size / 1048576).toFixed(1).replace(".", ",") + " MB";
      say("Seçilen dosya: " + f.name + " (" + size + ")");
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
        try { data = JSON.parse(xhr.responseText); } catch (err) { /* boş yanıt */ }
        if (xhr.status < 200 || xhr.status >= 300) {
          say(data.error || "Yükleme başarısız oldu. Sayfayı yenileyip yeniden deneyin.", true);
          submit.disabled = false;
          return;
        }
        window.location.href = data.url;
      });
      xhr.addEventListener("error", () => {
        say("Bağlantı hatası. İnternet bağlantınızı kontrol edip yeniden deneyin.", true);
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
    const send = async (file) => {
      if (!file || !kind) return;
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
          say(data.error || "Yeniden denetlenemedi. Sayfayı yenileyip yeniden deneyin.", true);
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
          say(data.error || "Kopya hazırlanamadı. Sayfayı yenileyip yeniden deneyin.", true);
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
