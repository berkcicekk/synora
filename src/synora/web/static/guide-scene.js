// Kılavuz sayfası: örnek metni kural setindeki ölçülerle dizer; seçilen ölçüyü sayfada işaretler.
// Sayfa yerine otururken ve imleçle yalnızca birkaç derece eğilir. Hareket azaltılmışsa eğilme
// olmaz; işaretleme aynen çalışır. Harici kütüphane yok.
"use strict";

(function () {
  const fig = document.querySelector(".guide-fig");
  const page = document.getElementById("guide-page");
  if (!fig || !page) return;
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const clamp = (v) => Math.min(1, Math.max(0, v));

  // Gerçek ölçek: kural setindeki değerler (geçersizse CSS'teki öntanımlılar kalır)
  [["--pt", "body"], ["--lead", "lead"], ["--indent-cm", "indent"]].forEach(([prop, key]) => {
    const value = parseFloat(String(page.dataset[key] || "").replace(",", "."));
    if (value > 0) page.style.setProperty(prop, value);
  });
  if (page.dataset.font) page.style.setProperty("--page-font", '"' + page.dataset.font.replace(/"/g, "") + '"');
  const inset = page.querySelector("[data-inset]").dataset.inset.split(",");
  page.querySelector(".b-top").style.height = inset[2] + "%";
  page.querySelector(".b-bottom").style.height = inset[3] + "%";

  // --- Seçim ------------------------------------------------------------------------------------
  const controls = [...fig.querySelectorAll("[data-part]")];
  let focus = null;
  const setFocus = (part) => {
    if (focus === part) return;
    focus = part;
    if (part) fig.dataset.focus = part;
    else delete fig.dataset.focus;
    controls.forEach((c) => {
      const on = c.dataset.part === part;
      c.classList.toggle("is-on", on);
      c.setAttribute("aria-pressed", String(on));
    });
  };

  let pointer = "";
  fig.addEventListener("pointerdown", (e) => { pointer = e.pointerType; });
  controls.forEach((c) => {
    const part = c.dataset.part;
    c.addEventListener("pointerenter", (e) => { if (e.pointerType === "mouse") setFocus(part); });
    c.addEventListener("pointerleave", (e) => { if (e.pointerType === "mouse") setFocus(null); });
    c.addEventListener("focus", () => { if (c.matches(":focus-visible")) setFocus(part); });
    c.addEventListener("blur", () => setFocus(null));
    c.addEventListener("click", () => { if (pointer !== "mouse") setFocus(focus === part ? null : part); });
  });
  fig.classList.add("is-live");

  if (reduced) return;

  // --- Hareket: yerine oturma + imleç (en çok 3°) --------------------------------------------------
  const tilt = { x: 0, y: 0, tx: 0, ty: 0 };
  let raf = 0;
  const schedule = () => { if (!raf) raf = requestAnimationFrame(frame); };

  function frame() {
    raf = 0;
    const o = fig.getBoundingClientRect();
    if (o.bottom > 0 && o.top < innerHeight) {
      tilt.x += (tilt.tx - tilt.x) * .12;
      tilt.y += (tilt.ty - tilt.y) * .12;
      const k = 1 - clamp((innerHeight - o.top) / (innerHeight * .6));
      const still = k < .001 && Math.abs(tilt.x) + Math.abs(tilt.y) < .002;
      page.style.transform = still ? "none" : "translateY(" + (k * 14).toFixed(1) + "px)"
        + " rotateX(" + (k * 6 - tilt.y * 6).toFixed(2) + "deg)"
        + " rotateY(" + (tilt.x * 6).toFixed(2) + "deg)";
    }
    if (Math.abs(tilt.tx - tilt.x) + Math.abs(tilt.ty - tilt.y) > .002) schedule();
  }

  window.addEventListener("scroll", schedule, { passive: true });
  window.addEventListener("resize", schedule);
  if (matchMedia("(hover: hover) and (pointer: fine)").matches) {
    fig.addEventListener("pointermove", (e) => {
      const o = fig.getBoundingClientRect();
      tilt.tx = clamp((e.clientX - o.left) / o.width) - .5;
      tilt.ty = clamp((e.clientY - o.top) / o.height) - .5;
      schedule();
    }, { passive: true });
    fig.addEventListener("pointerleave", () => { tilt.tx = 0; tilt.ty = 0; schedule(); });
  }
  schedule();
})();
