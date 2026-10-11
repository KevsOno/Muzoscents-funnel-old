const API_BASE = window.location.origin;
let TOKEN = localStorage.getItem('access_token') || '';
let CONFIG = null;         // Full merged config from server
let ORG_META = null;       // { org_name, slug, vertical, published }
let DIRTY = false;

/* ─── helpers ─── */
function $(s) { return document.querySelector(s); }
function $$(s) { return Array.from(document.querySelectorAll(s)); }
function esc(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function toast(msg, kind) {
    const colors = { success: 'bg-emerald-600', error: 'bg-red-600', info: 'bg-blue-600' };
    const el = document.createElement('div');
    el.className = 'fixed bottom-4 right-4 ' + (colors[kind] || colors.info) + ' text-white px-5 py-3 rounded-xl text-sm shadow-2xl z-50';
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 2600);
}
function markDirty() {
    DIRTY = true;
    const btn = $('#btn-save');
    btn.disabled = false;
    $('#save-label').textContent = 'Save changes';
}
function clearDirty() {
    DIRTY = false;
    const btn = $('#btn-save');
    btn.disabled = true;
    $('#save-label').textContent = 'Saved';
    setTimeout(() => { if (!DIRTY) $('#save-label').textContent = 'Save'; }, 1200);
}

/* ─── API ─── */
async function api(path, opts) {
    opts = opts || {};
    opts.headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
    if (TOKEN) opts.headers['Authorization'] = 'Bearer ' + TOKEN;
    const res = await fetch(API_BASE + path, opts);
    if (res.status === 401) {
        localStorage.removeItem('access_token');
        throw new Error('Session expired. Please sign in again.');
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || ('HTTP ' + res.status));
    return data;
}

/* ─── Auth ─── */
async function signin() {
    const email = $('#gate-email').value.trim();
    const password = $('#gate-password').value;
    const err = $('#gate-error');
    err.classList.add('hidden');
    if (!email || !password) { err.textContent = 'Email and password required'; err.classList.remove('hidden'); return; }

    try {
        const res = await fetch(API_BASE + '/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Login failed');
        TOKEN = data.access_token;
        localStorage.setItem('access_token', TOKEN);
        localStorage.setItem('refresh_token', data.refresh_token || '');
        await bootApp();
    } catch (e) {
        err.textContent = e.message;
        err.classList.remove('hidden');
    }
}

/* ─── Boot ─── */
async function bootApp() {
    try {
        const me = await api('/auth/me');
        if (me.role !== 'owner' && me.role !== 'admin') {
            throw new Error('Only owners and admins can edit the storefront.');
        }
        const payload = await api('/storefront/config');
        ORG_META = payload;
        CONFIG = payload.config || {};

        $('#gate').classList.add('hidden');
        $('#app').classList.remove('hidden');

        hydrateForm();
        wireAll();
        updateHeader();
        updatePublishButton();
    } catch (e) {
        $('#gate-error').textContent = e.message;
        $('#gate-error').classList.remove('hidden');
    }
}

/* ─── Hydrate form from config ─── */
function hydrateForm() {
    const b = CONFIG.branding || {};
    const h = CONFIG.hero || {};
    const c = CONFIG.contact || {};
    const s = CONFIG.social || {};
    const p = CONFIG.policies || {};
    const seo = CONFIG.seo || {};
    const f = CONFIG.features || {};
    const food = CONFIG.food_config || {};

    $('#f-branding-store_name').value = b.store_name || '';
    $('#f-branding-tagline').value = b.tagline || '';
    $('#f-branding-font').value = b.font_family || 'Inter';
    setColor('primary', b.primary_color || '#3b82f6');
    setColor('accent', b.accent_color || '#f59e0b');
    setColor('background', b.background || '#ffffff');
    setColor('text', b.text_color || '#0f172a');
    renderUploadPreview('logo', b.logo_url);
    renderUploadPreview('favicon', b.favicon_url);

    // Theme
    $$('.theme-card').forEach(t => t.classList.toggle('selected', t.dataset.theme === (CONFIG.theme || 'modern')));
    // Ensure layout is initialized from saved config (falls back to defaults)
    if (!CONFIG.layout) {
        CONFIG.layout = { product_card: 'grid', hero: 'split', grid_density: 'normal' };
    }

    // Hero
    setToggle('t-hero-enabled', h.enabled !== false);
    $('#f-hero-headline').value = h.headline || '';
    $('#f-hero-subtext').value = h.subtext || '';
    $('#f-hero-cta_text').value = h.cta_text || 'Shop now';
    $('#f-hero-cta_link').value = h.cta_link || '#products';
    $('#f-hero-overlay').value = String(h.overlay ?? 0.35);
    $('#hero-overlay-label').textContent = Number(h.overlay ?? 0.35).toFixed(2);
    renderUploadPreview('hero', h.image_url);

    // Contact
    $('#f-contact-email').value = c.email || '';
    $('#f-contact-phone').value = c.phone || '';
    $('#f-contact-whatsapp').value = c.whatsapp || '';
    $('#f-contact-address').value = c.address || '';

    // Social
    $('#f-social-facebook').value = s.facebook || '';
    $('#f-social-instagram').value = s.instagram || '';
    $('#f-social-twitter').value = s.twitter || '';
    $('#f-social-tiktok').value = s.tiktok || '';

    // Policies
    $('#f-policies-shipping').value = p.shipping || '';
    $('#f-policies-returns').value = p.returns || '';
    $('#f-policies-privacy').value = p.privacy || '';

    // SEO
    $('#f-seo-meta_title').value = seo.meta_title || '';
    $('#f-seo-meta_description').value = seo.meta_description || '';

    // Features
    setToggle('t-features-show_search', f.show_search !== false);
    setToggle('t-features-show_categories', f.show_categories !== false);
    setToggle('t-features-show_contact_bar', f.show_contact_bar !== false);
    setToggle('t-features-show_loyalty_cta', f.show_loyalty_cta !== false);

    // Food
    if (ORG_META.vertical === 'food') {
        $('#nav-food').classList.remove('hidden');
        setToggle('t-food-accepting_orders', food.accepting_orders !== false);
        $('#f-food-closed_message').value = food.closed_message || '';

        const fm = food.fulfillment_modes || {};
        ['delivery', 'pickup', 'dine_in'].forEach(mode => {
            const cfg = fm[mode] || {};
            setToggle('t-food-' + mode, cfg.enabled !== false);
            $('#f-food-' + mode + '-prep').value = cfg.prep_time_minutes || '';
        });

        const oh = food.opening_hours || {};
        ['mon','tue','wed','thu','fri','sat','sun'].forEach(day => {
            const d = oh[day] || {};
            $('#f-hours-' + day + '-open').value = d.open || '';
            $('#f-hours-' + day + '-close').value = d.close || '';
        });

        renderSections(food.menu_sections || []);
    }

    renderSectionsUI();
}

/* ─── UI primitives ─── */
function setColor(key, hex) {
    $('#c-' + key).value = hex;
    $('#c-' + key + '-label').textContent = hex;
}
function getColor(key) { return $('#c-' + key).value; }

function setToggle(id, on) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.toggle('on', !!on);
}
function getToggle(id) {
    const el = document.getElementById(id);
    return el ? el.classList.contains('on') : false;
}

function renderUploadPreview(kind, url) {
    const box = document.getElementById('upload-' + kind);
    if (!box) return;
    if (url) {
        box.outerHTML = '<div class="upload-preview" id="upload-' + kind + '">' +
            '<img src="' + esc(url) + '" alt="' + kind + ' preview" />' +
            '<div class="flex-1 min-w-0">' +
                '<div class="text-xs text-slate-400">Current ' + kind + '</div>' +
                '<div class="text-xs text-slate-500 truncate">' + esc(url) + '</div>' +
            '</div>' +
            '<button type="button" class="text-slate-400 hover:text-red-400 p-2" data-clear="' + kind + '">' +
                '<i class="fa-regular fa-trash-can"></i>' +
            '</button>' +
        '</div>';
    } else {
        const placeholders = {
            logo: { icon: 'fa-cloud-arrow-up', label: 'Upload logo', hint: 'PNG, JPG, WEBP, or SVG · 3MB max' },
            favicon: { icon: 'fa-star', label: 'Upload favicon', hint: 'Small square icon, 32×32 recommended' },
            hero: { icon: 'fa-image', label: 'Upload hero image', hint: 'Wide image, 1600×600 or larger' }
        };
        const p = placeholders[kind];
        box.outerHTML = '<div class="upload-box" id="upload-' + kind + '">' +
            '<i class="fa-solid ' + p.icon + ' text-2xl text-slate-500 mb-2"></i>' +
            '<div class="text-sm text-slate-300 font-medium">' + p.label + '</div>' +
            '<div class="text-xs text-slate-500 mt-1">' + p.hint + '</div>' +
        '</div>';
    }
}

function renderSections(sections) {
    const list = document.getElementById('sections-list');
    list.innerHTML = (sections || []).map((sec, i) => renderSectionRow(sec, i)).join('');
    list.querySelectorAll('[data-section-remove]').forEach(btn => {
        btn.addEventListener('click', () => {
            const idx = Number(btn.dataset.sectionRemove);
            removeSection(idx);
        });
    });
    list.querySelectorAll('[data-section-name]').forEach(input => {
        input.addEventListener('input', () => {
            const idx = Number(input.dataset.sectionName);
            updateSectionName(idx, input.value);
        });
    });
    list.querySelectorAll('[data-section-order]').forEach(input => {
        input.addEventListener('input', () => {
            const idx = Number(input.dataset.sectionOrder);
            updateSectionOrder(idx, Number(input.value) || 0);
        });
    });
}

function renderSectionRow(sec, i) {
    return '<div class="flex items-center gap-2 bg-slate-900 border border-slate-700 rounded-xl p-2">' +
        '<input type="text" value="' + esc(sec.name || '') + '" placeholder="Section name" ' +
            'class="flex-1 bg-slate-800 border border-slate-600 rounded px-3 py-2 text-sm" ' +
            'data-section-name="' + i + '" />' +
        '<input type="number" value="' + (sec.order || i + 1) + '" min="0" ' +
            'class="w-16 bg-slate-800 border border-slate-600 rounded px-2 py-2 text-sm" ' +
            'data-section-order="' + i + '" />' +
        '<button type="button" class="text-slate-500 hover:text-red-400 p-2" data-section-remove="' + i + '">' +
            '<i class="fa-regular fa-trash-can"></i>' +
        '</button>' +
    '</div>';
}

function addSection() {
    if (!CONFIG.food_config) CONFIG.food_config = {};
    if (!CONFIG.food_config.menu_sections) CONFIG.food_config.menu_sections = [];
    CONFIG.food_config.menu_sections.push({ name: 'New section', order: CONFIG.food_config.menu_sections.length + 1 });
    renderSections(CONFIG.food_config.menu_sections);
    markDirty();
}

function removeSection(idx) {
    CONFIG.food_config.menu_sections.splice(idx, 1);
    renderSections(CONFIG.food_config.menu_sections);
    markDirty();
}

function updateSectionName(idx, name) {
    if (!CONFIG.food_config.menu_sections[idx]) return;
    CONFIG.food_config.menu_sections[idx].name = name;
    markDirty();
}

function updateSectionOrder(idx, order) {
    if (!CONFIG.food_config.menu_sections[idx]) return;
    CONFIG.food_config.menu_sections[idx].order = order;
    markDirty();
}

/* ─── Sections editor (page sections) ─── */
function renderSectionsUI() {
    const editor = document.getElementById('sections-editor');
    if (!editor) return;
    const list = CONFIG.sections || [];
    const SECTION_LABELS = {
        'hero': 'Hero',
        'benefits': 'Benefits strip',
        'categories': 'Shop by Category',
        'top-picks': "Today's Picks",
        'needs': 'Shop by Need',
        'products': 'Product grid',
        'about': 'About',
        'cta': 'Call to action'
    };
    if (list.length === 0) {
        editor.innerHTML = '<div class="text-sm text-slate-400 text-center py-8">No sections yet. Add one below.</div>';
        return;
    }
    editor.innerHTML = list.map((sec, i) => `
        <div class="flex items-center gap-2 bg-slate-900 border border-slate-700 rounded-xl p-3">
            <div class="flex flex-col gap-0.5">
                <button class="text-slate-500 hover:text-white p-1 disabled:opacity-20" data-move-up="${i}" ${i === 0 ? 'disabled' : ''} aria-label="Move up">
                    <i class="fa-solid fa-chevron-up text-xs"></i>
                </button>
                <button class="text-slate-500 hover:text-white p-1 disabled:opacity-20" data-move-down="${i}" ${i === list.length - 1 ? 'disabled' : ''} aria-label="Move down">
                    <i class="fa-solid fa-chevron-down text-xs"></i>
                </button>
            </div>
            <div class="flex-1">
                <div class="font-medium text-white">${escapeHtml(SECTION_LABELS[sec.type] || sec.type)}</div>
                <div class="text-xs text-slate-500 font-mono">${escapeHtml(sec.type)}</div>
            </div>
            <button class="text-slate-500 hover:text-red-400 p-2" data-remove-section="${i}" aria-label="Remove section">
                <i class="fa-regular fa-trash-can"></i>
            </button>
        </div>
    `).join('');

    editor.querySelectorAll('[data-move-up]').forEach(btn => {
        btn.addEventListener('click', () => {
            const i = Number(btn.dataset.moveUp);
            if (i <= 0) return;
            const [item] = CONFIG.sections.splice(i, 1);
            CONFIG.sections.splice(i - 1, 0, item);
            renderSectionsUI();
            markDirty();
        });
    });
    editor.querySelectorAll('[data-move-down]').forEach(btn => {
        btn.addEventListener('click', () => {
            const i = Number(btn.dataset.moveDown);
            if (i >= CONFIG.sections.length - 1) return;
            const [item] = CONFIG.sections.splice(i, 1);
            CONFIG.sections.splice(i + 1, 0, item);
            renderSectionsUI();
            markDirty();
        });
    });
    editor.querySelectorAll('[data-remove-section]').forEach(btn => {
        btn.addEventListener('click', () => {
            const i = Number(btn.dataset.removeSection);
            CONFIG.sections.splice(i, 1);
            renderSectionsUI();
            markDirty();
        });
    });
}

/* ─── Header state ─── */
function updateHeader() {
    const b = CONFIG.branding || {};
    $('#hdr-store-name').textContent = b.store_name || ORG_META.org_name || 'Store';
    $('#hdr-slug').textContent = '/' + (ORG_META.slug || '');
    $('#hdr-live-link').href = ORG_META.slug ? ('/store/' + ORG_META.slug) : '#';
}
function updatePublishButton() {
    const pub = ORG_META.published;
    const status = $('#hdr-status');
    if (pub) {
        status.textContent = 'Live';
        status.className = 'text-xs px-3 py-1.5 rounded-lg font-medium bg-emerald-900/40 text-emerald-300';
        $('#publish-label').textContent = 'Unpublish';
        $('#btn-publish').className = 'bg-slate-700 hover:bg-slate-600 text-sm px-4 py-2 rounded-lg font-medium';
    } else {
        status.textContent = 'Unpublished';
        status.className = 'text-xs px-3 py-1.5 rounded-lg font-medium bg-slate-700 text-slate-300';
        $('#publish-label').textContent = 'Publish';
        $('#btn-publish').className = 'bg-emerald-600 hover:bg-emerald-700 text-sm px-4 py-2 rounded-lg font-medium';
    }
}

/* ─── Build payload from form ─── */
function buildPayload() {
    const payload = {
        theme: CONFIG.theme || 'modern',
        layout: CONFIG.layout || { product_card: 'grid', hero: 'split', grid_density: 'normal' },
        sections: CONFIG.sections || [],
        branding: {
            store_name: $('#f-branding-store_name').value.trim() || null,
            tagline: $('#f-branding-tagline').value.trim() || null,
            primary_color: getColor('primary'),
            accent_color: getColor('accent'),
            background: getColor('background'),
            text_color: getColor('text'),
            font_family: $('#f-branding-font').value || 'Inter'
        },
        hero: {
            enabled: getToggle('t-hero-enabled'),
            headline: $('#f-hero-headline').value.trim() || null,
            subtext: $('#f-hero-subtext').value.trim() || null,
            cta_text: $('#f-hero-cta_text').value.trim() || null,
            cta_link: $('#f-hero-cta_link').value.trim() || null,
            overlay: parseFloat($('#f-hero-overlay').value) || 0,
            image_url: CONFIG.hero && CONFIG.hero.image_url || null
        },
        contact: {
            email: $('#f-contact-email').value.trim() || null,
            phone: $('#f-contact-phone').value.trim() || null,
            whatsapp: $('#f-contact-whatsapp').value.trim() || null,
            address: $('#f-contact-address').value.trim() || null
        },
        social: {
            facebook: $('#f-social-facebook').value.trim() || null,
            instagram: $('#f-social-instagram').value.trim() || null,
            twitter: $('#f-social-twitter').value.trim() || null,
            tiktok: $('#f-social-tiktok').value.trim() || null
        },
        policies: {
            shipping: $('#f-policies-shipping').value.trim() || null,
            returns: $('#f-policies-returns').value.trim() || null,
            privacy: $('#f-policies-privacy').value.trim() || null
        },
        seo: {
            meta_title: $('#f-seo-meta_title').value.trim() || null,
            meta_description: $('#f-seo-meta_description').value.trim() || null
        },
        features: {
            show_search: getToggle('t-features-show_search'),
            show_categories: getToggle('t-features-show_categories'),
            show_contact_bar: getToggle('t-features-show_contact_bar'),
            show_loyalty_cta: getToggle('t-features-show_loyalty_cta')
        }
    };

    // Carry logo/favicon URLs which are stored but not form-bound
    payload.branding.logo_url = CONFIG.branding && CONFIG.branding.logo_url || null;
    payload.branding.favicon_url = CONFIG.branding && CONFIG.branding.favicon_url || null;

    if (ORG_META.vertical === 'food') {
        const fm = {
            delivery: {
                enabled: getToggle('t-food-delivery'),
                prep_time_minutes: parseInt($('#f-food-delivery-prep').value, 10) || 0
            },
            pickup: {
                enabled: getToggle('t-food-pickup'),
                prep_time_minutes: parseInt($('#f-food-pickup-prep').value, 10) || 0
            },
            dine_in: {
                enabled: getToggle('t-food-dine_in'),
                prep_time_minutes: parseInt($('#f-food-dine_in-prep').value, 10) || 0
            }
        };
        const oh = {};
        ['mon','tue','wed','thu','fri','sat','sun'].forEach(day => {
            const open = $('#f-hours-' + day + '-open').value;
            const close = $('#f-hours-' + day + '-close').value;
            if (open && close) oh[day] = { open, close };
        });
        payload.food_config = {
            menu_sections: (CONFIG.food_config && CONFIG.food_config.menu_sections) || [],
            fulfillment_modes: fm,
            opening_hours: oh,
            accepting_orders: getToggle('t-food-accepting_orders'),
            closed_message: $('#f-food-closed_message').value.trim() || null
        };
    }

    return payload;
}

/* ─── Save / Publish ─── */
async function save() {
    const btn = $('#btn-save');
    btn.disabled = true;
    $('#save-label').textContent = 'Saving…';
    try {
        const payload = buildPayload();
        const res = await api('/storefront/config', {
            method: 'PATCH',
            body: JSON.stringify(payload)
        });
        CONFIG = res.config;
        ORG_META.config = res.config;
        clearDirty();
        toast('Saved', 'success');
        updateHeader();
    } catch (e) {
        toast(e.message, 'error');
        btn.disabled = false;
        $('#save-label').textContent = 'Save';
    }
}

async function togglePublish() {
    try {
        if (ORG_META.published) {
            await api('/storefront/unpublish', { method: 'POST' });
            ORG_META.published = false;
            toast('Storefront unpublished', 'info');
        } else {
            // Ensure current changes are saved before publishing
            if (DIRTY) await save();
            const res = await api('/storefront/publish', { method: 'POST' });
            ORG_META.published = true;
            toast('Storefront published', 'success');
        }
        updatePublishButton();
    } catch (e) {
        toast(e.message, 'error');
    }
}

/* ─── Uploads ─── */
async function uploadFile(kind, file) {
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);
    try {
        const res = await fetch(API_BASE + '/storefront/upload', {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + TOKEN },
            body: fd
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Upload failed');

        // Store on local config object
        if (!CONFIG.branding) CONFIG.branding = {};
        if (kind === 'logo') CONFIG.branding.logo_url = data.url;
        if (kind === 'favicon') CONFIG.branding.favicon_url = data.url;
        if (kind === 'hero') {
            if (!CONFIG.hero) CONFIG.hero = {};
            CONFIG.hero.image_url = data.url;
        }
        renderUploadPreview(kind, data.url);
        wireUpload(kind);
        markDirty();
        updateHeader();
        toast(kind + ' uploaded', 'success');
    } catch (e) {
        toast(e.message, 'error');
    }
}

function wireUpload(kind) {
    const box = document.getElementById('upload-' + kind);
    const input = document.getElementById('file-' + kind);
    if (!box || !input) return;

    // Existing preview — wire the clear button
    const clearBtn = box.querySelector('[data-clear]');
    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            if (!CONFIG.branding) CONFIG.branding = {};
            if (!CONFIG.hero) CONFIG.hero = {};
            if (kind === 'logo') CONFIG.branding.logo_url = null;
            if (kind === 'favicon') CONFIG.branding.favicon_url = null;
            if (kind === 'hero') CONFIG.hero.image_url = null;
            renderUploadPreview(kind, null);
            wireUpload(kind);
            markDirty();
            updateHeader();
        });
        return;
    }

    // Placeholder — wire the click to open file picker
    box.addEventListener('click', () => input.click());
    input.onchange = (e) => {
        if (e.target.files[0]) uploadFile(kind, e.target.files[0]);
        input.value = '';
    };
}

/* ─── Wiring ─── */
function wireAll() {
    // Sidebar tabs
    $$('.nav-item').forEach(btn => {
        btn.addEventListener('click', () => {
            $$('.nav-item').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            $$('[data-panel]').forEach(p => p.classList.toggle('hidden', p.dataset.panel !== btn.dataset.tab));
        });
    });

    // Dirty tracking — any input in the main area
    document.querySelectorAll('input, textarea, select').forEach(el => {
        if (el.closest('#gate')) return;
        el.addEventListener('input', markDirty);
        el.addEventListener('change', markDirty);
    });

    // Colour pickers
    ['primary', 'accent', 'background', 'text'].forEach(key => {
        const input = document.getElementById('c-' + key);
        input.addEventListener('input', () => {
            $('#c-' + key + '-label').textContent = input.value;
            markDirty();
        });
    });

    // Toggles
    document.querySelectorAll('.toggle').forEach(t => {
        t.addEventListener('click', () => {
            t.classList.toggle('on');
            markDirty();
        });
    });

    // Theme cards
    const THEME_PRESETS = {
        modern: {
            layout: { product_card: 'grid', hero: 'split', grid_density: 'normal' },
            sections: [
                { type: 'hero' },
                { type: 'benefits' },
                { type: 'categories' },
                { type: 'top-picks' },
                { type: 'needs' },
                { type: 'products' }
            ]
        },
        minimal: {
            layout: { product_card: 'list', hero: 'minimal', grid_density: 'sparse' },
            sections: [
                { type: 'hero' },
                { type: 'products' }
            ]
        },
        bold: {
            layout: { product_card: 'editorial', hero: 'full', grid_density: 'dense' },
            sections: [
                { type: 'hero' },
                { type: 'categories' },
                { type: 'top-picks' },
                { type: 'products' },
                { type: 'benefits' }
            ]
        },
        warm: {
            layout: { product_card: 'rounded', hero: 'split', grid_density: 'normal' },
            sections: [
                { type: 'hero' },
                { type: 'benefits' },
                { type: 'top-picks' },
                { type: 'categories' },
                { type: 'products' },
                { type: 'about' },
                { type: 'cta' }
            ]
        }
    };

    $$('.theme-card').forEach(card => {
        card.addEventListener('click', () => {
            $$('.theme-card').forEach(c => c.classList.remove('selected'));
            card.classList.add('selected');
            const themeName = card.dataset.theme;
            CONFIG.theme = themeName;
            const preset = THEME_PRESETS[themeName] || {};
            CONFIG.layout = Object.assign({}, CONFIG.layout, preset.layout || {});
            CONFIG.sections = JSON.parse(JSON.stringify(preset.sections || []));
            markDirty();
            if (typeof toast === 'function') {
                toast(`Theme set to ${themeName} — save to apply`, 'info');
            }
            if (typeof renderSectionsUI === 'function') renderSectionsUI();
        });
    });

    // Hero overlay slider label
    $('#f-hero-overlay').addEventListener('input', (e) => {
        $('#hero-overlay-label').textContent = Number(e.target.value).toFixed(2);
    });

    // Upload placeholders
    ['logo', 'favicon', 'hero'].forEach(wireUpload);

    // Sections
    $('#btn-add-section').addEventListener('click', addSection);

    // Page sections editor — add section
    document.getElementById('add-section-btn')?.addEventListener('click', () => {
        const select = document.getElementById('add-section-select');
        const type = select.value;
        if (!type) return;
        if (!CONFIG.sections) CONFIG.sections = [];
        CONFIG.sections.push({ type });
        renderSectionsUI();
        select.value = '';
        markDirty();
    });

    // Save / Publish
    $('#btn-save').addEventListener('click', save);
    $('#btn-publish').addEventListener('click', togglePublish);
    $('#btn-preview').addEventListener('click', () => {
        if (!ORG_META.slug) { toast('Set a slug first', 'error'); return; }
        window.open('/store/' + ORG_META.slug, '_blank');
    });

    // Warn on unsaved changes
    window.addEventListener('beforeunload', (e) => {
        if (DIRTY) { e.preventDefault(); e.returnValue = ''; }
    });
}

/* ─── Init ─── */
$('#gate-signin').addEventListener('click', signin);
$('#gate-password').addEventListener('keypress', e => { if (e.key === 'Enter') signin(); });

if (TOKEN) {
    bootApp();
}
