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
    let ticking = false;
    const update = () => {
      const y = window.scrollY;
      layers.forEach((el) => { el.style.transform = "translate3d(0," + (y * Number(el.dataset.speed)).toFixed(1) + "px,0)"; });
      ticking = false;
    };
    window.addEventListener("scroll", () => { if (!ticking) { ticking = true; requestAnimationFrame(update); } }, { passive: true });
    update();
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
    let kind = null;
    const say = (msg, isError) => {
      status.textContent = msg;
      status.classList.toggle("error", Boolean(isError));
    };
    outputs.querySelectorAll("[data-output]").forEach((btn) => btn.addEventListener("click", () => {
      kind = btn.dataset.output;
      say("Denetlediğiniz dosyayı yeniden seçin.");
      picker.value = "";
      picker.click();
    }));
    picker.addEventListener("change", async () => {
      const file = picker.files[0];
      if (!file || !kind) return;
      const buttons = outputs.querySelectorAll("[data-output]");
      buttons.forEach((b) => { b.disabled = true; });
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
