(() => {
  const DEFAULT_BACKEND_URL = "https://kevsono-kevs-digital-bos.hf.space";
  const DEFAULT_BI_URL = "https://kevsono-kevs-digital-business-intelligencev2.hf.space";
  const DEFAULT_CONCIERGE_URL = "https://kevsono-penafort-concierge.hf.space";

  const norm = (val, fallback) =>
    String((typeof window !== "undefined" && val) || fallback).replace(/\/+$/, "");

  const apiUrl = norm(window.__KDBS_BACKEND_URL__, DEFAULT_BACKEND_URL);
  const biUrl = norm(window.__KDBS_BI_URL__, DEFAULT_BI_URL);
  const conciergeUrl = norm(window.__KDBS_CONCIERGE_URL__, DEFAULT_CONCIERGE_URL);

  window.KDBS_API_URL = apiUrl;
  window.KDBS_BACKEND_URL = apiUrl;
  window.KDBS_BI_URL = biUrl;
  window.KDBS_CONCIERGE_URL = conciergeUrl;
  window.getKdbsBackendUrl = function getKdbsBackendUrl() {
    return window.KDBS_API_URL;
  };
})();
