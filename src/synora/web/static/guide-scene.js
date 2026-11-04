// Kılavuz sahnesi: 3D A4 kağıt, etiketlerden kağıda noktalı bağlar, seçilen ölçünün "analizi" ve
// bir kez dönen otomatik tur. Yalnızca ana sayfada yüklenir; harici kütüphane yok.
// Hareket azaltılmışsa 3D ve tur çalışmaz; bağlar sabit durur, seçim vurgusu hareketsiz çalışır.
"use strict";

(function () {
  const fig = document.querySelector(".guide-fig");
  const page = document.getElementById("guide-page");
  if (!fig || !page) return;
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fine = matchMedia("(hover: hover) and (pointer: fine)").matches;
  const clamp = (v) => Math.min(1, Math.max(0, v));

  let raf = 0, until = 0;
  const kick = (ms) => {
    until = Math.max(until, performance.now() + (ms || 0));
    if (!raf) raf = requestAnimationFrame(frame);
  };

  fig.classList.add("is-live");
  const [left, right, top, bottom] = page.querySelector("[data-inset]").dataset.inset.split(",");
  page.querySelector(".b-left").style.width = left + "%";
  page.querySelector(".b-right").style.width = right + "%";
  page.querySelector(".b-top").style.height = top + "%";
  page.querySelector(".b-bottom").style.height = bottom + "%";

  // --- Noktalı bağlar ------------------------------------------------------------------------
  const NS = "http://www.w3.org/2000/svg";
  const DOTS = 12;
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("class", "guide-links");
  svg.setAttribute("aria-hidden", "true");
  fig.appendChild(svg);
  // Her etiketin kağıttaki yeri: [satır, satır boyunca konum]
  const TARGET = { size: [".l-size", .7], spacing: [".l-sp", .35], indent: [".l-ind", .03], font: [".l-font", .55] };
  const controls = [...fig.querySelectorAll("[data-part]")];
  const chips = controls.filter((c) => TARGET[c.dataset.part]);
  const links = chips.map((chip) => {
    const [selector, along] = TARGET[chip.dataset.part];
    const g = document.createElementNS(NS, "g");
    const dots = [];
    for (let i = 0; i < DOTS; i++) {
      const dot = document.createElementNS(NS, "circle");
      dot.setAttribute("r", i === DOTS - 1 ? "3.2" : "1.5");
      dot.style.transitionDelay = i * 45 + "ms";
      g.appendChild(dot);
      dots.push(dot);
    }
    svg.appendChild(g);
    return { chip, g, dots, along, part: chip.dataset.part, target: page.querySelector(selector) };
  });

  const drawLinks = () => {
    const o = fig.getBoundingClientRect();
    links.forEach((link) => {
      const a = link.chip.getBoundingClientRect(), b = link.target.getBoundingClientRect();
      const x0 = a.left + a.width / 2 - o.left, y0 = a.top - o.top;
      const x1 = b.left + b.width * link.along - o.left, y1 = b.top + b.height / 2 - o.top;
      const cx = x0 + (x1 - x0) * .2, cy = y1 + (y0 - y1) * .45; // eğri: önce yukarı, sonra hedefe
      link.dots.forEach((dot, i) => {
        const u = (i + 1) / DOTS, v = 1 - u;
        dot.setAttribute("cx", (v * v * x0 + 2 * v * u * cx + u * u * x1).toFixed(1));
        dot.setAttribute("cy", (v * v * y0 + 2 * v * u * cy + u * u * y1).toFixed(1));
      });
    });
  };

  // --- Seçim: analiz ---------------------------------------------------------------------------
  const tag = page.querySelector(".guide-tag");
  const scan = page.querySelector(".guide-scan");
  let focus = null, hovering = false;
  const syncOpen = () => { fig.classList.toggle("is-open", hovering || !!focus); kick(700); };
  const setFocus = (part, source) => {
    if (focus === part) return;
    focus = part;
    if (part) {
      fig.dataset.focus = part;
      tag.textContent = source.textContent;
      scan.classList.remove("run");
      void scan.offsetWidth; // aynı animasyonu baştan oynatmak için
      scan.classList.add("run");
    } else delete fig.dataset.focus;
    controls.forEach((c) => {
      const on = c.dataset.part === part;
      c.classList.toggle("is-on", on);
      c.setAttribute("aria-pressed", String(on));
    });
    links.forEach((link) => link.g.classList.toggle("on", link.part === part));
    syncOpen();
  };

  // Otomatik tur: sahne görününce etiketler bir kez dolaşılır; etkileşim başlayınca biter.
  let timer = 0, tourOver = reduced;
  const endTour = () => { tourOver = true; clearTimeout(timer); };
  const tour = (i) => {
    timer = setTimeout(() => {
      if (i < chips.length) { setFocus(chips[i].dataset.part, chips[i]); tour(i + 1); }
      else { tourOver = true; setFocus(null); }
    }, i ? 1700 : 800);
  };

  let pointer = "";
  fig.addEventListener("pointerdown", (e) => { pointer = e.pointerType; });
  controls.forEach((c) => {
    const part = c.dataset.part;
    c.addEventListener("pointerenter", (e) => { if (e.pointerType === "mouse") setFocus(part, c); });
    c.addEventListener("pointerleave", (e) => { if (e.pointerType === "mouse") setFocus(null); });
    c.addEventListener("focus", () => { if (c.matches(":focus-visible")) { endTour(); setFocus(part, c); } });
    c.addEventListener("blur", () => { if (tourOver) setFocus(null); });
    c.addEventListener("click", () => {
      endTour();
      if (pointer !== "mouse") setFocus(focus === part ? null : part, c);
    });
  });
  fig.addEventListener("pointerenter", (e) => {
    if (e.pointerType === "mouse" && !tourOver) { endTour(); setFocus(null); }
  });
  const hover = (on) => (e) => { if (e.pointerType === "mouse") { hovering = on; syncOpen(); } };
  page.addEventListener("pointerenter", hover(true));
  page.addEventListener("pointerleave", hover(false));

  const seen = () => { svg.classList.add("is-linked"); kick(); };
  if ("IntersectionObserver" in window) {
    new IntersectionObserver((entries) => entries.forEach((en) => {
      if (en.isIntersecting) {
        seen();
        if (!tourOver) tour(0);
      } else if (!tourOver) { clearTimeout(timer); setFocus(null); }
    }), { threshold: 0.4 }).observe(fig);
  } else seen();

  // --- 3D kağıt: kaydırınca doğrulur, imleci izler -----------------------------------------------
  const sheen = page.querySelector(".guide-sheen");
  const cursor = { x: 0, y: 0, tx: 0, ty: 0, cx: 0, cy: 0 }; // x, y: ekrana göre -0,5…+0,5

  function frame() {
    raf = 0;
    const o = fig.getBoundingClientRect();
    if (o.bottom > 0 && o.top < innerHeight) {
      if (!reduced) {
        cursor.x += (cursor.tx - cursor.x) * .1;
        cursor.y += (cursor.ty - cursor.y) * .1;
        const k = 1 - clamp((innerHeight - o.top) / (innerHeight * .7));
        const lie = k * k * (3 - 2 * k);
        page.style.transform = "translate3d(0," + (lie * 30).toFixed(1) + "px,0)"
          + " rotateX(" + (lie * 32 - cursor.y * 16).toFixed(2) + "deg)"
          + " rotateY(" + (lie * -16 + cursor.x * 16).toFixed(2) + "deg)"
          + " rotateZ(" + (lie * -7).toFixed(2) + "deg)";
        if (fine) {
          sheen.style.setProperty("--sx", clamp((cursor.cx - o.left) / o.width) * 100 + "%");
          sheen.style.setProperty("--sy", clamp((cursor.cy - o.top) / o.height) * 100 + "%");
        }
      }
      drawLinks();
    }
    const moving = !reduced && Math.abs(cursor.tx - cursor.x) + Math.abs(cursor.ty - cursor.y) > .002;
    if (moving || performance.now() < until) raf = requestAnimationFrame(frame);
  }

  window.addEventListener("scroll", () => kick(), { passive: true });
  window.addEventListener("resize", () => kick());
  window.addEventListener("load", () => kick());
  if (document.fonts) document.fonts.ready.then(() => kick());
  if (!reduced && fine) {
    window.addEventListener("pointermove", (e) => {
      cursor.tx = e.clientX / innerWidth - .5;
      cursor.ty = e.clientY / innerHeight - .5;
      cursor.cx = e.clientX;
      cursor.cy = e.clientY;
      kick();
    }, { passive: true });
  }
  kick();
})();
