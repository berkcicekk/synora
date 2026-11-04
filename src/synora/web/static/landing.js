// Sontez tanıtım sayfası: belirme, parallax, eğilme ve parlama, "nasıl çalışır" tetikleyicisi,
// barkod ve piksel süsleri, sayılar (kılavuz sahnesi: guide-scene.js). Yalnızca bu sayfada
// yüklenir; harici kütüphane yok. Kurallar: hareket transform/opacity ile; hareket azaltılmışsa
// animasyon yok, içerik doğrudan görünür; kaydırma her cihazda, imleç ve eğilme yalnızca farede.
"use strict";

(function () {
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fine = matchMedia("(hover: hover) and (pointer: fine)").matches;
  // CSS gizli başlangıç hâllerini yalnızca bu sınıf varken uygular (JS yoksa içerik görünür).
  if (!reduced) document.documentElement.classList.add("motion");

  const clamp = (v) => Math.min(1, Math.max(0, v));
  const inView = (el) => { const r = el.getBoundingClientRect(); return r.bottom > 0 && r.top < innerHeight; };
  // Öğenin üstü ekranın altına gelince 0, `span` ekran boyu sonra 1.
  const progress = (el, span) => clamp((innerHeight - el.getBoundingClientRect().top) / (innerHeight * span));
  const move = (el, x, y) => { el.style.transform = "translate3d(" + x.toFixed(1) + "px," + y.toFixed(1) + "px,0)"; };

  // --- Süsler -----------------------------------------------------------------------------
  // Deterministik sözde rastgele: her yüklemede aynı desen.
  const seeded = (seed) => () => { seed = (seed * 9301 + 49297) % 233280; return seed / 233280; };

  // Barkod bandı: tezin satırları. Çubuklar şeritlerde: kaydırınca satırlar zıt yöne akar.
  const barcode = document.getElementById("barcode");
  let stripsA = [], stripB = null;
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
    const strip = (row, n, one, before) => {
      const s = document.createElement("span");
      s.className = "barcode-bars";
      for (let i = 0; i < n; i++) s.appendChild(one(i));
      row.insertBefore(s, before || null);
      return s;
    };
    const rows = barcode.querySelectorAll(".barcode-row");
    const note = rows[0].querySelector(".barcode-note");
    stripsA = [
      strip(rows[0], 30, (i) => (i === 4 ? bar({ w: 2, slant: true, keep: true })
        : i === 17 ? bar({ w: 4, accent: true }) : bar()), note),
      strip(rows[0], 20, () => bar()),
    ];
    stripB = strip(rows[1], 60, (i) => (i === 8 ? bar({ w: 5, accent: true })
      : i === 51 ? bar({ w: 3, slant: true, keep: true }) : bar()));
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
        // Yalnız köşedeki yığın: üst bölgeye serpilen kareler metnin üstüne biniyordu.
        const onL = (ROWS - r) <= ROWS - Math.floor(c * 0.75) - Math.floor(rnd() * 2) - 1;
        const a = document.createElement("i");
        if (onL) a.style.background = shades[Math.floor(rnd() * shades.length)];
        pxLeft.appendChild(a);
        const onR = (ROWS - r) <= Math.floor(c * 0.8) + 1 - Math.floor(rnd() * 2);
        const b = document.createElement("i");
        if (onR) b.style.background = shades[Math.floor(rnd() * shades.length)];
        pxRight.appendChild(b);
      }
    }
  }

  // Sayılar: görününce gerçek değere kadar sayar; sonunda sunucudan gelen metin aynen geri yazılır.
  const countUp = (el) => {
    const full = el.textContent;
    const m = /^(\D*)(\d+)(?:,(\d+))?$/.exec(full);
    if (!m) return;
    const end = Number(m[2] + "." + (m[3] || "0")), digits = (m[3] || "").length, t0 = performance.now();
    const tick = (now) => {
      const k = clamp((now - t0) / 1200);
      el.textContent = k < 1 ? m[1] + (end * (1 - Math.pow(1 - k, 3))).toFixed(digits).replace(".", ",") : full;
      if (k < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  };

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
      if (en.target.matches(".guide-stats")) en.target.querySelectorAll(".n").forEach(countUp);
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

  // --- Parallax: kahraman, barkod, gizlilik, kılavuz metni; tek rAF döngüsünde -----------------
  const hero = document.querySelector(".hero");
  const heroWrap = hero && hero.querySelector(".wrap");
  const layers = [...document.querySelectorAll(".hero-layers [data-depth]")];
  const stage = document.querySelector(".privacy-stage");
  const guide = document.querySelector("[data-guide]");
  const text = document.getElementById("guide-text");
  const cursor = { x: 0, y: 0, tx: 0, ty: 0 }; // ekrana göre -0,5…+0,5
  let raf = 0;
  const frame = () => {
    raf = 0;
    cursor.x += (cursor.tx - cursor.x) * .1;
    cursor.y += (cursor.ty - cursor.y) * .1;
    const y = window.scrollY;
    if (hero && y < hero.offsetHeight * 1.2) {
      layers.forEach((el) => {
        const depth = Number(el.dataset.depth);
        move(el, cursor.x * depth * 120, y * depth + cursor.y * depth * 90);
      });
      if (heroWrap) {
        // Metin geride kalır; düğmeler ekrandayken okunur kalsın diye solma geç başlar.
        const fade = clamp((y / hero.offsetHeight - .35) / .65);
        move(heroWrap, 0, y * .08);
        heroWrap.style.opacity = (1 - fade * .5).toFixed(3);
      }
    }
    if (barcode && inView(barcode)) {
      const d = (progress(barcode, 1.3) - .5) * 64;
      stripsA.forEach((s) => move(s, d, 0));
      move(stripB, -d, 0);
    }
    if (stage && pxLeft && inView(stage)) {
      const k = 1 - progress(stage, .75);
      move(pxLeft, 0, k * pxLeft.offsetHeight * .8);
      move(pxRight, 0, k * pxRight.offsetHeight * 1.2);
    }
    if (fine && guide && text && inView(guide)) {
      const r = guide.getBoundingClientRect();
      move(text, 0, (clamp((innerHeight - r.top) / (innerHeight + r.height)) - .5) * 60);
    }
    if (Math.abs(cursor.tx - cursor.x) + Math.abs(cursor.ty - cursor.y) > .002) schedule();
  };
  const schedule = () => { if (!raf) raf = requestAnimationFrame(frame); };
  if (!reduced) {
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    schedule();
  }

  if (reduced || !fine) return;  // aşağısı: imleç izleme ve eğilme (yalnızca fare, hareket açık)

  window.addEventListener("pointermove", (e) => {
    cursor.tx = e.clientX / innerWidth - .5;
    cursor.ty = e.clientY / innerHeight - .5;
    schedule();
  }, { passive: true });

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
