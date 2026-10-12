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
  }));

  // --- Silme onayı (tarayıcı confirm() yerine sayfa içi) ------------------------------------
  document.querySelectorAll("[data-confirm]").forEach((btn) => btn.addEventListener("click", () => {
    btn.hidden = true;
    const real = btn.parentElement.querySelector("button[type=submit]");
    real.hidden = false;
    real.focus();
  }));
})();
