// Payper tanıtım sayfası: belirme, hafif kaydırma (parallax), eğilme ve parlama, "nasıl çalışır"
// tetikleyicisi, barkod ve piksel süsleri. Yalnızca bu sayfada yüklenir; harici kütüphane yok.
// Kurallar: yalnızca transform/opacity değişir; hareket azaltılmışsa animasyon yok, içerik
// doğrudan görünür; parallax ve eğilme yalnızca fareli cihazlarda.
"use strict";

(function () {
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fine = matchMedia("(hover: hover) and (pointer: fine)").matches;
  // CSS gizli başlangıç hâllerini yalnızca bu sınıf varken uygular (JS yoksa içerik görünür).
  if (!reduced) document.documentElement.classList.add("motion");

  // --- Süsler -----------------------------------------------------------------------------
  // Deterministik sözde rastgele: her yüklemede aynı desen.
  const seeded = (seed) => () => { seed = (seed * 9301 + 49297) % 233280; return seed / 233280; };

  // Barkod bandı: tezin satırları
  const barcode = document.getElementById("barcode");
  if (barcode) {
    const rnd = seeded(7);
    const bar = (o = {}) => {
      const w = o.w || [1, 2, 2, 3, 4, 5][Math.floor(rnd() * 6)];
      const ghost = !o.keep && !o.accent && rnd() < 0.12;
      const el = document.createElement("i");
      el.style.flex = "0 0 " + w + "px";
      el.style.background = o.accent ? "var(--accent)" : (ghost ? "transparent" : "var(--ink)");
      if (o.slant) { el.style.transform = "skewX(-18deg)"; el.style.transformOrigin = "bottom"; }
      return el;
    };
    const rows = barcode.querySelectorAll(".barcode-row");
    const note = rows[0].querySelector(".barcode-note");
    for (let i = 0; i < 30; i++) {
      rows[0].insertBefore(i === 4 ? bar({ w: 2, slant: true, keep: true })
        : i === 17 ? bar({ w: 4, accent: true }) : bar(), note);
    }
    for (let i = 0; i < 20; i++) rows[0].appendChild(bar());
    for (let i = 0; i < 60; i++) {
      rows[1].appendChild(i === 8 ? bar({ w: 5, accent: true })
        : i === 51 ? bar({ w: 3, slant: true, keep: true }) : bar());
    }
    barcode.hidden = false;
  }

  // Gizlilik: köşelerde piksel yığınları (tonlar vurgu renginden türetilir)
  const pxLeft = document.getElementById("pixels-left");
  const pxRight = document.getElementById("pixels-right");
  if (pxLeft && pxRight) {
    const rnd = seeded(11);
    const tone = (p) => "color-mix(in srgb, var(--accent) " + p + "%, var(--surface))";
    const shades = ["var(--accent)", "var(--accent)", tone(60), tone(35), tone(15)];
    const COLS = 16, ROWS = 12;
    for (let r = 0; r < ROWS; r++) {
      for (let c = 0; c < COLS; c++) {
        const onL = (ROWS - r) <= ROWS - Math.floor(c * 0.75) - Math.floor(rnd() * 2) - 1
          || (rnd() < 0.04 && r > 2);
        const a = document.createElement("i");
        if (onL) a.style.background = shades[Math.floor(rnd() * shades.length)];
        pxLeft.appendChild(a);
        const onR = (ROWS - r) <= Math.floor(c * 0.8) + 1 - Math.floor(rnd() * 2) || (rnd() < 0.03 && r > 3);
        const b = document.createElement("i");
        if (onR) b.style.background = shades[Math.floor(rnd() * shades.length)];
        pxRight.appendChild(b);
      }
    }
  }

  // --- Belirme: bölümler görünür olunca yumuşakça gelir; [data-stagger] çocukları sırayla ----
  const reveals = [...document.querySelectorAll(".reveal")];
  document.querySelectorAll("[data-stagger]").forEach((p) =>
    [...p.children].forEach((c, i) => c.style.setProperty("--i", i)));
  const hiw = document.querySelector("[data-hiw]");
  const steps = hiw ? [...hiw.querySelectorAll(".hiw-step")] : [];
  steps.forEach((s, i) => s.style.setProperty("--i", i));
  if (!reduced && "IntersectionObserver" in window) {
    const io = new IntersectionObserver((entries) => entries.forEach((en) => {
      if (!en.isIntersecting) return;
      en.target.classList.add("is-in");
      io.unobserve(en.target);
    }), { rootMargin: "0px 0px -8% 0px", threshold: 0.15 });
    reveals.forEach((el) => io.observe(el));
    // "Nasıl çalışır": çizimler hazır hâlden başlar, her adım görününce canlanır.
    if (hiw) {
      hiw.classList.add("is-armed");
      steps.forEach((s) => io.observe(s));
    }
  } else {
    reveals.forEach((el) => el.classList.add("is-in"));
    steps.forEach((s) => s.classList.add("is-in"));
  }

  if (reduced || !fine) return;  // aşağısı: parallax ve eğilme (yalnızca fare, hareket açık)

  // --- Parallax: kahraman katmanları ve kılavuz sayfası, tek rAF döngüsünde ------------------
  const hero = document.querySelector(".hero");
  const layers = [...document.querySelectorAll(".hero-layers [data-depth]")];
  const guide = document.querySelector("[data-guide]");
  const page = document.getElementById("guide-page");
  const text = document.getElementById("guide-text");
  const chips = guide ? [...guide.querySelectorAll(".guide-chip")] : [];
  let raf = 0;
  const frame = () => {
    raf = 0;
    const y = window.scrollY;
    const vh = window.innerHeight || 800;
    if (hero && y < hero.offsetHeight * 1.2) {
      layers.forEach((el) => {
        el.style.transform = "translate3d(0," + (y * Number(el.dataset.depth)).toFixed(1) + "px,0)";
      });
    }
    if (guide) {
      const r = guide.getBoundingClientRect();
      if (r.bottom > 0 && r.top < vh) {
        const d = Math.max(0, Math.min(1, (vh - r.top) / (vh + r.height))) - 0.5;
        if (page) page.style.transform =
          "translate3d(0," + (d * -140).toFixed(1) + "px,0) rotate(" + (d * -6).toFixed(2) + "deg)";
        if (text) text.style.transform = "translate3d(0," + (d * 60).toFixed(1) + "px,0)";
        chips.forEach((c) => {
          c.style.transform = "translate3d(0," + (d * Number(c.dataset.v || 0)).toFixed(1) + "px,0)";
        });
      }
    }
  };
  const schedule = () => { if (!raf) raf = requestAnimationFrame(frame); };
  window.addEventListener("scroll", schedule, { passive: true });
  window.addEventListener("resize", schedule);
  frame();

  // --- Eğilme + ışık parlaması: fareyi hafifçe izler (en çok 5°) ----------------------------
  document.querySelectorAll(".tilt").forEach((card) => {
    let pending = null;
    let tiltRaf = 0;
    const apply = () => {
      tiltRaf = 0;
      if (!pending) return;
      const r = card.getBoundingClientRect();
      const x = (pending.clientX - r.left) / r.width;
      const y = (pending.clientY - r.top) / r.height;
      card.style.setProperty("--ry", ((x - 0.5) * 10).toFixed(2) + "deg");
      card.style.setProperty("--rx", ((0.5 - y) * 10).toFixed(2) + "deg");
      card.style.setProperty("--mx", (x * 100).toFixed(1) + "%");
      card.style.setProperty("--my", (y * 100).toFixed(1) + "%");
    };
    card.addEventListener("pointermove", (e) => {
      pending = e;
      if (!tiltRaf) tiltRaf = requestAnimationFrame(apply);
    });
    card.addEventListener("pointerleave", () => {
      pending = null;
      card.style.setProperty("--rx", "0deg");
      card.style.setProperty("--ry", "0deg");
    });
  });
})();
