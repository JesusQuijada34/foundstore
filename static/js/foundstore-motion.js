(() => {
  const platform = () => {
    const userAgent = navigator.userAgent || "";
    const touchMac = /Macintosh/i.test(userAgent) && navigator.maxTouchPoints > 1;
    if (/Android/i.test(userAgent)) return "android";
    if (/iPhone|iPad|iPod/i.test(userAgent) || touchMac) return "ios";
    if (/Windows|Macintosh|Linux|CrOS/i.test(userAgent)) return "desktop";
    return "other";
  };
  const details = {
    desktop: { name: "Escritorio detectado", copy: "La solicitud se revisaría en tu DaneDesk vinculado.", state: "LOCAL" },
    android: { name: "Android detectado", copy: "La solicitud seguiría requiriendo aprobación en DaneDesk.", state: "MÓVIL" },
    ios: { name: "iPhone o iPad detectado", copy: "La ventana se adapta a tu navegador sin guardar plataforma.", state: "MÓVIL" },
    other: { name: "Dispositivo detectado", copy: "La solicitud seguiría requiriendo aprobación local.", state: "LOCAL" },
  };
  const initialise = () => {
    const current = platform();
    const copy = details[current];
    document.documentElement.dataset.devicePlatform = current;
    document.querySelectorAll("[data-device-window]").forEach((windowNode) => {
      windowNode.dataset.platform = current;
      const name = windowNode.querySelector("[data-device-platform-name]");
      const description = windowNode.querySelector("[data-device-platform-copy]");
      const state = windowNode.querySelector("[data-device-platform-state]");
      if (name) name.textContent = copy.name;
      if (description) description.textContent = copy.copy;
      if (state) state.textContent = copy.state;
    });
    const controls = document.querySelectorAll("button, .open, .signin, .landing-primary, .landing-secondary, .landing-nav-cta, .pwa-button, .foundstore-package-card a");
    controls.forEach((node) => node.classList.add("motion-control"));
    const surfaces = [...document.querySelectorAll(".card, .foundstore-package-card, .detail, .install, .readme, .security, .landing-stats, .landing-trust, .landing-steps li, .device-window")].slice(0, 8);
    surfaces.forEach((node, index) => { node.classList.add("motion-surface"); node.style.setProperty("--motion-index", String(index)); });
    if (!matchMedia("(prefers-reduced-motion: reduce)").matches) requestAnimationFrame(() => document.documentElement.classList.add("motion-ready"));
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialise, { once: true }); else initialise();
})();
