// kdint.js — API transport interceptor.
// Loaded blocking in <head>, BEFORE any other script that calls fetch.
//
// Responsibilities:
//   1. Inject X-Selected-Org-Id and X-Selected-Branch-Id on every API call.
//      The org header is skipped if the caller already set one (idempotent).
//      The branch header is skipped if the stored value is '__all__' — the
//      backend interprets absence as "all branches for owners" and would
//      400 for non-owners if we sent it.
//   2. Handle 402 responses (suspended organisation / feature-gated endpoint).
//   3. On 400 "Multiple branches available" and on the two 403 branch/org
//      membership errors, clear the stale selection and dispatch
//      kd:branch-error so kdsession.js can re-show the picker.
//   4. Expose branch/org state helpers so kdsession.js has one source of
//      truth for localStorage reads and writes.
//
// 402 handling is unchanged from the previous version — only its position
// within the response switch moved.
(function () {
  'use strict';

  // ─── Configuration ───
  var API_BASE      = 'https://kevsono-kevs-digital-bos.hf.space';
  var SUPPORT_EMAIL = 'mickevsono@gmail.com';
  var ALL_BRANCHES  = '__all__';

  // Org storage keys are tried in order so pages that predate the
  // kd_selected_* namespace still work.
  var ORG_ID_KEYS    = ['kd_selected_org_id', 'selected_org_id'];
  var ORG_NAME_KEYS  = ['kd_selected_org_name', 'selected_org_name'];
  var BRANCH_ID_KEY  = 'kd_selected_branch_id';
  var BRANCH_NAME_KEY = 'kd_selected_branch_name';
  var DISMISSED_KEY  = 'kd402_dismissed_features';

  // ─── Utilities ───
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function readLocal(keys) {
    for (var i = 0; i < keys.length; i++) {
      var v = localStorage.getItem(keys[i]);
      if (v) return v;
    }
    return null;
  }

  // ─── Org / branch state ───
  function readSelectedOrg() {
    return readLocal(ORG_ID_KEYS);
  }
  function readSelectedOrgName() {
    return readLocal(ORG_NAME_KEYS);
  }
  function writeSelectedOrg(id, name) {
    try {
      if (id)   {
        localStorage.setItem('kd_selected_org_id', id);
        localStorage.setItem('selected_org_id', id);  // legacy key parity
      } else {
        localStorage.removeItem('kd_selected_org_id');
        localStorage.removeItem('selected_org_id');
      }
      if (name) {
        localStorage.setItem('kd_selected_org_name', name);
        localStorage.setItem('selected_org_name', name);
      } else {
        localStorage.removeItem('kd_selected_org_name');
        localStorage.removeItem('selected_org_name');
      }
    } catch (e) {}
  }
  function clearSelectedOrg() {
    writeSelectedOrg(null, null);
  }

  function readSelectedBranch() {
    try { return localStorage.getItem(BRANCH_ID_KEY) || null; } catch (e) { return null; }
  }
  function readSelectedBranchName() {
    try { return localStorage.getItem(BRANCH_NAME_KEY) || null; } catch (e) { return null; }
  }
  function writeSelectedBranch(id, name) {
    try {
      if (id)   localStorage.setItem(BRANCH_ID_KEY, id);
      else      localStorage.removeItem(BRANCH_ID_KEY);
      if (name) localStorage.setItem(BRANCH_NAME_KEY, name);
      else      localStorage.removeItem(BRANCH_NAME_KEY);
    } catch (e) {}
  }
  function clearSelectedBranch() {
    writeSelectedBranch(null, null);
  }

  // ─── Dismissed features (session-scoped) ───
  var dismissedFeatures = (function () {
    try {
      var raw = sessionStorage.getItem(DISMISSED_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch (e) { return {}; }
  })();
  function saveDismissed() {
    try {
      sessionStorage.setItem(DISMISSED_KEY, JSON.stringify(dismissedFeatures));
    } catch (e) {}
  }
  function isDismissed(key) { return !!dismissedFeatures[key]; }
  function markDismissed(key) {
    if (!key) return;
    dismissedFeatures[key] = true;
    saveDismissed();
  }

  // ─── Suspended modal ───
  var suspendedModal = null;
  function ensureSuspendedModal() {
    if (suspendedModal) return suspendedModal;
    var el = document.createElement('div');
    el.id = 'kd402-suspended-modal';
    el.style.cssText = [
      'position:fixed', 'inset:0', 'z-index:2147483647',
      'background:rgba(0,0,0,0.88)', 'backdrop-filter:blur(6px)',
      'display:none', 'align-items:center', 'justify-content:center',
      'padding:1.5rem'
    ].join(';');
    el.innerHTML =
      '<div style="max-width:520px;width:100%;background:#1a1414;border:1px solid #7f1d1d;border-radius:20px;padding:2rem;box-shadow:0 24px 60px rgba(0,0,0,0.6);font-family:Inter,system-ui,-apple-system,sans-serif;color:#e5e7eb;">' +
        '<div style="text-align:center;margin-bottom:1.25rem;">' +
          '<div style="font-size:3rem;line-height:1;color:#f87171;">\u26A0</div>' +
          '<h2 style="font-size:1.4rem;font-weight:700;color:#fecaca;margin-top:0.75rem;">Organisation suspended</h2>' +
          '<p id="kd402-suspended-org" style="font-size:0.95rem;color:#fca5a5;margin-top:0.25rem;font-weight:500;"></p>' +
        '</div>' +
        '<div style="background:#0f0a0a;border:1px solid #4c1d1d;border-radius:12px;padding:1rem 1.15rem;font-size:0.88rem;line-height:1.55;color:#d1d5db;">' +
          '<p id="kd402-suspended-message" style="margin:0;"></p>' +
        '</div>' +
        '<p style="font-size:0.78rem;color:#9ca3af;margin-top:1rem;line-height:1.5;">' +
          'If you believe this is an error, contact support and quote your organisation name.' +
        '</p>' +
        '<div style="display:flex;gap:0.6rem;margin-top:1.5rem;">' +
          '<a id="kd402-suspended-mail" href="#" style="flex:1;text-align:center;background:#334155;color:#e5e7eb;padding:0.7rem;border-radius:10px;text-decoration:none;font-size:0.85rem;font-weight:500;">Contact support</a>' +
          '<button id="kd402-suspended-logout" style="flex:1;background:#b91c1c;color:#fff;padding:0.7rem;border-radius:10px;border:none;font-size:0.85rem;font-weight:600;cursor:pointer;">Log out</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(el);

    el.querySelector('#kd402-suspended-logout').addEventListener('click', function () {
      try { localStorage.clear(); } catch (e) {}
      try { sessionStorage.removeItem(DISMISSED_KEY); } catch (e) {}
      window.location.href = '/kdsiginin';
    });

    suspendedModal = el;
    return el;
  }
  function showSuspended(detail) {
    var el = ensureSuspendedModal();
    var orgName = readSelectedOrgName() || '(unknown organisation)';
    el.querySelector('#kd402-suspended-org').textContent = orgName;
    el.querySelector('#kd402-suspended-message').textContent =
      detail || 'This organisation has been suspended. All features are disabled until an administrator reactivates it.';
    var mail = el.querySelector('#kd402-suspended-mail');
    mail.href = 'mailto:' + SUPPORT_EMAIL
      + '?subject=' + encodeURIComponent('Suspended organisation: ' + orgName)
      + '&body=' + encodeURIComponent(
          'Organisation: ' + orgName + '\nOrg ID: ' + (readSelectedOrg() || '') + '\n\nDescribe the issue:\n'
        );
    el.style.display = 'flex';
  }
  function hideSuspended() {
    if (suspendedModal) suspendedModal.style.display = 'none';
  }

  // ─── Feature-required modal ───
  var featureModal = null;
  var currentFeatureKey = null;
  var featureQueue = [];

  function ensureFeatureModal() {
    if (featureModal) return featureModal;
    var el = document.createElement('div');
    el.id = 'kd402-feature-modal';
    el.style.cssText = [
      'position:fixed', 'inset:0', 'z-index:2147483646',
      'background:rgba(0,0,0,0.82)', 'backdrop-filter:blur(4px)',
      'display:none', 'align-items:center', 'justify-content:center',
      'padding:1.5rem'
    ].join(';');
    el.innerHTML =
      '<div style="max-width:480px;width:100%;background:#141a1a;border:1px solid #78350f;border-radius:20px;padding:2rem;box-shadow:0 24px 60px rgba(0,0,0,0.55);font-family:Inter,system-ui,-apple-system,sans-serif;color:#e5e7eb;">' +
        '<div style="text-align:center;margin-bottom:1.25rem;">' +
          '<div style="font-size:3rem;line-height:1;color:#fbbf24;">\uD83D\uDD12</div>' +
          '<h2 style="font-size:1.35rem;font-weight:700;color:#fde68a;margin-top:0.75rem;">Feature not available</h2>' +
        '</div>' +
        '<div style="background:#0f1011;border:1px solid #78350f;border-radius:12px;padding:1rem 1.15rem;font-size:0.88rem;line-height:1.55;color:#d1d5db;">' +
          '<p id="kd402-feature-message" style="margin:0;"></p>' +
        '</div>' +
        '<p style="font-size:0.78rem;color:#9ca3af;margin-top:1rem;line-height:1.5;">' +
          'Ask your platform administrator to enable this feature or upgrade your plan.' +
        '</p>' +
        '<div style="display:flex;gap:0.6rem;margin-top:1.5rem;">' +
          '<a id="kd402-feature-mail" href="#" style="flex:1;text-align:center;background:#334155;color:#e5e7eb;padding:0.7rem;border-radius:10px;text-decoration:none;font-size:0.85rem;font-weight:500;">Contact support</a>' +
          '<button id="kd402-feature-close" style="flex:1;background:#0e7490;color:#fff;padding:0.7rem;border-radius:10px;border:none;font-size:0.85rem;font-weight:600;cursor:pointer;">Dismiss</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(el);

    el.querySelector('#kd402-feature-close').addEventListener('click', function () {
      var key = el.getAttribute('data-feature-key');
      markDismissed(key);
      el.style.display = 'none';
      el.removeAttribute('data-feature-key');
      currentFeatureKey = null;

      var next;
      while ((next = featureQueue.shift())) {
        if (!isDismissed(next.dedupKey)) {
          renderFeatureModal(el, next.dedupKey, next.detail);
          return;
        }
      }
    });

    featureModal = el;
    return el;
  }

  function renderFeatureModal(el, dedupKey, detail) {
    currentFeatureKey = dedupKey;
    el.setAttribute('data-feature-key', dedupKey);

    el.querySelector('#kd402-feature-message').textContent =
      detail || 'This feature is not enabled for your organisation.';

    var featureName = '';
    var m = /Feature '([^']+)'/.exec(detail || '');
    if (m) {
      featureName = m[1];
    } else {
      var m2 = /None of (\[[^\]]+\])/.exec(detail || '');
      if (m2) featureName = m2[1];
      else featureName = (detail || 'Feature access').slice(0, 60);
    }

    var mail = el.querySelector('#kd402-feature-mail');
    mail.href = 'mailto:' + SUPPORT_EMAIL
      + '?subject=' + encodeURIComponent('Feature access request')
      + '&body=' + encodeURIComponent(
          'Feature: ' + featureName + '\n'
          + 'Organisation: ' + (readSelectedOrgName() || '') + '\n\n'
          + 'Request:\n'
        );

    el.style.display = 'flex';
  }

  function showFeatureRequired(detail) {
    var dedupKey = detail || '__generic__';
    if (isDismissed(dedupKey)) return;

    var el = ensureFeatureModal();
    if (el.style.display === 'flex' && currentFeatureKey === dedupKey) return;

    if (el.style.display === 'flex') {
      for (var i = 0; i < featureQueue.length; i++) {
        if (featureQueue[i].dedupKey === dedupKey) return;
      }
      featureQueue.push({ dedupKey: dedupKey, detail: detail });
      return;
    }

    renderFeatureModal(el, dedupKey, detail);
  }

  // ─── Fetch wrapper ───
  var origFetch = window.fetch;

  function isApiCall(url) {
    var target = typeof url === 'string' ? url : (url && url.url) || '';
    if (!target) return false;
    if (target.indexOf(API_BASE) === 0) return true;
    try {
      if (target.indexOf(window.location.origin) === 0) return true;
    } catch (e) {}
    // Relative URL starting with a single slash
    if (target.charAt(0) === '/' && target.charAt(1) !== '/') return true;
    return false;
  }

  function normalizeHeaders(h) {
    if (!h) return {};
    if (typeof Headers !== 'undefined' && h instanceof Headers) {
      var out = {};
      h.forEach(function (v, k) { out[k] = v; });
      return out;
    }
    if (Array.isArray(h)) {
      var out2 = {};
      h.forEach(function (pair) { out2[pair[0]] = pair[1]; });
      return out2;
    }
    return h;
  }

  function hasHeader(h, name) {
    var lc = name.toLowerCase();
    for (var k in h) {
      if (k.toLowerCase() === lc) return true;
    }
    return false;
  }

  // Cooldown so a persistently-broken selection doesn't spin the picker
  // in an infinite loop.
  var lastSessionErrorAt = 0;
  var SESSION_ERROR_COOLDOWN_MS = 3000;

  function dispatchSessionError(scope, message) {
    var now = Date.now();
    if (now - lastSessionErrorAt < SESSION_ERROR_COOLDOWN_MS) return;
    lastSessionErrorAt = now;

    if (scope === 'org') {
      clearSelectedOrg();
      clearSelectedBranch();
    } else if (scope === 'branch') {
      clearSelectedBranch();
    }

    try {
      window.dispatchEvent(new CustomEvent('kd:branch-error', {
        detail: { scope: scope, message: message }
      }));
    } catch (e) {}
  }

  window.fetch = async function (url, opts) {
    opts = opts || {};
    var apiCall = isApiCall(url);

    if (apiCall) {
      opts.headers = normalizeHeaders(opts.headers);

      // Org header
      if (!hasHeader(opts.headers, 'x-selected-org-id')) {
        var orgId = readSelectedOrg();
        if (orgId) opts.headers['X-Selected-Org-Id'] = orgId;
      }

      // Branch header — skip when '__all__' because the backend treats
      // absence as "all branches for owners". Sending it as a literal
      // string would 403.
      if (!hasHeader(opts.headers, 'x-selected-branch-id')) {
        var branchId = readSelectedBranch();
        if (branchId && branchId !== ALL_BRANCHES) {
          opts.headers['X-Selected-Branch-Id'] = branchId;
        }
      }
    }

    var res = await origFetch.call(this, url, opts);

    if (!apiCall) return res;

    if (res.status === 402) {
      try {
        var clone = res.clone();
        var body = await clone.json();
        var detail = (body && (body.detail || body.message)) || '';
        if (/suspend/i.test(detail)) {
          showSuspended(detail);
        } else {
          showFeatureRequired(detail);
        }
      } catch (e) {
        showFeatureRequired('');
      }
    } else if (res.status === 400) {
      try {
        var c400 = res.clone();
        var b400 = await c400.json();
        var d400 = (b400 && (b400.detail || b400.message)) || '';
        if (/multiple branches/i.test(d400)) {
          dispatchSessionError('branch', d400);
        }
      } catch (e) {}
    } else if (res.status === 403) {
      try {
        var c403 = res.clone();
        var b403 = await c403.json();
        var d403 = (b403 && (b403.detail || b403.message)) || '';
        if (/member of the selected branch/i.test(d403)) {
          dispatchSessionError('branch', d403);
        } else if (/not a member of the requested organisation/i.test(d403)) {
          dispatchSessionError('org', d403);
        }
      } catch (e) {}
    } else if (res.status >= 200 && res.status < 300) {
      hideSuspended();
    }

    return res;
  };

  // ─── Public API ───
  window.KD402 = {
    // Org / branch state (single source of truth for kdsession.js)
    ALL_BRANCHES:          ALL_BRANCHES,
    readSelectedOrg:       readSelectedOrg,
    readSelectedOrgName:   readSelectedOrgName,
    writeSelectedOrg:      writeSelectedOrg,
    clearSelectedOrg:      clearSelectedOrg,
    readSelectedBranch:    readSelectedBranch,
    readSelectedBranchName: readSelectedBranchName,
    writeSelectedBranch:   writeSelectedBranch,
    clearSelectedBranch:   clearSelectedBranch,

    // Suspended / feature modals
    showSuspended:       showSuspended,
    hideSuspended:       hideSuspended,
    showFeatureRequired: showFeatureRequired,
    SUPPORT_EMAIL:       SUPPORT_EMAIL,

    // Debugging
    clearDismissed: function () {
      dismissedFeatures = {};
      try { sessionStorage.removeItem(DISMISSED_KEY); } catch (e) {}
    },
    state: function () {
      return {
        org:       readSelectedOrg(),
        orgName:   readSelectedOrgName(),
        branch:    readSelectedBranch(),
        branchName: readSelectedBranchName(),
        dismissed: Object.keys(dismissedFeatures),
        queue:     featureQueue.map(function (q) { return q.dedupKey.slice(0, 60); }),
        current:   currentFeatureKey
      };
    }
  };
})();
