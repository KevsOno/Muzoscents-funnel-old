(() => {
  const DEFAULT_BACKEND_URL = "https://kevsono-kevs-digital-bos.hf.space";
  const rawUrl =
    (typeof window !== "undefined" && window.__KDBS_BACKEND_URL__) ||
    DEFAULT_BACKEND_URL;
  const normalizedUrl = String(rawUrl || DEFAULT_BACKEND_URL).replace(/\/+$/, "");

  window.KDBS_API_URL = normalizedUrl;
  window.KDBS_BACKEND_URL = normalizedUrl;
  window.getKdbsBackendUrl = function getKdbsBackendUrl() {
    return window.KDBS_API_URL;
  };
})();
