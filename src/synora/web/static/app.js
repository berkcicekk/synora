// Synora arayüzü: yükleme, durum takibi, bulgu süzme. Harici kütüphane yok.
"use strict";

(function () {
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

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!file) return;
      submit.disabled = true;
      say("Yükleniyor…");
      try {
        const res = await fetch("/jobs", {
          method: "POST",
          headers: {
            "Content-Type": "application/octet-stream",
            "X-CSRF-Token": form.dataset.csrf,
            "X-Ruleset": document.getElementById("ruleset").value,
          },
          body: file,
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          say(data.error || "Yükleme başarısız oldu. Sayfayı yenileyip yeniden deneyin.", true);
          submit.disabled = false;
          return;
        }
        window.location.href = data.url;
      } catch (err) {
        say("Bağlantı hatası. İnternet bağlantınızı kontrol edip yeniden deneyin.", true);
        submit.disabled = false;
      }
    });
  }

  // --- Durum takibi -------------------------------------------------------------------------
  const poller = document.querySelector("[data-poll]");
  if (poller) {
    const url = poller.dataset.poll;
    const tick = async () => {
      try {
        const res = await fetch(url, { headers: { Accept: "application/json" } });
        const data = await res.json();
        if (data.status !== "queued" && data.status !== "running") {
          window.location.reload();
          return;
        }
      } catch (err) { /* geçici hata: yeniden dene */ }
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
        || card.dataset.severity === f;
      card.hidden = !show;
    });
    const empty = document.getElementById("filter-empty");
    if (empty) empty.hidden = document.querySelectorAll(".card:not([hidden])").length > 0;
    // Editör: görünür yorumu olmayan paragrafları soluklaştır.
    const visible = new Set([...document.querySelectorAll(".comment:not([hidden])")].map((c) => c.dataset.card));
    document.querySelectorAll(".blk[data-cards]").forEach((blk) => {
      const cards = blk.dataset.cards.split(" ").filter(Boolean);
      blk.classList.toggle("dim", f !== "all" && cards.length > 0 && !cards.some((n) => visible.has(n)));
    });
  }));

  // --- Editör: yorum ↔ paragraf ------------------------------------------------------------
  const canvas = document.querySelector(".pane-canvas");
  const commentsPane = document.querySelector(".pane-comments");
  if (canvas && commentsPane) {
    const clearActive = () => document.querySelectorAll(".blk.active, .comment.active")
      .forEach((el) => el.classList.remove("active"));
    const scrollInto = (pane, el) => {
      const top = el.getBoundingClientRect().top - pane.getBoundingClientRect().top + pane.scrollTop - 80;
      pane.scrollTo({ top, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    };
    const activateCard = (comment, scrollCanvas) => {
      clearActive();
      comment.classList.add("active");
      const blocks = comment.dataset.blocks.split(" ").filter(Boolean)
        .map((i) => document.getElementById("b" + i)).filter(Boolean);
      blocks.forEach((b) => b.classList.add("active"));
      if (scrollCanvas && blocks[0]) scrollInto(canvas, blocks[0]);
    };
    document.querySelectorAll(".comment").forEach((c) => {
      c.addEventListener("click", (e) => { if (!e.target.closest("summary")) activateCard(c, true); });
      c.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activateCard(c, true); } });
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

  // Amblem, kahraman alanında imlecin yönüne hafifçe döner ve kayar.
  const logo = document.querySelector("#hero-logo .hero-logo-inner");
  const hero = document.querySelector(".hero");
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

  // --- Silme onayı (tarayıcı confirm() yerine sayfa içi) ------------------------------------
  document.querySelectorAll("[data-confirm]").forEach((btn) => btn.addEventListener("click", () => {
    btn.hidden = true;
    const real = btn.parentElement.querySelector("button[type=submit]");
    real.hidden = false;
    real.focus();
  }));
})();
