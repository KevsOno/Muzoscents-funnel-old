// nav.js — shared navbar for every Kevs bOS page + native lockdown.
// Served at /nav.js from the repo root. Loaded by every internal page:
//   <div id="kevs-nav-container"></div>
//   <script src="/nav.js" defer></script>
//
// When running inside Tauri (remote-URL mode) this file ALSO:
//   - blocks right-click / context menu
//   - blocks devtools & reload shortcuts (F12, Ctrl+R, Ctrl+Shift+I, ...)
//   - blocks Ctrl+W (close window) and Ctrl+P on POS pages
//   - blocks Ctrl+wheel zoom
//   - opens external links in the system browser instead of navigating the webview away
//   - auto-logouts after 15 min idle (60s warning)
//
// In a normal browser none of the lockdown runs. Add ?lockdown=1 to test it.
//
// NAVBAR LAYOUT (v2): on desktop (md+) the bar is a single slim row (~44px).
// Only the current page shows its label; the other items are icon-only and
// reveal their name in a tooltip on hover/focus. On mobile the original
// scrollable icon+label strip is kept.
(function () {
    'use strict';

    const APP_NAME   = 'Kd<span class="text-orange-500">bOS</span>';
    const LOGIN_URL  = '/kdsiginin';
    const API_BASE   = 'https://kevsono-kevs-digital-bos.hf.space';

    // ---------- runtime flags ----------
    const IS_TAURI   = !!(window.__TAURI_INTERNALS__ || window.__TAURI__);
    const FORCE_LOCK = new URLSearchParams(location.search).has('lockdown');
    const LOCKDOWN   = IS_TAURI || FORCE_LOCK;

    const IDLE_MS    = 15 * 60 * 1000;   // 15 min idle → logout
    const IDLE_WARN  = 60 * 1000;        // warning 60s before
    // Ctrl+P is blocked only on pages that print programmatically.
    // Add paths here if other pages also print via window.print().
    const CTRL_P_BLOCKED_ON = ['/kdpos'];

    const navItems = [
        { path: '/kdbi',          name: 'Strategy',   icon: 'fa-chart-line',    title: 'Marketing metrics, leads & AI strategy',                 roles: ['owner','admin','sales_rep','finance'] },
        { path: '/kdpos',         name: 'POS',         icon: 'fa-cash-register', title: 'Multi‑tab sales, SKU search & online payments',         roles: ['owner','admin','sales_rep'] },
        { path: '/kdfulfillment', name: 'Fulfillment', icon: 'fa-truck-fast',    title: 'Order shipping, tracking & dispatch',                    roles: ['owner','admin','logistics'] },
        { path: '/kdsupport',     name: 'Support',     icon: 'fa-headset',       title: 'Ticket management & customer context',                   roles: ['owner','admin','support'] },
        { path: '/kddashboard',   name: 'Exec. Dash.', icon: 'fa-chart-simple',  title: 'Executive revenue & profit overview',                    roles: ['owner','admin','finance'] },
        { path: '/kdadmin',       name: 'Inventory',   icon: 'fa-boxes',         title: 'Manage products, stock, bulk CSV upload',                roles: ['owner','admin','inventory_manager','warehouse'] },
        { path: '/kdteam',        name: 'Team',        icon: 'fa-users',         title: 'Invite & manage team members',                           roles: ['owner','admin'] },
        { path: '/kdknowledge',   name: 'Knowledge',   icon: 'fa-database',      title: 'Manage AI knowledge base documents',                     roles: ['owner','admin'] },
        { path: '/kdprocurement', name: 'Procurement', icon: 'fa-truck',         title: 'Manage suppliers, purchase orders, and goods received',  roles: ['owner','admin','inventory_manager','procurement','warehouse'] },
        { path: '/kdhr',          name: 'HR',          icon: 'fa-users-gear',    title: 'Employee management, attendance, leave, payroll',        roles: ['owner','admin','hr','employee'] },
        { path: '/kdaccount',     name: 'Accounts',    icon: 'fa-book',          title: 'Chart of accounts, journal entries, AR/AP, P&L, export', roles: ['owner','admin','finance','auditor'] },
        { path: '/kdstorefront',  name: 'Storefront',  icon: 'fa-store',         title: 'Edit your public storefront — branding, theme, SEO',     roles: ['owner','admin'] }
    ];

    function esc(s) {
        if (s == null) return '';
        return String(s).replace(/[&<>"']/g, c =>
            ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
    }

    function getUserRole() {
        try { return localStorage.getItem('user_role') || 'customer'; }
        catch (e) { return 'customer'; }
    }

    // Small stylesheet for the compact desktop nav (tooltips need pseudo-elements,
    // which Tailwind utility classes can't express). Injected once.
    function injectNavStyles() {
        if (document.getElementById('kevs-nav-style')) return;
        const st = document.createElement('style');
        st.id = 'kevs-nav-style';
        st.textContent =
            '.kn-link{position:relative;display:inline-flex;align-items:center;justify-content:center;gap:8px;' +
                'height:36px;min-width:36px;padding:0 10px;border-radius:8px;font-size:14px;font-weight:500;' +
                'color:rgba(255,255,255,.8);transition:background .15s,color .15s;white-space:nowrap;text-decoration:none;}' +
            '.kn-link:hover,.kn-link:focus-visible{background:rgba(255,255,255,.12);color:#fff;outline:none;}' +
            '.kn-link.kn-active{background:rgba(255,255,255,.2);color:#fff;}' +
            '.kn-link:not(.kn-active) .kn-label{display:none;}' +
            '.kn-link:not(.kn-active)::after{content:attr(data-label);position:absolute;top:100%;left:50%;' +
                'transform:translateX(-50%);margin-top:8px;background:#0f172a;color:#fff;font-size:12px;' +
                'line-height:1;padding:6px 9px;border-radius:6px;white-space:nowrap;opacity:0;' +
                'pointer-events:none;transition:opacity .12s;z-index:60;box-shadow:0 4px 12px rgba(0,0,0,.3);}' +
            '.kn-link:not(.kn-active):hover::after,.kn-link:not(.kn-active):focus-visible::after{opacity:1;}';
        document.head.appendChild(st);
    }

    function buildNavbar() {
        const currentPath = window.location.pathname;
        const role = getUserRole();
        let desktopLinks = '';
        let mobileLinks = '';
        navItems.forEach(item => {
            if (!item.roles.includes(role)) return;
            const isActive = currentPath === item.path;

            // Desktop: compact — label only on the active page, tooltip for the rest.
            desktopLinks += `<a href="${item.path}" data-label="${esc(item.name)}" aria-label="${esc(item.name)}"` +
                ` class="kn-link${isActive ? ' kn-active' : ''}"${isActive ? ' aria-current="page"' : ''}>` +
                `<i class="fa-solid ${item.icon}"></i><span class="kn-label">${item.name}</span></a>`;

            // Mobile: original scrollable strip with icon + label.
            const activeClass = isActive ? 'bg-white/20 text-white' : 'text-white/80 hover:bg-white/10';
            mobileLinks += `<a href="${item.path}" title="${esc(item.title)}" class="flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition ${activeClass}"><i class="fa-solid ${item.icon} w-4"></i> ${item.name}</a>`;
        });
        let userName = 'User';
        try { userName = localStorage.getItem('user_profile_display') || 'User'; } catch (e) {}
        return `<div class="bg-[#1E3A5F] text-white shadow-md sticky top-0 z-40">
            <div class="max-w-7xl mx-auto px-4 py-1.5 flex items-center justify-between gap-3">
                <a href="/kdbi" class="flex items-center gap-2 shrink-0"><i class="fa-solid fa-chart-pie text-orange-400 text-lg"></i><span class="text-lg font-bold">${APP_NAME}</span></a>
                <div class="hidden md:flex items-center gap-1">${desktopLinks}</div>
                <div class="flex items-center gap-2 shrink-0">
                    <span class="text-xs bg-white/10 px-3 py-1.5 rounded-full"><i class="fa-regular fa-user mr-1"></i> ${esc(userName)}</span>
                    <button id="global-logout-btn" title="Log out" class="bg-red-500/80 hover:bg-red-600 text-white text-sm px-3 py-1.5 rounded-lg transition"><i class="fa-solid fa-sign-out-alt"></i></button>
                </div>
            </div>
            <div class="md:hidden flex overflow-x-auto pb-2 px-4 gap-1">${mobileLinks}</div>
        </div>`;
    }

    async function globalLogout() {
        try {
            const token = localStorage.getItem('access_token');
            await fetch(`${API_BASE}/auth/logout`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` }
            });
        } catch (e) {}
        localStorage.clear();
        window.location.href = LOGIN_URL;
    }

    // ============================================================
    // Native lockdown (Tauri only, or ?lockdown=1 in a browser)
    // ============================================================
    function installLockdown() {
        if (!LOCKDOWN) return;

        // 1) No right-click / context menu
        document.addEventListener('contextmenu', e => e.preventDefault(), true);

        // 2) Prevent drag-drop from navigating the webview to a local file
        ['dragover', 'drop'].forEach(ev =>
            document.addEventListener(ev, e => e.preventDefault(), true));

        // 3) Keyboard shortcut interception
        document.addEventListener('keydown', e => {
            const k     = (e.key || '').toLowerCase();
            const ctrl  = e.ctrlKey || e.metaKey;
            const shift = e.shiftKey;
            const kill  = ev => { ev.preventDefault(); ev.stopPropagation(); };

            // Admin escape hatch: Ctrl+Shift+Alt+R hard-reloads the app
            if (ctrl && shift && e.altKey && k === 'r') { location.reload(); return; }

            // Devtools
            if (k === 'f12') return kill(e);
            if (ctrl && shift && ['i','j','c','k','m'].includes(k)) return kill(e);

            // Reload / view-source / save / devtools aliases / close window
            if (k === 'f5') return kill(e);
            if (ctrl && ['r','s','u','i','j','k','m','w'].includes(k)) return kill(e);

            // Zoom
            if (ctrl && ['+','-','=','0'].includes(k)) return kill(e);

            // Back / forward navigation (Alt+← / Alt+→)
            if (e.altKey && (k === 'arrowleft' || k === 'arrowright')) return kill(e);

            // Ctrl+P only where receipts print via window.print()
            if (ctrl && k === 'p' &&
                CTRL_P_BLOCKED_ON.some(p => location.pathname.startsWith(p))) {
                return kill(e);
            }
        }, true);

        // 4) Ctrl+wheel zoom
        document.addEventListener('wheel', e => {
            if (e.ctrlKey) e.preventDefault();
        }, { passive: false, capture: true });

        // 5) External links → system browser, so the webview never leaves the app.
        //    Requires "opener:allow-open-url" in the capability file.
        document.addEventListener('click', e => {
            const a = e.target && e.target.closest ? e.target.closest('a[href]') : null;
            if (!a) return;
            const href = a.getAttribute('href');
            if (!href || href.startsWith('#') ||
                href.startsWith('javascript:') ||
                href.startsWith('mailto:') || href.startsWith('tel:')) return;
            let url; try { url = new URL(href, location.href); } catch (_) { return; }
            if (url.origin === location.origin) return; // internal — let it navigate
            e.preventDefault();
            const invoke = window.__TAURI_INTERNALS__ && window.__TAURI_INTERNALS__.invoke;
            if (invoke) {
                invoke('plugin:opener|open_url', { url: url.href }).catch(() => {});
            } else {
                window.open(url.href, '_blank', 'noopener');
            }
        }, true);
    }

    // ============================================================
    // Idle auto-logout (Tauri only / ?lockdown=1)
    // ============================================================
    function installIdleLogout() {
        if (!LOCKDOWN) return;
        if (!document.getElementById('kevs-nav-container')) return;
        try { if (!localStorage.getItem('access_token')) return; } catch (_) { return; }

        let warnTimer = null, logoutTimer = null, countTimer = null;
        let overlay = null;

        const clearTimers = () => {
            clearTimeout(warnTimer); clearTimeout(logoutTimer); clearInterval(countTimer);
            warnTimer = logoutTimer = countTimer = null;
        };
        const removeOverlay = () => { if (overlay) { overlay.remove(); overlay = null; } };

        const doLogout = () => {
            clearTimers(); removeOverlay();
            try { localStorage.clear(); } catch (_) {}
            location.href = LOGIN_URL + '?reason=idle';
        };

        const showWarning = () => {
            let left = Math.ceil(IDLE_WARN / 1000);
            overlay = document.createElement('div');
            overlay.id = 'kevs-idle-overlay';
            overlay.style.cssText =
                'position:fixed;inset:0;background:rgba(15,23,42,.55);z-index:99999;' +
                'display:flex;align-items:center;justify-content:center;font-family:system-ui,sans-serif;';
            overlay.innerHTML =
                '<div style="background:#fff;border-radius:12px;padding:24px 28px;max-width:380px;' +
                'box-shadow:0 20px 60px rgba(0,0,0,.3);text-align:center;">' +
                '<div style="font-size:18px;font-weight:700;color:#1E3A5F;margin-bottom:8px;">' +
                'Session about to expire</div>' +
                '<div style="font-size:14px;color:#475569;margin-bottom:16px;">' +
                'Logging out in <b id="kevs-idle-count">' + left + '</b>s.</div>' +
                '<button id="kevs-idle-stay" style="background:#1E3A5F;color:#fff;border:0;' +
                'border-radius:8px;padding:10px 16px;font-size:14px;cursor:pointer;">' +
                'Stay logged in</button></div>';
            document.body.appendChild(overlay);
            const btn = document.getElementById('kevs-idle-stay');
            if (btn) btn.onclick = () => { removeOverlay(); schedule(); };

            countTimer = setInterval(() => {
                left--;
                const n = document.getElementById('kevs-idle-count');
                if (n) n.textContent = left;
                if (left <= 0) { clearInterval(countTimer); countTimer = null; }
            }, 1000);
        };

        const schedule = () => {
            clearTimers();
            warnTimer = setTimeout(showWarning, IDLE_MS - IDLE_WARN);
            logoutTimer = setTimeout(doLogout, IDLE_MS);
        };

        const reset = () => {
            if (overlay) removeOverlay();
            clearInterval(countTimer); countTimer = null;
            schedule();
        };

        // Scanner keystrokes count as activity — correct for POS.
        ['mousemove','mousedown','keydown','touchstart','scroll','wheel','focus']
            .forEach(ev => window.addEventListener(ev, reset, { passive: true, capture: true }));

        schedule();
    }

    // If user_role is missing (fresh session on a page that hasn't fetched /auth/me yet),
    // pull it once so the correct menu items render.
    async function hydrateRoleIfMissing() {
        if (getUserRole() !== 'customer') return;
        const token = localStorage.getItem('access_token');
        if (!token) return;
        try {
            const res = await fetch(`${API_BASE}/auth/me`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (res.ok) {
                const me = await res.json();
                localStorage.setItem('user_role', me.role || 'admin');
                if (me.display_name || me.email) {
                    localStorage.setItem('user_profile_display', me.display_name || me.email);
                }
            }
        } catch (e) {}
    }

    async function mount() {
        const container = document.getElementById('kevs-nav-container');
        if (!container) return;
        injectNavStyles();
        await hydrateRoleIfMissing();
        container.innerHTML = buildNavbar();
        document.getElementById('global-logout-btn')?.addEventListener('click', globalLogout);
    }

    // Install lockdown as early as possible.
    installLockdown();
    installIdleLogout();

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', mount);
    } else {
        mount();
    }
})();
