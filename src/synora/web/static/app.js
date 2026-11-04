// Sontez arayüzü: yükleme, durum takibi, bulgu süzme. Harici kütüphane yok.
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

  // --- Seçim kutusu: yerel <select> üzerine aranabilir açılır liste ---------------------------
  // Değer yine yerel select'te durur (form ve JS'siz kullanım); bu yalnızca görünümdür.
  const foldTr = (s) => s.replace(/I/g, "ı").replace(/İ/g, "i").toLocaleLowerCase("tr");
  const SEARCH_FROM = 7; // bundan kısa listede arama kutusu gürültüdür
  let pickerCount = 0;
  const makePicker = (select, { searchLabel, keywords, noun }) => {
    const id = "pick-" + (++pickerCount);
    const make = (tag, className) => {
      const node = document.createElement(tag);
      if (className) node.className = className;
      return node;
    };
    const wrap = make("div", "pick");
    const button = make("button", "pick-btn");
    const value = make("span", "pick-value");
    const pop = make("div", "pick-pop");
    const search = make("input", "pick-search");
    const count = make("p", "pick-count");
    const list = make("ul", "pick-list");
    const empty = make("p", "pick-empty");
    button.type = "button";
    button.id = id;
    button.setAttribute("aria-haspopup", "listbox");
    button.setAttribute("aria-expanded", "false");
    button.append(value);
    pop.hidden = true;
    search.type = "search";
    search.autocomplete = "off";
    search.placeholder = searchLabel;
    search.setAttribute("aria-label", searchLabel);
    search.setAttribute("role", "combobox");
    search.setAttribute("aria-controls", id + "-list");
    search.setAttribute("aria-expanded", "true");
    count.setAttribute("role", "status");
    list.id = id + "-list";
    list.tabIndex = -1;
    list.setAttribute("role", "listbox");
    empty.textContent = "Eşleşen sonuç yok.";
    empty.hidden = true;
    pop.append(search, count, list, empty);
    wrap.append(button, pop);
    select.after(wrap);
    select.classList.add("visually-hidden");
    select.tabIndex = -1;
    select.setAttribute("aria-hidden", "true");
    const label = select.id && document.querySelector('label[for="' + select.id + '"]');
    if (label) {
      label.id = label.id || id + "-label";
      label.htmlFor = id;
      button.setAttribute("aria-labelledby", label.id + " " + id);
      list.setAttribute("aria-labelledby", label.id);
    }

    let visible = [];
    let active = -1;
    const focusTarget = () => (search.hidden ? list : search);
    const setActive = (index) => {
      active = index;
      [...list.children].forEach((li, i) => {
        li.classList.toggle("is-active", i === index);
        if (i === index) li.scrollIntoView({ block: "nearest" });
      });
      const current = list.children[index];
      if (current) focusTarget().setAttribute("aria-activedescendant", current.id);
      else focusTarget().removeAttribute("aria-activedescendant");
    };
    const renderList = () => {
      const words = foldTr(search.value).split(/\s+/).filter(Boolean);
      const options = [...select.options];
      visible = options.filter((o) => {
        const key = foldTr(o.textContent + " " + (keywords ? keywords(o) : ""));
        return words.every((w) => key.includes(w));
      });
      list.textContent = "";
      visible.forEach((o, i) => {
        const li = make("li");
        li.id = id + "-opt-" + i;
        li.textContent = o.textContent;
        li.setAttribute("role", "option");
        li.setAttribute("aria-selected", String(o.value === select.value));
        li.addEventListener("mousemove", () => { if (active !== i) setActive(i); });
        li.addEventListener("click", () => choose(o));
        list.append(li);
      });
      empty.hidden = visible.length > 0;
      list.hidden = !visible.length;
      count.textContent = words.length && noun ? visible.length + " " + noun : "";
      const selected = visible.findIndex((o) => o.value === select.value);
      setActive(words.length ? (visible.length ? 0 : -1) : selected);
    };
    const isOpen = () => !pop.hidden;
    const close = (refocus) => {
      if (!isOpen()) return;
      pop.hidden = true;
      button.setAttribute("aria-expanded", "false");
      if (refocus) button.focus();
    };
    const open = () => {
      if (isOpen()) return;
      search.value = "";
      search.hidden = select.options.length < SEARCH_FROM;
      pop.hidden = false;
      button.setAttribute("aria-expanded", "true");
      const room = window.innerHeight - button.getBoundingClientRect().bottom;
      pop.classList.toggle("up", room < 340 && button.getBoundingClientRect().top > 340);
      renderList();
      focusTarget().focus();
    };
    const choose = (option) => {
      const changed = select.value !== option.value;
      select.value = option.value;
      value.textContent = option.textContent;
      close(true);
      if (changed) select.dispatchEvent(new Event("change", { bubbles: true }));
    };
    button.addEventListener("click", () => (isOpen() ? close(true) : open()));
    button.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); open(); }
    });
    search.addEventListener("input", renderList);
    pop.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" && visible.length) {
        e.preventDefault();
        setActive((active + 1) % visible.length);
      } else if (e.key === "ArrowUp" && visible.length) {
        e.preventDefault();
        setActive((active - 1 + visible.length) % visible.length);
      } else if (e.key === "Enter") {
        e.preventDefault(); // formu (yüklemeyi) göndermesin
        if (visible[active]) choose(visible[active]);
      } else if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation(); // açık bir pencere varsa onu kapatmasın
        close(true);
      } else if (e.key === "Tab") {
        close(false);
      }
    });
    document.addEventListener("pointerdown", (e) => { if (!wrap.contains(e.target)) close(false); });
    const refresh = () => {
      const current = select.options[select.selectedIndex];
      value.textContent = current ? current.textContent : "";
    };
    refresh();
    return { refresh, button };
  };

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
    const rulesetPicker = makePicker(rulesetSelect, { searchLabel: "Kılavuz ara", noun: "kılavuz" });

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
        rulesetPicker.refresh();
      };
      uniSel.addEventListener("change", applyUni);
      applyUni();
      // Arama kılavuz adlarında da çalışır ("Tıp" yazınca o kılavuzu olan üniversiteler).
      makePicker(uniSel, {
        searchLabel: "Üniversite ya da kılavuz ara",
        noun: "üniversite",
        keywords: (o) => groups[Number(o.value)].options.map((g) => g.text).join(" "),
      });
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

  // --- Bilgi pencereleri: düğmeyle açılır, Esc, kapat düğmesi ya da dışarı tıklamayla kapanır ----
  document.querySelectorAll("[data-dialog-open]").forEach((opener) => {
    const dialog = document.getElementById(opener.dataset.dialogOpen);
    if (!dialog) return;
    opener.addEventListener("click", () => dialog.showModal());
    dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); });
    dialog.querySelectorAll("[data-dialog-close]").forEach((b) =>
      b.addEventListener("click", () => dialog.close()));
  });

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
    // Akış: önce tez, sonra kılavuz, sonra başlat. Kılavuz ve şablonlar dosyasız da kullanılabilir.
    const guide = document.getElementById("kilavuz-sec");
    const guideHint = document.getElementById("guide-hint");
    const guideHintInitial = guideHint ? guideHint.textContent : "";
    const leadToGuide = () => {
      if (!guide) return;
      guide.classList.add("is-next");
      if (guideHint) guideHint.textContent = "Tezinizin kılavuzu bu mu? Değilse değiştirin, sonra denetimi başlatın.";
      const stepLinks = document.querySelectorAll(".subnav a[href^=\"#\"]");
      stepLinks.forEach((a) => {
        if (a.getAttribute("href") === "#kilavuz-sec") a.setAttribute("aria-current", "step");
        else a.removeAttribute("aria-current");
      });
      // Kılavuz ve başlatma düğmesi birlikte sığıyorsa ikisi de görünsün; dar ekranda kılavuz öncelikli.
      const span = submit.getBoundingClientRect().bottom - guide.getBoundingClientRect().top;
      if (span < window.innerHeight - 120) submit.scrollIntoView({ block: "end" });
      else guide.scrollIntoView({ block: "center" });
      const first = guide.querySelector(".pick-btn");
      if (first) first.focus({ preventScroll: true });
    };
    const resetFlow = () => {
      if (guide) guide.classList.remove("is-next");
      if (guideHint) guideHint.textContent = guideHintInitial;
      submit.classList.remove("is-next");
    };
    if (guide) guide.addEventListener("change", () => {
      if (!file) return;
      guide.classList.remove("is-next");
      if (guideHint) guideHint.textContent = "Hazır. Denetimi başlatabilirsiniz.";
      submit.classList.add("is-next");
      submit.scrollIntoView({ block: "end" });
      submit.focus({ preventScroll: true });
    });

    const choose = (f) => {
      file = null;
      submit.disabled = true;
      drop.classList.remove("has-file");
      resetDrop();
      resetFlow();
      if (!f) return;
      const problem = fileProblem(f, max);
      if (problem) { say(problem, true); return; }
      file = f;
      submit.disabled = false;
      drop.classList.add("has-file");
      if (dropTitle) dropTitle.textContent = f.name;
      if (dropHelp) dropHelp.textContent = "Hazır (" + fmtSize(f.size) + ") · denetim yalnızca bellekte çalışır";
      say("Seçilen dosya: " + f.name + " (" + fmtSize(f.size) + "). Şimdi kılavuzu kontrol edin.");
      leadToGuide();
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
      // Takip bitti: animasyon sürerse "hâlâ denetleniyor" izlenimi verirdi.
      document.querySelectorAll(".paperfall, .scan, .check-stages").forEach((el) => { el.hidden = true; });
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
  // Sayılar sunucudan gelir (report_counts); burada yalnızca görünürlük değişir.
  const filters = [...document.querySelectorAll(".filter")];
  const checkList = document.getElementById("check-list");
  const onlyNote = document.getElementById("filter-only");
  const filterEmpty = document.getElementById("filter-empty");
  const stepPosLabel = document.getElementById("step-pos");
  const applyCards = (show, dimBlock) => {
    document.querySelectorAll(".card").forEach((card) => { card.hidden = !show(card); });
    const shown = document.querySelectorAll(".card:not([hidden])").length;
    if (stepPosLabel) stepPosLabel.textContent = shown + " yorum";
    const visible = new Set([...document.querySelectorAll(".comment:not([hidden])")].map((c) => c.dataset.card));
    // Editör: görünür yorumu olmayan paragrafları soluklaştır.
    document.querySelectorAll(".blk[data-cards]").forEach((blk) => {
      const cards = blk.dataset.cards.split(" ").filter(Boolean);
      blk.classList.toggle("dim", dimBlock(blk, cards, visible));
    });
    return shown;
  };
  const FILTER_TESTS = {
    all: () => true,
    auto: (card) => card.dataset.fixable === "yes",
    manual: (card) => card.dataset.fixable === "no",
    error: (card) => card.dataset.severity === "error",
    warning: (card) => card.dataset.severity === "warning",
    check: () => false, // bulgu değil, paragraf: aşağıdaki liste gösterilir
  };
  const setFilter = (f) => {
    filters.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.filter === f)));
    if (onlyNote) onlyNote.hidden = true;
    if (checkList) checkList.hidden = f !== "check";
    const dim = f === "check"
      ? (blk) => !blk.classList.contains("is-unsure")
      : (blk, cards, visible) => f !== "all" && cards.length > 0 && !cards.some((n) => visible.has(n));
    const shown = applyCards(FILTER_TESTS[f], dim);
    if (filterEmpty) filterEmpty.hidden = shown > 0 || f === "check";
  };
  filters.forEach((btn) => btn.addEventListener("click", () => setFilter(btn.dataset.filter)));
  const showAll = () => { if (filters.length) setFilter("all"); };
  document.querySelectorAll("[data-filter-reset]").forEach((btn) => btn.addEventListener("click", () => {
    showAll();
    const all = filters.find((b) => b.dataset.filter === "all");
    if (all) all.focus();
  }));
  // Özet şeridi: ilgili süzgeci uygular.
  document.querySelectorAll("[data-apply-filter]").forEach((btn) => btn.addEventListener("click", () => {
    const target = filters.find((b) => b.dataset.filter === btn.dataset.applyFilter);
    if (target) { target.click(); target.focus(); }
  }));
  // Bir satırın "+N" rozeti: yalnızca o satırın yorumları.
  const showOnly = (numbers) => {
    filters.forEach((b) => b.setAttribute("aria-pressed", "false"));
    if (checkList) checkList.hidden = true;
    if (filterEmpty) filterEmpty.hidden = true;
    const wanted = new Set(numbers);
    applyCards((card) => wanted.has(card.dataset.card), () => false);
    if (onlyNote) {
      onlyNote.hidden = false;
      document.getElementById("filter-only-text").textContent = "Bu satırın " + wanted.size + " yorumu gösteriliyor.";
    }
  };

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
      // Yapışkan "Bulgular" başlığının altında kalmasın.
      const head = pane.querySelector(".pane-head");
      const gap = head ? head.offsetHeight + 12 : 80;
      const top = el.getBoundingClientRect().top - pane.getBoundingClientRect().top + pane.scrollTop - gap;
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
    // Belgedeki işaret: ilgili yorumu açar; süzgeç gizliyorsa önce süzgeci kaldırır.
    const openCard = (number, blk) => {
      const comment = document.getElementById("c" + number);
      if (!comment) return;
      if (comment.hidden) showAll();
      activateCard(comment, false);
      if (blk) blk.classList.add("active");
      scrollInto(commentsPane, comment);
    };
    document.querySelectorAll(".blk[data-cards]").forEach((blk) => {
      const first = blk.dataset.cards.split(" ").filter(Boolean)[0];
      if (first) blk.addEventListener("click", () => openCard(first, blk));
    });
    document.querySelectorAll("[data-open-card]").forEach((pin) => pin.addEventListener("click", (e) => {
      e.stopPropagation();
      openCard(pin.dataset.openCard, pin.closest(".blk"));
      document.getElementById("c" + pin.dataset.openCard)?.focus({ preventScroll: true });
    }));
    document.querySelectorAll("[data-only-cards]").forEach((more) => more.addEventListener("click", (e) => {
      e.stopPropagation();
      showOnly(more.dataset.onlyCards.split(" "));
      openCard(more.dataset.onlyCards.split(" ")[0], more.closest(".blk"));
    }));
    document.querySelectorAll("[data-jump-block]").forEach((btn) => btn.addEventListener("click", () => {
      const blk = document.getElementById("b" + btn.dataset.jumpBlock);
      if (!blk) return;
      scrollInto(canvas, blk);
      const sel = blk.querySelector("select");
      if (sel) sel.focus({ preventScroll: true });
    }));
    // Klavye: J/K bulgular arasında gezer. Yalnızca odak rapordayken; form alanlarında çalışmaz.
    document.addEventListener("keydown", (e) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key !== "j" && e.key !== "k") return;
      const el = document.activeElement;
      if (!el || !el.closest(".workspace") || el.matches("input, select, textarea")) return;
      e.preventDefault();
      step(e.key === "j" ? 1 : -1);
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

  // --- İsteğe bağlı metin görünümü kutusu: kapatma tercihi ---------------------------------
  const docviewBox = document.getElementById("docview");
  const docviewClose = document.querySelector("[data-docview-dismiss]");
  const docviewShow = document.querySelector("[data-docview-show]");
  if (docviewBox && docviewClose && docviewShow) {
    const KEY = "sontez.docview.dismissed";
    const remember = (on) => {
      try { if (on) localStorage.setItem(KEY, "1"); else localStorage.removeItem(KEY); } catch (err) { /* depo kapalı */ }
    };
    const setDismissed = (on) => { docviewBox.hidden = on; docviewShow.hidden = !on; };
    let dismissed = false;
    try { dismissed = localStorage.getItem(KEY) === "1"; } catch (err) { /* depo kapalı */ }
    setDismissed(dismissed);
    docviewClose.addEventListener("click", () => { remember(true); setDismissed(true); docviewShow.focus(); });
    docviewShow.addEventListener("click", () => { remember(false); setDismissed(false); });
    // Dosya tuvale bırakılarak açıldıysa kutu görünsün (durum satırı orada).
    document.addEventListener("sontez:docfile", () => setDismissed(false));
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
    document.addEventListener("sontez:docfile", (e) => { openFile = e.detail || null; });
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
      if (file) document.dispatchEvent(new CustomEvent("sontez:pickfile", { detail: file }));
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
        a.download = kind === "fixed" ? "sontez-duzeltilmis.docx" : "sontez-yorumlu.docx";
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

  // --- "Bu bulgu yanlış mı?" geri bildirimi ---------------------------------------------
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
    document.querySelectorAll("[data-open-suggest]").forEach((link) => {
      link.hidden = false;
      link.addEventListener("click", () => openBtn.click());
    });
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
