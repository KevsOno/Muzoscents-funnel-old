// kdsession.js — session-scoped state: active org, active branch, pickers.
// Loaded blocking in <head>, immediately after kdint.js.
//
// The contract with the rest of the app:
//
//   const session = await KD.session.ensure({ requireBranch: true });
//   if (!session) { window.location.href = '/kdsiginin'; return; }
//   // session.orgId, session.branchId, session.branches, session.user ...
//
// ensure() handles every bootstrap case:
//   * no token                 → resolves null (page redirects)
//   * no org stored            → shows org picker
//   * org stored, no branch    → shows branch picker (if requireBranch)
//   * owner with no branch     → resolves branchId = null ('all branches')
//   * non-owner single branch  → auto-selects silently
//   * stale selection          → cleared by kdint.js, ensure() reprompts
//
// Anything that needs to run after a switch can subscribe via
//   KD.session.onChange(function (session) { /* re-fetch */ });
//
// Org pickers, branch pickers, and switcher UI all live here. Pages that
// don't call ensure() are unaffected — kdint.js still injects headers.
(function () {
  'use strict';

  if (!window.KD402) {
    console.warn('[kdsession] kdint.js must load before kdsession.js');
    return;
  }

  var K = window.KD402;
  var API_BASE     = 'https://kevsono-kevs-digital-bos.hf.space';
  var ALL_BRANCHES = K.ALL_BRANCHES;

  // ─── Internal state ───
  var currentSession = null;
  var changeListeners = [];
  var bootstrapping = false;

  // ─── Helpers ───
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function getToken() {
    try {
      return localStorage.getItem('access_token') || localStorage.getItem('pf_auth_token') || null;
    } catch (e) { return null; }
  }

  async function fetchJson(path, opts) {
    opts = opts || {};
    opts.headers = opts.headers || {};
    if (!opts.headers['Content-Type'] && opts.body) {
      opts.headers['Content-Type'] = 'application/json';
    }
    var token = getToken();
    if (token) opts.headers['Authorization'] = 'Bearer ' + token;
    var res = await fetch(API_BASE + path, opts);
    var body = null;
    try { body = await res.json(); } catch (e) {}
    if (!res.ok) {
      var err = new Error((body && (body.detail || body.message)) || ('HTTP ' + res.status));
      err.status = res.status;
      err.body = body;
      throw err;
    }
    return body;
  }

  // ─── Modal scaffolding ───
  var orgModal = null;
  var branchModal = null;

  function ensureOrgModal() {
    if (orgModal) return orgModal;
    var el = document.createElement('div');
    el.id = 'kdsession-org-modal';
    el.style.cssText = [
      'position:fixed', 'inset:0', 'z-index:2147483645',
      'background:rgba(0,0,0,0.88)', 'backdrop-filter:blur(6px)',
      'display:none', 'align-items:center', 'justify-content:center',
      'padding:1.5rem'
    ].join(';');
    el.innerHTML =
      '<div style="max-width:560px;width:100%;background:#0f172a;border:1px solid #1e3a5f;border-radius:20px;padding:2rem;box-shadow:0 24px 60px rgba(0,0,0,0.6);font-family:Inter,system-ui,-apple-system,sans-serif;color:#e5e7eb;max-height:90vh;overflow-y:auto;">' +
        '<div style="text-align:center;margin-bottom:1.25rem;">' +
          '<div style="font-size:2.4rem;line-height:1;">\uD83C\uDFE2</div>' +
          '<h2 style="font-size:1.35rem;font-weight:700;color:#bfdbfe;margin-top:0.6rem;">Select organisation</h2>' +
          '<p style="font-size:0.85rem;color:#93c5fd;margin-top:0.35rem;">You belong to more than one organisation. Pick one to continue.</p>' +
        '</div>' +
        '<div id="kdsession-org-list" style="display:flex;flex-direction:column;gap:0.5rem;"></div>' +
        '<div style="display:flex;justify-content:flex-end;margin-top:1.5rem;">' +
          '<button id="kdsession-org-cancel" style="background:#334155;color:#e5e7eb;border:none;padding:0.6rem 1.1rem;border-radius:10px;font-size:0.85rem;cursor:pointer;">Cancel</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(el);
    orgModal = el;
    return el;
  }

  function ensureBranchModal() {
    if (branchModal) return branchModal;
    var el = document.createElement('div');
    el.id = 'kdsession-branch-modal';
    el.style.cssText = [
      'position:fixed', 'inset:0', 'z-index:2147483645',
      'background:rgba(0,0,0,0.88)', 'backdrop-filter:blur(6px)',
      'display:none', 'align-items:center', 'justify-content:center',
      'padding:1.5rem'
    ].join(';');
    el.innerHTML =
      '<div style="max-width:560px;width:100%;background:#0f172a;border:1px solid #1e4d3a;border-radius:20px;padding:2rem;box-shadow:0 24px 60px rgba(0,0,0,0.6);font-family:Inter,system-ui,-apple-system,sans-serif;color:#e5e7eb;max-height:90vh;overflow-y:auto;">' +
        '<div style="text-align:center;margin-bottom:1.25rem;">' +
          '<div style="font-size:2.4rem;line-height:1;">\uD83C\uDFEC</div>' +
          '<h2 style="font-size:1.35rem;font-weight:700;color:#a7f3d0;margin-top:0.6rem;">Select branch</h2>' +
          '<p id="kdsession-branch-intro" style="font-size:0.85rem;color:#6ee7b7;margin-top:0.35rem;">You have access to multiple branches. Pick one to continue.</p>' +
        '</div>' +
        '<div id="kdsession-branch-list" style="display:flex;flex-direction:column;gap:0.5rem;"></div>' +
        '<div style="display:flex;justify-content:flex-end;margin-top:1.5rem;">' +
          '<button id="kdsession-branch-cancel" style="background:#334155;color:#e5e7eb;border:none;padding:0.6rem 1.1rem;border-radius:10px;font-size:0.85rem;cursor:pointer;">Cancel</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(el);
    branchModal = el;
    return el;
  }

  function pickerButton(label, subtext, badge, accent) {
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.style.cssText =
      'text-align:left;background:#0b1220;color:#e5e7eb;' +
      'border:1px solid #1e3a5f;border-radius:12px;' +
      'padding:0.85rem 1rem;font-size:0.9rem;font-weight:500;cursor:pointer;' +
      'display:flex;justify-content:space-between;align-items:center;gap:0.75rem;';
    btn.onmouseenter = function () { btn.style.background = '#1e293b'; };
    btn.onmouseleave = function () { btn.style.background = '#0b1220'; };

    var left = document.createElement('div');
    var title = document.createElement('div');
    title.textContent = label;
    title.style.fontWeight = '600';
    left.appendChild(title);
    if (subtext) {
      var sub = document.createElement('div');
      sub.textContent = subtext;
      sub.style.fontSize = '0.75rem';
      sub.style.color = '#94a3b8';
      sub.style.marginTop = '0.15rem';
      left.appendChild(sub);
    }
    btn.appendChild(left);

    if (badge) {
      var b = document.createElement('span');
      b.textContent = badge;
      b.style.cssText =
        'background:' + (accent || '#1e3a5f') + ';color:#e5e7eb;' +
        'font-size:0.7rem;padding:0.15rem 0.55rem;border-radius:999px;font-weight:500;';
      btn.appendChild(b);
    }
    return btn;
  }

  // ─── Pickers ───
  // Both resolve with the picked item, or null if the user cancels.

  function promptOrgPicker(orgs, currentOrgId) {
    return new Promise(function (resolve) {
      var el = ensureOrgModal();
      var list = el.querySelector('#kdsession-org-list');
      list.innerHTML = '';

      if (!orgs || orgs.length === 0) {
        list.innerHTML =
          '<div style="text-align:center;padding:1.5rem;color:#94a3b8;">' +
            'You are not a member of any organisation.' +
          '</div>';
      } else {
        orgs.forEach(function (o) {
          var isCurrent = currentOrgId && o.id === currentOrgId;
          var btn = pickerButton(
            o.org_name || o.name || ('Org ' + o.id.slice(0, 8)),
            (o.role || 'member') + (o.status && o.status !== 'active' ? ' \u00B7 ' + o.status : ''),
            isCurrent ? 'current' : null,
            isCurrent ? '#16a34a' : '#1e3a5f'
          );
          btn.onclick = function () { close(null, o); };
          list.appendChild(btn);
        });
      }

      var cancelBtn = el.querySelector('#kdsession-org-cancel');
      cancelBtn.onclick = function () { close(null, null); };

      el.style.display = 'flex';

      function close(ev, picked) {
        el.style.display = 'none';
        document.removeEventListener('keydown', onKey);
        resolve(picked);
      }
      function onKey(e) {
        if (e.key === 'Escape') close(null, null);
      }
      document.addEventListener('keydown', onKey);
    });
  }

  function promptBranchPicker(branches, currentBranchId, allowAllForOwner) {
    return new Promise(function (resolve) {
      var el = ensureBranchModal();
      var list = el.querySelector('#kdsession-branch-list');
      var intro = el.querySelector('#kdsession-branch-intro');
      list.innerHTML = '';

      intro.textContent = allowAllForOwner
        ? 'Pick a specific branch, or continue with access to every branch.'
        : 'You have access to multiple branches. Pick one to continue.';

      if (allowAllForOwner) {
        var allBtn = pickerButton(
          'All branches',
          'See and manage every branch in this organisation',
          currentBranchId === null ? 'current' : null,
          currentBranchId === null ? '#16a34a' : '#1e4d3a'
        );
        allBtn.onclick = function () {
          close(null, { id: ALL_BRANCHES, name: 'All branches' });
        };
        list.appendChild(allBtn);
      }

      (branches || []).forEach(function (b) {
        var isCurrent = b.id === currentBranchId;
        var btn = pickerButton(
          b.name || ('Branch ' + b.id.slice(0, 8)),
          b.code ? 'Code: ' + b.code : null,
          b.is_default ? 'default' : (isCurrent ? 'current' : null),
          isCurrent ? '#16a34a' : (b.is_default ? '#1e4d3a' : null)
        );
        btn.onclick = function () { close(null, { id: b.id, name: b.name || b.code || b.id }); };
        list.appendChild(btn);
      });

      var cancelBtn = el.querySelector('#kdsession-branch-cancel');
      cancelBtn.onclick = function () { close(null, null); };

      el.style.display = 'flex';

      function close(ev, picked) {
        el.style.display = 'none';
        document.removeEventListener('keydown', onKey);
        resolve(picked);
      }
      function onKey(e) {
        if (e.key === 'Escape') close(null, null);
      }
      document.addEventListener('keydown', onKey);
    });
  }

  // ─── Bootstrap: the one entry point ───
  async function ensure(opts) {
    opts = opts || {};
    var requireBranch = opts.requireBranch !== false;
    var force = opts.force === true;

    bootstrapping = true;
    try {
      // 1. Token check
      if (!getToken()) {
        return null;
      }

      // 2. Resolve org
      var orgId = force ? null : K.readSelectedOrg();
      if (!orgId) {
        var orgs = await fetchOrgs();
        if (!orgs || orgs.length === 0) {
          // No memberships at all. Surface a picker that shows the
          // empty state — the user cannot proceed.
          await promptOrgPicker([], null);
          return null;
        }
        if (orgs.length === 1) {
          // Only one org — no need to ask.
          K.writeSelectedOrg(orgs[0].id, orgs[0].org_name || orgs[0].name);
          orgId = orgs[0].id;
        } else {
          var picked = await promptOrgPicker(orgs, null);
          if (!picked) return null;
          K.writeSelectedOrg(picked.id, picked.org_name || picked.name);
          K.clearSelectedBranch();  // branch from a different org is meaningless
          orgId = picked.id;
        }
      }

      // 3. Fetch /auth/me to resolve branch state. If the stored org is
      //    stale (user removed from org), /auth/me 403s; retry with
      //    org picker.
      var me;
      try {
        me = await fetchJson('/auth/me');
      } catch (err) {
        if (err.status === 403) {
          K.clearSelectedOrg();
          K.clearSelectedBranch();
          var orgs2 = await fetchOrgs();
          if (!orgs2 || orgs2.length === 0) {
            await promptOrgPicker([], null);
            return null;
          }
          var picked2 = orgs2.length === 1 ? orgs2[0] : await promptOrgPicker(orgs2, null);
          if (!picked2) return null;
          K.writeSelectedOrg(picked2.id, picked2.org_name || picked2.name);
          me = await fetchJson('/auth/me');
          orgId = picked2.id;
        } else {
          throw err;
        }
      }

      // 4. Resolve branch
      var branches = me.branches || [];
      var isOwner  = !!me.is_owner;
      var validIds = branches.map(function (b) { return b.id; });

      var storedBranchId   = K.readSelectedBranch();
      var storedBranchName = K.readSelectedBranchName();
      var branchId   = null;
      var branchName = null;

      if (isOwner) {
        // Owner: absence of header = all branches. Can also pick a
        // specific one if they stored it.
        if (!storedBranchId || storedBranchId === ALL_BRANCHES) {
          branchId = null;
          branchName = 'All branches';
        } else if (validIds.indexOf(storedBranchId) >= 0) {
          branchId = storedBranchId;
          branchName = findBranchName(branches, storedBranchId) || storedBranchName || '';
        } else {
          // Stored branch no longer exists
          K.clearSelectedBranch();
          branchId = null;
          branchName = 'All branches';
        }
      } else {
        // Non-owner
        if (me.current_branch_id) {
          // Backend resolved it (single branch, or default fallback)
          branchId = me.current_branch_id;
          branchName = findBranchName(branches, branchId) || '';
          K.writeSelectedBranch(branchId, branchName);
        } else if (me.requires_branch_selection) {
          // Must pick
          if (!requireBranch) {
            // Page explicitly opted out of the requirement
            branchId = null;
            branchName = null;
          } else if (storedBranchId && validIds.indexOf(storedBranchId) >= 0) {
            // Valid pick already stored — use it
            branchId = storedBranchId;
            branchName = findBranchName(branches, storedBranchId) || storedBranchName || '';
          } else {
            // Show picker
            var pickedBranch = await promptBranchPicker(branches, storedBranchId, false);
            if (!pickedBranch) return null;  // user cancelled
            branchId = pickedBranch.id;
            branchName = pickedBranch.name;
            K.writeSelectedBranch(branchId, branchName);
          }
        } else {
          // No branch needed (edge case — single-team fallback failed)
          branchId = null;
          branchName = null;
        }
      }

      var session = {
        orgId:      orgId,
        orgName:    K.readSelectedOrgName() || '',
        role:       me.role,
        isOwner:    isOwner,
        branchId:   branchId,
        branchName: branchName,
        branches:   branches,
        user:       me
      };
      currentSession = session;
      return session;

    } catch (err) {
      console.error('[kdsession] ensure() failed', err);
      throw err;
    } finally {
      bootstrapping = false;
    }
  }

  function findBranchName(branches, id) {
    for (var i = 0; i < branches.length; i++) {
      if (branches[i].id === id) return branches[i].name || branches[i].code || '';
    }
    return null;
  }

  async function fetchOrgs() {
    // Primary: /auth/my-orgs — returns {orgs: [{id, org_name, role, slug, status}]}
    try {
      var data = await fetchJson('/auth/my-orgs');
      var list = (data && (data.orgs || data.organisations)) || [];
      if (list.length) return list.map(function (o) {
        return {
          id: o.id || o.org_id,
          org_name: o.org_name || o.name,
          role: o.role,
          status: o.status
        };
      });
    } catch (e) { /* fall through */ }

    // Fallback: /auth/me + /auth/org for the single-org case
    try {
      var me = await fetchJson('/auth/me');
      if (me && me.org_id) {
        var name = null;
        try {
          var o = await fetchJson('/auth/org');
          name = o && o.org_name;
        } catch (e) {}
        return [{
          id: me.org_id,
          org_name: name || ('Org ' + me.org_id.slice(0, 8)),
          role: me.role
        }];
      }
    } catch (e) { /* fall through */ }

    return [];
  }

  // ─── Public switch ───
  //
  // Cancel-safe: if the user dismisses the picker (or ensure() throws),
  // the previous selection is restored so the still-mounted page does
  // not end up firing unscoped requests after a cancelled switch.
  //
  // Resolves:
  //   * the new session on success
  //   * null on user cancel (previous selection restored)
  //   * throws if ensure() fails (previous selection restored)
  async function switchSession(opts) {
    var prevOrgId    = K.readSelectedOrg();
    var prevOrgName  = K.readSelectedOrgName();
    var prevBranchId = K.readSelectedBranch();
    var prevBranchNm = K.readSelectedBranchName();

    K.clearSelectedOrg();
    K.clearSelectedBranch();

    var next;
    try {
      next = await ensure(Object.assign({ force: true }, opts || {}));
    } catch (err) {
      K.writeSelectedOrg(prevOrgId, prevOrgName);
      K.writeSelectedBranch(prevBranchId, prevBranchNm);
      throw err;
    }

    if (next) {
      emitChange(next);
      return next;
    }

    // User cancelled the picker — restore and return null.
    K.writeSelectedOrg(prevOrgId, prevOrgName);
    K.writeSelectedBranch(prevBranchId, prevBranchNm);
    return null;
  }

  // ─── Subscription ───
  function onChange(cb) {
    if (typeof cb === 'function') changeListeners.push(cb);
    return function () {
      var i = changeListeners.indexOf(cb);
      if (i >= 0) changeListeners.splice(i, 1);
    };
  }

  function emitChange(session) {
    changeListeners.forEach(function (cb) {
      try { cb(session); } catch (e) {
        console.error('[kdsession] onChange listener threw', e);
      }
    });
  }

  // ─── Auto-recovery from kdint.js branch errors ───
  // When kdint.js sees a 400 "Multiple branches" or a 403 branch/org
  // mismatch, it clears the stale selection and dispatches this event.
  // If we're already bootstrapped, recover by re-running ensure() with
  // the appropriate scope.
  window.addEventListener('kd:branch-error', async function (e) {
    var scope = (e && e.detail && e.detail.scope) || 'branch';
    console.warn('[kdsession] recovering from branch error', scope);

    if (bootstrapping) {
      // ensure() is in-flight; it will handle the empty selection.
      return;
    }

    try {
      if (scope === 'org') {
        // Both org and branch were cleared by kdint.js — full re-bootstrap
        var s = await ensure({ requireBranch: true, force: true });
        if (s) emitChange(s);
      } else {
        // Branch only — re-run ensure(), which will prompt if needed
        var s2 = await ensure({ requireBranch: true });
        if (s2) emitChange(s2);
      }
    } catch (err) {
      console.error('[kdsession] branch-error recovery failed', err);
    }
  });

  // ─── Public API ───
  window.KD = window.KD || {};
  window.KD.session = {
    ensure:   ensure,
    switch:   switchSession,
    onChange: onChange,
    current:  function () { return currentSession; },
    getToken: getToken
  };

  // Expose branch name lookup for callers that want to format "Org · Branch"
  window.KD.session.branchLabel = function (session) {
    if (!session) return '';
    if (!session.branchId) return session.isOwner ? 'All branches' : '';
    return session.branchName || session.branchId;
  };
})();
