// nav.js — shared navbar for every Kevs bOS page.
// Usage in any page:
//   <div id="kevs-nav-container"></div>
//   <script src="/nav.js" defer></script>
(function () {
    const APP_NAME   = 'Kevs<span class="text-orange-500">BI</span>';
    const LOGIN_URL  = '/kdsiginin';
    const API_BASE   = 'https://kevsono-kevs-digital-bos.hf.space';

    const navItems = [
        { path: '/kdbi',          name: 'Strategy',   icon: 'fa-chart-line',    title: 'Marketing metrics, leads & AI strategy',                 roles: ['owner','admin','sales_rep','finance'] },
        { path: '/kdpos',         name: 'POS',         icon: 'fa-cash-register', title: 'Multi‑tab sales, SKU search & online payments',         roles: ['owner','admin','sales_rep'] },
        { path: '/kdfulfillment', name: 'Fulfillment', icon: 'fa-truck-fast',    title: 'Order shipping, tracking & dispatch',                    roles: ['owner','admin','logistics'] },
        { path: '/kdsupport',     name: 'Support',     icon: 'fa-headset',       title: 'Ticket management & customer context',                   roles: ['owner','admin','support'] },
        { path: '/kddashboard',   name: 'Exec',        icon: 'fa-chart-simple',  title: 'Executive revenue & profit overview',                    roles: ['owner','admin','finance'] },
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

    function buildNavbar() {
        const currentPath = window.location.pathname;
        let linksHtml = '';
        navItems.forEach(item => {
            if (!item.roles.includes(getUserRole())) return;
            const isActive = currentPath === item.path;
            const activeClass = isActive
                ? 'bg-white/20 text-white'
                : 'text-white/80 hover:bg-white/10';
            linksHtml += `<a href="${item.path}" title="${esc(item.title)}" class="flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition ${activeClass}"><i class="fa-solid ${item.icon} w-4"></i> ${item.name}</a>`;
        });
        let userName = 'User';
        try { userName = localStorage.getItem('user_profile_display') || 'User'; } catch (e) {}
        return `<div class="bg-[#1E3A5F] text-white shadow-md sticky top-0 z-40">
            <div class="max-w-7xl mx-auto px-4 py-3 flex flex-wrap items-center justify-between gap-3">
                <div class="flex items-center gap-2"><i class="fa-solid fa-chart-pie text-orange-400 text-xl"></i><span class="text-xl font-bold">${APP_NAME}</span></div>
                <div class="hidden md:flex items-center gap-1 flex-wrap">${linksHtml}</div>
                <div class="flex items-center gap-3">
                    <span class="text-xs bg-white/10 px-3 py-1.5 rounded-full"><i class="fa-regular fa-user mr-1"></i> ${esc(userName)}</span>
                    <button id="global-logout-btn" class="bg-red-500/80 hover:bg-red-600 text-white text-sm px-3 py-1.5 rounded-lg transition"><i class="fa-solid fa-sign-out-alt"></i></button>
                </div>
            </div>
            <div class="md:hidden flex overflow-x-auto pb-2 px-4 gap-1">${linksHtml}</div>
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
        await hydrateRoleIfMissing();
        container.innerHTML = buildNavbar();
        document.getElementById('global-logout-btn')?.addEventListener('click', globalLogout);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', mount);
    } else {
        mount();
    }
})();
