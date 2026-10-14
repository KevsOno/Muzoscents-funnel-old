// kdint.js — 402 interceptor for suspended organisations / feature-gated endpoints.
// Must be loaded in <head> BEFORE any other script that calls fetch.
// No defer, no async — the parser must block on this file.
(function () {
  'use strict';

  // ────────────────────────────────────────────────────────────
  // Configuration
  // ────────────────────────────────────────────────────────────
  var API_BASE = 'https://kevsono-kevs-digital-bos.hf.space';
  var SUPPORT_EMAIL = 'support@kevsdigital.com';
  var STORAGE_KEYS_ORG_NAME = ['kd_current_org_name', 'selected_org_name'];
  var STORAGE_KEYS_ORG_ID   = ['kd_current_org', 'selected_org_id'];

  // ────────────────────────────────────────────────────────────
  // Utilities
  // ────────────────────────────────────────────────────────────
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

  // ────────────────────────────────────────────────────────────
  // Modal scaffolding (injected lazily)
  // ────────────────────────────────────────────────────────────
  var suspendedModal = null;
  var featureModal = null;

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
    el.innerHTML = '' +
      '<div style="max-width:520px;width:100%;background:#1a1414;border:1px solid #7f1d1d;border-radius:20px;padding:2rem;box-shadow:0 24px 60px rgba(0,0,0,0.6);font-family:Inter,system-ui,-apple-system,sans-serif;color:#e5e7eb;">' +
        '<div style="text-align:center;margin-bottom:1.25rem;">' +
          '<div style="font-size:3rem;line-height:1;color:#f87171;">⚠</div>' +
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
      window.location.href = '/kdsiginin';
    });

    suspendedModal = el;
    return el;
  }

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
    el.innerHTML = '' +
      '<div style="max-width:480px;width:100%;background:#141a1a;border:1px solid #78350f;border-radius:20px;padding:2rem;box-shadow:0 24px 60px rgba(0,0,0,0.55);font-family:Inter,system-ui,-apple-system,sans-serif;color:#e5e7eb;">' +
        '<div style="text-align:center;margin-bottom:1.25rem;">' +
          '<div style="font-size:3rem;line-height:1;color:#fbbf24;">🔒</div>' +
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
      el.style.display = 'none';
    });

    featureModal = el;
    return el;
  }

  // ────────────────────────────────────────────────────────────
  // Public API
  // ────────────────────────────────────────────────────────────
  function showSuspended(detail) {
    var el = ensureSuspendedModal();
    var orgName = readLocal(STORAGE_KEYS_ORG_NAME) || '(unknown organisation)';
    el.querySelector('#kd402-suspended-org').textContent = orgName;
    el.querySelector('#kd402-suspended-message').textContent =
      detail || 'This organisation has been suspended. All features are disabled until an administrator reactivates it.';
    var mail = el.querySelector('#kd402-suspended-mail');
    mail.href = 'mailto:' + SUPPORT_EMAIL
      + '?subject=' + encodeURIComponent('Suspended organisation: ' + orgName)
      + '&body=' + encodeURIComponent('Organisation: ' + orgName + '\nOrg ID: ' + (readLocal(STORAGE_KEYS_ORG_ID) || '') + '\n\nDescribe the issue:\n');
    el.style.display = 'flex';
  }

  function hideSuspended() {
    if (suspendedModal) suspendedModal.style.display = 'none';
  }

  // De-dupe feature messages so 8 parallel fetches don't stack 8 modals
  var lastFeatureShownAt = 0;
  var lastFeatureKey = '';
  function showFeatureRequired(detail) {
    var el = ensureFeatureModal();

    // Extract a short key from the message so repeat shows of the same
    // missing feature don't re-open the modal within a 3s window.
    var m = /Feature '([^']+)'/.exec(detail || '');
    var key = m ? m[1] : (detail || '').slice(0, 60);
    var now = Date.now();
    var isOpen = el.style.display === 'flex';
    if (isOpen && key === lastFeatureKey && now - lastFeatureShownAt < 3000) {
      return;
    }
    lastFeatureShownAt = now;
    lastFeatureKey = key;

    el.querySelector('#kd402-feature-message').textContent =
      detail || 'This feature is not enabled for your organisation.';
    var mail = el.querySelector('#kd402-feature-mail');
    mail.href = 'mailto:' + SUPPORT_EMAIL
      + '?subject=' + encodeURIComponent('Feature access request')
      + '&body=' + encodeURIComponent('Feature: ' + key + '\nOrganisation: ' + (readLocal(STORAGE_KEYS_ORG_NAME) || '') + '\n\nRequest:\n');
    el.style.display = 'flex';
  }

  // ────────────────────────────────────────────────────────────
  // Fetch interceptor
  // ────────────────────────────────────────────────────────────
  var origFetch = window.fetch;
  window.fetch = async function (url, opts) {
    var res = await origFetch.call(this, url, opts);

    // Only inspect responses from our backend
    var target = typeof url === 'string' ? url : (url && url.url) || '';
    if (target.indexOf(API_BASE) !== 0) return res;

    if (res.status === 402) {
      // Clone before anyone else consumes the body
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
        // Body wasn't JSON, or clone failed. Fall back to a generic
        // feature-required message so at least something is visible.
        showFeatureRequired('');
      }
    } else if (res.status >= 200 && res.status < 300) {
      // A successful request means the org is functional again.
      // Auto-hide the suspended overlay so a reactivated user doesn't
      // stare at a stale screen after a page reload.
      hideSuspended();
    }

    return res;
  };

  // ────────────────────────────────────────────────────────────
  // Expose for advanced use (pages can override behaviour)
  // ────────────────────────────────────────────────────────────
  window.KD402 = {
    showSuspended: showSuspended,
    hideSuspended: hideSuspended,
    showFeatureRequired: showFeatureRequired,
    SUPPORT_EMAIL: SUPPORT_EMAIL
  };
})();
