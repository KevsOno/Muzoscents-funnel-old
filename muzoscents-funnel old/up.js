// ============================================================
// PWA MOBILE VIEW
// Installed PWAs on some Android devices can expose a wider CSS
// viewport than the physical phone. Detect the standalone/coarse
// pointer environment and remove desktop-only Tailwind breakpoint
// utilities so the base mobile layout remains authoritative.
// ============================================================
(function applyPwaMobileMode() {
    const standalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
    const coarsePointer = window.matchMedia('(pointer: coarse)').matches;
    if (!standalone || !coarsePointer) return;

    document.documentElement.classList.add('pwa-mobile');

    const stripDesktopUtilities = () => {
        document.querySelectorAll('[class*="md:"] , [class*="lg:"]').forEach(el => {
            [...el.classList].forEach(cls => {
                if (cls.startsWith('md:') || cls.startsWith('lg:')) el.classList.remove(cls);
            });
        });
    };

    if (document.body) stripDesktopUtilities();
    document.addEventListener('DOMContentLoaded', stripDesktopUtilities, { once: true });
})();

// ========== CONFIG ==========
const API_BASE = "https://kevsono-kevs-digital-bos.hf.space";
let token = localStorage.getItem('access_token');
let userProfile = null;
let userLoyalty = { points: 0, tier: 'bronze' };
let cart = [];
let deliveryOption = localStorage.getItem('pf_delivery_option') || 'pickup';
let deliveryAddress = localStorage.getItem('pf_delivery_address') || '';
let deliveryFee = 0,
    handlingFee = 0;
let allProducts = [];
let totalItems = 0;
let totalPages = 1;
let searchQuery = '';
let selectedCategory = '';
let categories = [];
let sessionId = localStorage.getItem('pf_session') || ('web_' + Date.now() + '_' + Math.random().toString(36).substr(2, 10));
localStorage.setItem('pf_session', sessionId);
let currentView = 'shop';
let currentProductForModal = null;
let isRecalcInProgress = false;
let lastCalculatedCartState = '';

let modalQuantity = 1;
let productQuantities = {};

// Flag to track if delivery estimation has been successfully performed
let isDeliveryEstimated = false;

// Featured carousel state (Update #2)
let featuredProducts = [];
let featuredCurrentIndex = 0;
let featuredInterval = null;
let isFeaturedLoading = false;

// ========== PAGINATION ==========
let currentPage = 1;
const PAGE_SIZE = 101;

// ========== UTILITIES ==========
function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/[&<>]/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' } [m]));
}

function showToast(msg, type) {
    const t = document.createElement('div');
    t.className =
        `fixed bottom-20 left-4 right-4 md:left-auto md:right-6 z-50 bg-${type==='success'?'green-600':'red-600'} text-white px-4 py-2 rounded-xl shadow-lg text-sm`;
    t.innerText = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 3000);
}

function setButtonLoading(btn, loading) {
    if (!btn) return;
    if (loading) {
        btn.disabled = true;
        btn.dataset.origHtml = btn.innerHTML;
        btn.innerHTML = '<span class="loader-small"></span> Please wait...';
    } else {
        btn.disabled = false;
        if (btn.dataset.origHtml) {
            btn.innerHTML = btn.dataset.origHtml;
        }
    }
}

function setCartTotalLoading(loading) {
    const totalSpan = document.getElementById('cart-total');
    if (loading) {
        totalSpan.innerHTML = '<span class="loader-small"></span>';
    } else {
        const subtotal = cart.reduce((s, i) => s + i.price * i.quantity, 0);
        let total = subtotal;
        if (deliveryOption === 'delivery' && deliveryAddress && deliveryFee) total += deliveryFee;
        totalSpan.innerText = `₦${total.toLocaleString()}`;
    }
}

// Update #8: API call with exponential backoff
async function apiCall(endpoint, options = {}, retryCount = 3, delay = 1000) {
    if (!options.headers) options.headers = {};
    options.headers['Content-Type'] = 'application/json';
    if (token) options.headers['Authorization'] = `Bearer ${token}`;
    const selectedOrgId = localStorage.getItem('selected_org_id');
    if (selectedOrgId) {
        options.headers['X-Selected-Org-Id'] = selectedOrgId;
    }

    let attempt = 0;
    while (attempt < retryCount) {
        try {
            let res = await fetch(`${API_BASE}${endpoint}`, options);
            if (res.status === 401 && attempt < retryCount - 1) {
                const refresh = localStorage.getItem('refresh_token');
                if (refresh) {
                    const refreshRes = await fetch(`${API_BASE}/auth/refresh`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ refresh_token: refresh })
                    });
                    if (refreshRes.ok) {
                        const { access_token, refresh_token } = await refreshRes.json();
                        localStorage.setItem('access_token', access_token);
                        localStorage.setItem('refresh_token', refresh_token);
                        token = access_token;
                        options.headers['Authorization'] = `Bearer ${token}`;
                        // Retry with new token
                        continue;
                    }
                }
                showAuthModal();
                throw new Error('Session expired');
            }
            if (!res.ok) {
                const err = await res.json().catch(() => ({ detail: 'Error' }));
                throw new Error(err.detail || 'Request failed');
            }
            return await res.json();
        } catch (e) {
            attempt++;
            if (attempt >= retryCount) throw e;
            // Exponential backoff
            const wait = delay * Math.pow(2, attempt - 1);
            await new Promise(resolve => setTimeout(resolve, wait));
        }
    }
}

// ============================================================
//  VIEWS
// ============================================================
function showView(view) {
    currentView = view;
    const shopDiv = document.getElementById('shop-view'),
        ticketsDiv = document.getElementById('tickets-view'),
        confirmDiv = document.getElementById('confirmation-view');
    shopDiv.classList.add('hidden');
    ticketsDiv.classList.add('hidden');
    confirmDiv.classList.add('hidden');

    if (view === 'shop') {
        shopDiv.classList.remove('hidden');
        if (allProducts.length === 0) loadProducts();
    } else if (view === 'tickets') {
        ticketsDiv.classList.remove('hidden');
        loadTickets();
    } else if (view === 'confirmation') {
        confirmDiv.classList.remove('hidden');
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }
}

// ============================================================
//  PRODUCTS / CATEGORIES
// ============================================================
async function loadCategories() {
    try {
        const data = await apiCall('/inventory/public-categories');
        if (data.categories && data.categories.length) {
            categories = data.categories;
            console.log("✅ Categories loaded:", categories);
            updateCategoryDropdown();
            return;
        }
    } catch (e) {
        console.log("Category endpoint failed, using product data.");
    }
    if (allProducts && allProducts.length) {
        const groups = allProducts.map(p => p.product_group).filter(g => g && g.trim());
        const unique = [...new Set(groups)];
        if (unique.length) {
            categories = unique.sort();
            updateCategoryDropdown();
            return;
        }
    }
    categories = [];
    updateCategoryDropdown();
}

function updateCategoryDropdown() {
    const select = document.getElementById('category-select');
    if (!select) return;
    let options = '<option value="">All Categories</option>';
    if (categories && categories.length) {
        options += categories.map(c => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('');
    } else {
        options += '<option disabled>— No categories found —</option>';
    }
    select.innerHTML = options;
    const mobileSelect = document.getElementById('category-select-mobile');
    if (mobileSelect) mobileSelect.innerHTML = options;
    renderCategoryCards();
}

async function loadProducts(page = currentPage, limit = PAGE_SIZE) {
    const offset = (page - 1) * limit;
    let url = `/inventory/public-list?limit=${limit}&offset=${offset}`;
    if (searchQuery.trim()) url += `&q=${encodeURIComponent(searchQuery.trim())}`;
    if (selectedCategory && selectedCategory !== '') url += `&category=${encodeURIComponent(selectedCategory)}`;

    try {
        const data = await apiCall(url);
        const items = data.items || [];
        totalItems = data.total || 0;
        totalPages = Math.ceil(totalItems / limit) || 1;
        currentPage = page;

        allProducts = items;
        productQuantities = {};
        allProducts.forEach(p => { productQuantities[p.id] = 1; });
        renderProducts();
        renderPagination();
        // Also load featured products
        loadTopProducts();
    } catch (e) {
        console.error("Failed to load products:", e);
        document.getElementById('products-grid').innerHTML = `<div class="col-span-full text-red-500">⚠️ ${e.message}</div>`;
    }
}

function renderPagination() {
    const container = document.getElementById('pagination-container');
    if (!container) return;

    const start = (currentPage - 1) * PAGE_SIZE + 1;
    const end = Math.min(currentPage * PAGE_SIZE, totalItems);
    let infoHtml = '';
    if (totalItems > 0) {
        infoHtml = `<div class="pagination-info text-center text-sm text-gray-500 mb-2">Showing ${start}–${end} of ${totalItems}</div>`;
    }

    if (totalPages <= 1) {
        container.innerHTML = infoHtml + '';
        return;
    }

    let html = infoHtml + `<div class="flex justify-center items-center gap-2 flex-wrap">`;
    if (currentPage > 1) html +=
        `<button class="page-btn px-3 py-1 bg-gray-200 rounded hover:bg-gray-300" data-page="${currentPage-1}">← Prev</button>`;

    const startPage = Math.max(1, currentPage - 2);
    const endPage = Math.min(totalPages, currentPage + 2);
    for (let i = startPage; i <= endPage; i++) {
        const active = i === currentPage ? 'bg-orange-500 text-white' : 'bg-gray-200 hover:bg-gray-300';
        html += `<button class="page-btn px-3 py-1 rounded ${active}" data-page="${i}">${i}</button>`;
    }

    if (currentPage < totalPages) html +=
        `<button class="page-btn px-3 py-1 bg-gray-200 rounded hover:bg-gray-300" data-page="${currentPage+1}">Next →</button>`;
    html += `</div>`;
    container.innerHTML = html;
}

function productCardHtml(p, featured = false) {
    if (!productQuantities.hasOwnProperty(p.id)) productQuantities[p.id] = 1;
    const qty = productQuantities[p.id];
    const stock = Number(p.current_qty || 0);
    // Update #4: escape image URL
    const safeImageUrl = p.image_url ? escapeHtml(p.image_url) : null;
    const imageHtml = safeImageUrl
        ? `<img src="${safeImageUrl}" alt="${escapeHtml(p.description)}" loading="lazy">`
        : `<i class="fa-solid fa-box-open text-4xl text-gray-300"></i>`;

    return `
        <article class="pf-product-card product-card cursor-pointer" data-product-id="${p.id}">
            <div class="pf-product-image">
                ${stock > 0 ? `<span class="absolute top-3 left-3 bg-[#eaf5e8] text-[#075c3a] text-[10px] font-bold px-2 py-1 rounded-full z-10">In stock</span>` : `<span class="absolute top-3 left-3 bg-red-50 text-red-600 text-[10px] font-bold px-2 py-1 rounded-full z-10">Out of stock</span>`}
                ${imageHtml}
            </div>
            <div class="p-3.5">
                <h3 class="font-bold text-gray-800 text-sm leading-5 line-clamp-2 min-h-[40px]" title="${escapeHtml(p.description)}">${escapeHtml(p.description)}</h3>
                <div class="flex items-center justify-between gap-2 mt-3">
                    <span class="pf-price font-black text-base md:text-lg">₦${Number(p.price_naira || 0).toLocaleString()}</span>
                    ${stock > 0 ? `<span class="pf-stock"><i class="fa-solid fa-check mr-1"></i>${stock} available</span>` : ''}
                </div>
                <div class="flex items-center justify-between gap-2 mt-3">
                    <div class="flex items-center gap-1">
                        <!-- Update #7: aria-label for quantity buttons -->
                        <button class="pf-qty-btn qty-btn" data-id="${p.id}" data-delta="-1" aria-label="Decrease quantity">−</button>
                        <span class="pf-qty qty-display" id="qty-${p.id}">${qty}</span>
                        <button class="pf-qty-btn qty-btn green" data-id="${p.id}" data-delta="1" aria-label="Increase quantity">+</button>
                    </div>
                    <button class="pf-add-btn add-to-cart-btn px-3 flex items-center justify-center gap-2 font-bold text-sm"
                        data-id="${p.id}" ${stock <= 0 ? 'disabled title="Out of stock"' : ''}>
                        <i class="fa-solid fa-cart-plus"></i><span class="hidden sm:inline">Add</span>
                    </button>
                </div>
            </div>
        </article>`;
}

function renderProducts() {
    const grid = document.getElementById('products-grid');
    const featuredGrid = document.getElementById('featured-grid');
    if (!grid) return;

    const items = allProducts || [];
    const featuredItems = items.slice(0, 6);

    if (featuredGrid) {
        // Only render static fallback if featured carousel hasn't loaded yet
        if (!isFeaturedLoading && featuredProducts.length === 0) {
            featuredGrid.innerHTML = featuredItems.length
                ? featuredItems.map(p => productCardHtml(p, true)).join('')
                : '<div class="col-span-full text-center py-10 text-gray-500">No featured products available.</div>';
        }
    }

    if (items.length === 0) {
        grid.innerHTML = `<div class="col-span-full text-center py-12 text-gray-500"><i class="fa-regular fa-face-frown text-2xl"></i><p class="mt-2">No products match your filters.</p></div>`;
        const summary = document.getElementById('product-results-summary');
        if (summary) summary.innerText = 'No products found.';
        return;
    }

    grid.innerHTML = items.map(p => productCardHtml(p)).join('');
    const summary = document.getElementById('product-results-summary');
    if (summary) {
        const filterText = searchQuery.trim() ? ` for “${escapeHtml(searchQuery.trim())}”` : '';
        summary.innerText = `Showing ${items.length} products${filterText}.`;
    }

    renderHeroProducts();
    renderCategoryCards();
}

function renderHeroProducts() {
    const collage = document.getElementById('hero-product-collage');
    if (!collage || !allProducts?.length) return;
    const slots = [...collage.querySelectorAll('.pf-hero-product')];
    const products = allProducts.filter(p => p.image_url).slice(0, slots.length);
    slots.forEach((slot, i) => {
        const p = products[i];
        // Update #4: escape image URL in hero as well
        const safeImageUrl = p && p.image_url ? escapeHtml(p.image_url) : null;
        slot.innerHTML = safeImageUrl
            ? `<img src="${safeImageUrl}" alt="${escapeHtml(p.description)}">`
            : `<div class="text-gray-300 text-4xl"><i class="fa-solid fa-box-open"></i></div>`;
    });
}

function categoryIcon(category) {
    const value = String(category || '').toLowerCase();
    if (/drink|beverage|water|wine|juice|soda/.test(value)) return 'fa-bottle-water';
    if (/food|grocery|rice|grain|flour|oil|kitchen/.test(value)) return 'fa-basket-shopping';
    if (/clean|deterg|soap|house/.test(value)) return 'fa-spray-can-sparkles';
    if (/beauty|personal|care|cosmetic/.test(value)) return 'fa-pump-soap';
    if (/baby|child|diaper/.test(value)) return 'fa-baby';
    if (/pet|animal/.test(value)) return 'fa-paw';
    if (/snack|sweet|confect/.test(value)) return 'fa-cookie-bite';
    return 'fa-store';
}

function renderCategoryCards() {
    const container = document.getElementById('category-cards');
    if (!container) return;

    const cats = (categories || []).filter(Boolean).slice(0, 12);
    if (!cats.length) {
        container.innerHTML = '<div class="text-sm text-gray-500">Categories will appear as products load.</div>';
        return;
    }

    container.innerHTML = cats.map((category, index) => {
        const product = allProducts.find(p => String(p.product_group || '').toLowerCase() === String(category).toLowerCase() && p.image_url);
        // Update #4: escape image URL in categories
        const safeImageUrl = product && product.image_url ? escapeHtml(product.image_url) : null;
        const visual = safeImageUrl
            ? `<img src="${safeImageUrl}" alt="${escapeHtml(category)}">`
            : `<i class="fa-solid ${categoryIcon(category)} text-3xl text-[#6d8f69]"></i>`;
        return `<button class="pf-category-card rounded-2xl p-2.5 text-left" data-category="${escapeHtml(category)}">
            <div class="pf-category-image">${visual}</div>
            <div class="font-bold text-xs mt-2.5 truncate">${escapeHtml(category)}</div>
            <div class="text-[10px] text-gray-400 mt-0.5">Shop now</div>
        </button>`;
    }).join('');
}

function updateProductQty(id, delta) {
    if (!productQuantities.hasOwnProperty(id)) productQuantities[id] = 1;
    const newQty = productQuantities[id] + delta;
    const product = allProducts.find(p => p.id == id);
    const maxStock = product ? (product.current_qty || 999) : 999;
    if (newQty < 1) return;
    if (newQty > maxStock) {
        showToast(`Only ${maxStock} available`, 'error');
        return;
    }
    productQuantities[id] = newQty;
    const display = document.getElementById(`qty-${id}`);
    if (display) display.innerText = newQty;
}

async function addFromCard(id) {
    const product = allProducts.find(p => p.id == id);
    if (!product) return;
    const qty = productQuantities[id] || 1;
    await addToCart({ id: product.id, name: product.description, price: product.price_naira }, qty);
    productQuantities[id] = 1;
    const display = document.getElementById(`qty-${id}`);
    if (display) display.innerText = 1;
}

// ============================================================
//  TODAY'S PICKS – DYNAMIC CAROUSEL (Update #2, #5, #9)
// ============================================================

async function loadTopProducts() {
    const grid = document.getElementById('featured-grid');
    if (!grid) return;

    // Show loading spinner (Update #9)
    isFeaturedLoading = true;
    grid.innerHTML = `<div class="col-span-full flex items-center justify-center py-10"><span class="loader-small"></span><span class="ml-3 text-gray-500 text-sm">Loading top picks...</span></div>`;

    try {
        const data = await apiCall('/public/top-products');
        const products = data.products || [];
        featuredProducts = products;
        renderFeaturedProducts(products);
    } catch (e) {
        console.error("Failed to load top products:", e);
        grid.innerHTML =
            `<div class="col-span-full text-center py-6 text-gray-500">Unable to load top picks.</div>`;
    } finally {
        isFeaturedLoading = false;
    }
}

function renderFeaturedProducts(products) {
    const container = document.getElementById('featured-grid');
    if (!container) return;

    // Clear existing
    container.innerHTML = '';

    // Fallback if empty (Update #5)
    if (!products || products.length === 0) {
        container.innerHTML =
            `<div class="col-span-full text-center py-6 text-gray-500">No top picks available yet. Check back soon!</div>`;
        return;
    }

    // Chunk products into groups of 2
    const slides = [];
    for (let i = 0; i < products.length; i += 2) {
        slides.push(products.slice(i, i + 2));
    }

    // Build carousel wrapper
    const carousel = document.createElement('div');
    carousel.className = 'featured-carousel';

    // Create each slide
    slides.forEach((chunk, idx) => {
        const slide = document.createElement('div');
        slide.className = `featured-slide${idx === 0 ? ' active' : ''}`;
        slide.dataset.index = idx;

        chunk.forEach(p => {
            // Ensure quantity exists
            if (!productQuantities.hasOwnProperty(p.inventory_id)) {
                productQuantities[p.inventory_id] = 1;
            }
            const qty = productQuantities[p.inventory_id] || 1;
            // Update #4: escape image URL
            const safeImageUrl = p.image_url ? escapeHtml(p.image_url) : null;
            const imageHtml = safeImageUrl ?
                `<img src="${safeImageUrl}" alt="${escapeHtml(p.product_name)}" loading="lazy">` :
                `<i class="fa-solid fa-box-open text-4xl text-gray-300"></i>`;

            const card = document.createElement('div');
            card.className = "pf-product-card product-card cursor-pointer";
            card.dataset.productId = p.inventory_id;
            card.innerHTML = `
                <div class="pf-product-image">
                    <span class="absolute top-3 left-3 bg-[#eaf5e8] text-[#075c3a] text-[10px] font-bold px-2 py-1 rounded-full z-10">In stock</span>
                    ${imageHtml}
                </div>
                <div class="p-3.5">
                    <h3 class="font-bold text-gray-800 text-sm leading-5 line-clamp-2 min-h-[40px]" title="${escapeHtml(p.product_name)}">${escapeHtml(p.product_name)}</h3>
                    <div class="flex items-center justify-between gap-2 mt-3">
                        <span class="pf-price font-black text-base md:text-lg">₦${Number(p.price_naira || 0).toLocaleString()}</span>
                        <span class="pf-stock"><i class="fa-solid fa-check mr-1"></i>In stock</span>
                    </div>
                    <div class="flex items-center justify-between gap-2 mt-3">
                        <div class="flex items-center gap-1">
                            <button class="pf-qty-btn qty-btn" data-id="${p.inventory_id}" data-delta="-1" aria-label="Decrease quantity">−</button>
                            <span class="pf-qty qty-display" id="qty-${p.inventory_id}">${qty}</span>
                            <button class="pf-qty-btn qty-btn green" data-id="${p.inventory_id}" data-delta="1" aria-label="Increase quantity">+</button>
                        </div>
                        <button class="pf-add-btn add-to-cart-btn px-3 flex items-center justify-center gap-2 font-bold text-sm" data-id="${p.inventory_id}">
                            <i class="fa-solid fa-cart-plus"></i><span class="hidden sm:inline">Add</span>
                        </button>
                    </div>
                </div>
            `;
            slide.appendChild(card);
        });

        carousel.appendChild(slide);
    });

    // If only one slide, no auto-rotation needed
    if (slides.length === 1) {
        container.appendChild(carousel);
        return;
    }

    // No dots (per your request)
    container.appendChild(carousel);

    // Auto-rotation (Update #2: no dots)
    if (featuredInterval) clearInterval(featuredInterval);
    featuredInterval = setInterval(() => {
        const total = slides.length;
        const next = (featuredCurrentIndex + 1) % total;
        goToFeaturedSlide(next);
    }, 5000);
}

function goToFeaturedSlide(index) {
    const container = document.getElementById('featured-grid');
    if (!container) return;

    const slides = container.querySelectorAll('.featured-slide');
    if (!slides.length || index === featuredCurrentIndex) return;

    // Update slides
    slides.forEach((slide, i) => {
        slide.classList.toggle('active', i === index);
    });

    featuredCurrentIndex = index;

    // Reset timer
    if (featuredInterval) {
        clearInterval(featuredInterval);
        const total = slides.length;
        featuredInterval = setInterval(() => {
            const next = (featuredCurrentIndex + 1) % total;
            goToFeaturedSlide(next);
        }, 5000);
    }
}

// ============================================================
//  PRODUCT DETAIL MODAL
// ============================================================
function showProductDetail(p) {
    currentProductForModal = p;
    modalQuantity = 1;

    const modal = document.getElementById('product-detail-modal'),
        content = document.getElementById('product-detail-content');
    const dim = (p.length_cm || p.width_cm || p.height_cm) ? `${p.length_cm||'?'}cm × ${p.width_cm||'?'}cm × ${p.height_cm||'?'}cm` :
        'Not specified';
    // Update #4: escape image URL in modal
    const safeImageUrl = p.image_url ? escapeHtml(p.image_url) : null;
    content.innerHTML =
        `<div class="flex flex-col gap-4">${safeImageUrl ? `<img src="${safeImageUrl}" class="w-full h-48 object-contain rounded-xl">` : `<div class="w-full h-48 bg-gradient-to-br from-orange-100 to-amber-100 rounded-xl flex items-center justify-center"><i class="fa-solid fa-cube text-5xl text-orange-400"></i></div>`}<h2 class="text-2xl font-bold">${escapeHtml(p.description)}</h2><div class="flex justify-between"><span class="text-3xl font-bold text-orange-600">₦${p.price_naira.toLocaleString()}</span><span class="bg-gray-100 px-3 py-1 rounded-full">Stock: ${p.current_qty||0}</span></div><div class="border-t pt-3 grid grid-cols-2 gap-3 text-sm"><div><span class="text-gray-500">Weight:</span> ${p.weight_kg ? p.weight_kg+' kg' : 'Not specified'}</div><div><span class="text-gray-500">Dimensions:</span> ${dim}</div><div><span class="text-gray-500">Handling:</span> ${p.handling_category || 'Standard'}</div><div><span class="text-gray-500">Size factor:</span> ${p.size_factor || 'Standard'}</div><div class="col-span-2 flex gap-2">${p.fragile ? '<span class="bg-red-100 text-red-700 px-2 py-1 rounded-full text-xs">Fragile</span>' : ''}${p.hazardous ? '<span class="bg-amber-100 text-amber-700 px-2 py-1 rounded-full text-xs">Hazardous</span>' : ''}</div>${p.product_group ? `<div><span class="text-gray-500">Group:</span> ${escapeHtml(p.product_group)}</div>` : ''}${p.item_code ? `<div><span class="text-gray-500">Item code:</span> ${escapeHtml(p.item_code)}</div>` : ''}</div><div class="bg-orange-50 p-3 rounded-xl text-sm"><i class="fa-regular fa-truck-fast text-orange-500 mr-2"></i> Delivery fees calculated based on weight, dimensions, and distance.</div></div>`;

    updateModalQtyDisplay();
    modal.classList.add('active');
}

function updateModalQtyDisplay() {
    const display = document.getElementById('modal-qty-display');
    const totalSpan = document.getElementById('modal-qty-total');
    if (display) display.innerText = modalQuantity;
    if (totalSpan && currentProductForModal) {
        totalSpan.innerText = `₦${(modalQuantity * currentProductForModal.price_naira).toLocaleString()}`;
    }
}

function closeProductModal() {
    document.getElementById('product-detail-modal').classList.remove('active');
    currentProductForModal = null;
}

// ============================================================
//  CART
// ============================================================
function saveCart() {
    localStorage.setItem('kevs_cart', JSON.stringify(cart));
    updateCartUI();
}

function loadCart() {
    const saved = localStorage.getItem('kevs_cart');
    cart = saved ? JSON.parse(saved) : [];
    updateCartUI();
}

async function addToCart(product, qty = 1) {
    if (qty < 1) qty = 1;
    let existing = cart.find(i => i.id === product.id);
    if (existing) {
        existing.quantity += qty;
    } else {
        cart.push({ id: product.id, name: product.name, price: product.price, quantity: qty });
    }
    saveCart();
    if (deliveryOption === 'delivery' && deliveryAddress) {
        await recalcDeliveryFee(true);
    } else {
        updateCartUI();
    }
    showToast(`${product.name} added to cart!`, 'success');
}

async function updateCartQty(idx, delta) {
    if (idx < 0 || idx >= cart.length) return;
    const newQty = cart[idx].quantity + delta;
    if (newQty <= 0) {
        cart.splice(idx, 1);
    } else {
        cart[idx].quantity = newQty;
    }
    saveCart();
    if (deliveryOption === 'delivery' && deliveryAddress) {
        await recalcDeliveryFee(true);
    }
    renderProducts();
}

async function removeCartItem(idx) {
    cart.splice(idx, 1);
    saveCart();
    if (deliveryOption === 'delivery' && deliveryAddress) {
        await recalcDeliveryFee(true);
    }
    renderProducts();
}

function updateCartUI() {
    const subtotal = cart.reduce((s, i) => s + i.price * i.quantity, 0);
    let total = subtotal;
    if (deliveryOption === 'delivery' && deliveryAddress && deliveryFee) total += deliveryFee;
    document.getElementById('cart-subtotal').innerText = `₦${subtotal.toLocaleString()}`;
    const totalSpan = document.getElementById('cart-total');
    if (!totalSpan.innerHTML.includes('loader')) totalSpan.innerText = `₦${total.toLocaleString()}`;
    const feeRow = document.getElementById('delivery-fee-row');
    if (deliveryOption === 'delivery' && deliveryAddress && deliveryFee) { feeRow.classList.remove('hidden');
        document.getElementById('cart-delivery-fee').innerText = `₦${deliveryFee.toLocaleString()}`; } else feeRow
        .classList.add('hidden');
    const count = cart.reduce((s, i) => s + i.quantity, 0);
    document.getElementById('cart-count-badge').innerText = count;
    const container = document.getElementById('cart-items-list');
    if (!container) return;
    if (cart.length === 0) {
        container.innerHTML =
            '<div class="text-center text-gray-400 py-8"><i class="fa-regular fa-basket-shopping text-4xl mb-2"></i><p>Cart is empty</p></div>';
        return;
    }

    container.innerHTML = cart.map((item, idx) => {
        const sub = item.price * item.quantity;
        return `<div class="flex flex-col sm:flex-row justify-between items-start sm:items-center bg-gray-50 p-3 rounded-xl gap-2">
              <div class="flex-1 min-w-0">
                <span class="font-medium text-gray-800 truncate block">${escapeHtml(item.name)}</span>
                <div class="flex items-center gap-2 mt-1">
                  <button class="cart-qty-btn qty-btn" data-index="${idx}" data-delta="-1" aria-label="Decrease quantity">−</button>
                  <span class="qty-display">${item.quantity}</span>
                  <button class="cart-qty-btn qty-btn orange" data-index="${idx}" data-delta="1" aria-label="Increase quantity">+</button>
                  <span class="text-xs text-gray-400 ml-1">× ₦${item.price.toLocaleString()}</span>
                </div>
              </div>
              <div class="flex items-center gap-3 w-full sm:w-auto justify-between sm:justify-end">
                <span class="font-mono text-orange-600 font-semibold">₦${sub.toLocaleString()}</span>
                <button class="cart-remove-btn text-red-400 hover:text-red-600 transition" data-index="${idx}"><i class="fa-regular fa-trash-can"></i></button>
              </div>
            </div>`;
    }).join('');
}

async function recalcDeliveryFee(showFeedback = true) {
    if (deliveryOption !== 'delivery' || !deliveryAddress || cart.length === 0) {
        if (cart.length === 0) { deliveryFee = 0;
            handlingFee = 0;
            isDeliveryEstimated = false;
            updateCartUI(); }
        return;
    }
    if (isRecalcInProgress) return;
    const currentCartSnapshot = JSON.stringify(cart);
    isRecalcInProgress = true;
    if (showFeedback) setCartTotalLoading(true);
    try {
        const items = cart.map(i => ({ inventory_id: i.id, quantity: i.quantity }));
        const res = await apiCall('/delivery/estimate', {
            method: 'POST',
            body: JSON.stringify({ address: deliveryAddress, items })
        });
        deliveryFee = res.delivery_fee_naira || 0;
        handlingFee = res.handling_fee_naira || 0;
        isDeliveryEstimated = true;
        const feeDiv = document.getElementById('delivery-fee-estimate');
        if (feeDiv && showFeedback) feeDiv.innerHTML = `🚚 Delivery fee: ₦${deliveryFee.toLocaleString()} | Handling: ₦${handlingFee.toLocaleString()}`;
        updateCartUI();
        if (showFeedback) showToast("Delivery fee updated", 'success');
    } catch (e) {
        if (showFeedback) showToast(e.message, 'error');
        else console.warn("Delivery recalc failed:", e);
        isDeliveryEstimated = false;
    } finally {
        isRecalcInProgress = false;
        if (JSON.stringify(cart) !== currentCartSnapshot && cart.length > 0) {
            recalcDeliveryFee(true);
        }
        if (showFeedback) setCartTotalLoading(false);
    }
}

// ============================================================
//  CHECKOUT / CONFIRMATION
// ============================================================
function showConfirmation(orderData) {
    const container = document.getElementById('confirmation-details');
    if (!container) return;

    const itemsHtml = orderData.items.map(item =>
        `<div class="flex justify-between border-b border-gray-100 py-2"><span>${escapeHtml(item.name)} × ${item.quantity}</span><span class="font-mono">₦${(item.price * item.quantity).toLocaleString()}</span></div>`
    ).join('');

    let feeHtml = '';
    if (orderData.deliveryOption === 'delivery') {
        feeHtml += `<div class="flex justify-between text-sm"><span class="text-gray-600">Delivery Address</span><span class="text-right max-w-[60%]">${escapeHtml(orderData.deliveryAddress || 'N/A')}</span></div>`;
        if (orderData.deliveryFee) {
            feeHtml +=
                `<div class="flex justify-between text-sm"><span class="text-gray-600">Delivery Fee</span><span>₦${(orderData.deliveryFee || 0).toLocaleString()}</span></div>`;
        }
        if (orderData.handlingFee) {
            feeHtml +=
                `<div class="flex justify-between text-sm"><span class="text-gray-600">Handling Fee</span><span>₦${(orderData.handlingFee || 0).toLocaleString()}</span></div>`;
        }
    }

    container.innerHTML = `
                <div class="bg-gray-50 rounded-xl p-4 space-y-2">
                    <div class="flex justify-between text-sm flex-wrap"><span class="text-gray-600">Receipt Number</span><span class="font-mono font-bold text-orange-600">${escapeHtml(orderData.receiptNumber || 'N/A')}</span></div>
                    <div class="flex justify-between text-sm flex-wrap"><span class="text-gray-600">Date</span><span>${new Date(orderData.createdAt || Date.now()).toLocaleString()}</span></div>
                    <div class="flex justify-between text-sm flex-wrap"><span class="text-gray-600">Payment Method</span><span>${escapeHtml(orderData.paymentMethod || 'Paystack')}</span></div>
                    <div class="flex justify-between text-sm flex-wrap"><span class="text-gray-600">Delivery Option</span><span>${orderData.deliveryOption === 'delivery' ? '🚚 Delivery' : '📦 Pickup'}</span></div>
                    ${feeHtml}
                </div>
                <div class="border-t border-gray-200 pt-3">
                    <div class="font-semibold mb-2">Order Items</div>
                    ${itemsHtml}
                </div>
                <div class="border-t border-gray-200 pt-3 space-y-1">
                    <div class="flex justify-between text-sm"><span class="text-gray-600">Subtotal</span><span>₦${(orderData.subtotal || 0).toLocaleString()}</span></div>
                    ${orderData.deliveryOption === 'delivery' && orderData.deliveryFee ? `<div class="flex justify-between text-sm"><span class="text-gray-600">Delivery Fee</span><span>₦${(orderData.deliveryFee || 0).toLocaleString()}</span></div>` : ''}
                    ${orderData.deliveryOption === 'delivery' && orderData.handlingFee ? `<div class="flex justify-between text-sm"><span class="text-gray-600">Handling Fee</span><span>₦${(orderData.handlingFee || 0).toLocaleString()}</span></div>` : ''}
                    <div class="flex justify-between font-bold text-lg border-t border-gray-200 pt-2 mt-1"><span>Total</span><span class="text-orange-600">₦${(orderData.totalAmount || 0).toLocaleString()}</span></div>
                </div>
            `;

    showView('confirmation');
}

async function checkout() {
    const btn = document.getElementById('checkout-btn');
    
    if (!cart.length) {
        showToast("Cart is empty", 'error');
        return;
    }
    if (!token) {
        showAuthModal();
        return;
    }

    if (deliveryOption === 'delivery') {
        if (!deliveryAddress) {
            showToast("Please enter your delivery address first.", 'error');
            return;
        }
        if (!isDeliveryEstimated) {
            showToast("Please click 'Save & Estimate Delivery' to calculate your delivery fee.", 'error');
            return;
        }
    }

    setButtonLoading(btn, true);
    try {
        if (token && !userProfile?.email) {
            try {
                await loadUser();
            } catch (e) {
                console.warn("Profile refresh failed", e);
            }
        }

        const payMethod = document.getElementById('payment-method').value;
        const items = cart.map(i => ({ inventory_id: i.id, quantity: i.quantity }));
        const subtotal = cart.reduce((s, i) => s + i.price * i.quantity, 0);
        let total = subtotal;
        let deliveryFeeToUse = 0,
            handlingFeeToUse = 0;
        if (deliveryOption === 'delivery') {
            deliveryFeeToUse = deliveryFee;
            handlingFeeToUse = handlingFee;
            total += deliveryFeeToUse + handlingFeeToUse;
        }

        const payload = {
            items,
            customer_name: userProfile?.first_name || null,
            customer_email: userProfile?.email || null,
            customer_phone: userProfile?.phone || null,
            payment_method: payMethod,
            callback_url: window.location.href.split('?')[0]
        };

        if (deliveryOption === 'delivery') {
            payload.shipping_address = deliveryAddress;
            payload.delivery_fee = deliveryFeeToUse;
            payload.handling_fee = handlingFeeToUse;
        }

        const orderSnapshot = {
            items: cart.map(i => ({ name: i.name, price: i.price, quantity: i.quantity })),
            totalAmount: total,
            subtotal: subtotal,
            deliveryFee: deliveryFeeToUse,
            handlingFee: handlingFeeToUse,
            deliveryOption: deliveryOption,
            deliveryAddress: deliveryOption === 'delivery' ? deliveryAddress : null,
            paymentMethod: payMethod,
            receiptNumber: 'PENDING',
            createdAt: new Date().toISOString()
        };

        if (payMethod === 'cash') {
            const result = await apiCall('/pos/terminal/checkout', {
                method: 'POST',
                body: JSON.stringify(payload)
            });
            orderSnapshot.receiptNumber = result.receipt_number || 'N/A';
            cart = [];
            saveCart();
            setDeliveryOpt('pickup');
            renderProducts();
            document.getElementById('cart-drawer').classList.add('translate-x-full');
            showToast(`✅ Checkout success! Receipt: ${result.receipt_number}`, 'success');
            showConfirmation(orderSnapshot);
        } else {
            const result = await apiCall('/pos/checkout', {
                method: 'POST',
                body: JSON.stringify(payload)
            });
            if (result.payment_url) {
                orderSnapshot.receiptNumber = result.receipt_number || 'PENDING';
                localStorage.setItem('pending_order', JSON.stringify(orderSnapshot));
                localStorage.setItem('pending_payment', 'true');
                window.location.replace(result.payment_url);
            } else {
                showToast("Payment initiation failed", 'error');
            }
        }
    } catch (e) {
        showToast(e.message, 'error');
    } finally {
        setButtonLoading(btn, false);
    }
}

// ============================================================
//  USER / AUTH
// ============================================================
function showAuthModal() { document.getElementById('auth-modal').classList.remove('hidden'); }

function hideAuthModal() { document.getElementById('auth-modal').classList.add('hidden'); }

async function loadUserLoyalty() {
    if (!token) return;
    try {
        const me = await apiCall('/auth/me');
        let points = 0,
            tier = 'bronze';
        try {
            const context = await apiCall(
                `/support/customer-context?target_user_id=${me.user_id}`);
            if (context.loyalty) { points = context.loyalty.current_points || 0;
                tier = context.loyalty.tier || 'bronze'; }
        } catch (e) { points = me.loyalty_points || 0;
            tier = me.loyalty_tier || 'bronze'; }
        userLoyalty = { points, tier };
        const pointsSpan = document.getElementById('user-points');
        const tierSpan = document.getElementById('user-tier');
        const loyaltyDiv = document.getElementById('loyalty-info-dropdown');
        if (pointsSpan) pointsSpan.innerText = userLoyalty.points;
        if (tierSpan) tierSpan.innerText = userLoyalty.tier;
        if (loyaltyDiv) loyaltyDiv.classList.remove('hidden');
    } catch (e) {
        console.warn(e);
    }
}

async function loadUser() {
    if (!token) return;
    try {
        const me = await apiCall('/auth/me');
        userProfile = me;
        const displayName = me.first_name || me.email || 'User';
        document.getElementById('user-info-dropdown').innerHTML = `<i class="fa-regular fa-user"></i> ${escapeHtml(displayName)}`;
        document.getElementById('logout-dropdown').classList.remove('hidden');
        await loadUserLoyalty();
    } catch (e) {
        userProfile = null;
        document.getElementById('user-info-dropdown').innerHTML = 'Guest';
        document.getElementById('logout-dropdown').classList.add('hidden');
    }
}

async function logout() {
    try { await apiCall('/auth/logout', { method: 'POST' }); } catch (e) {}
    localStorage.clear();
    token = null;
    userProfile = null;
    cart = [];
    saveCart();
    location.reload();
}

async function demoLogin() {
    const btn = document.getElementById('demo-access');
    setButtonLoading(btn, true);
    try {
        const res = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: 'demo@kevsdigital.com', password: 'KevsDemo2026!' })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail);
        token = data.access_token;
        localStorage.setItem('access_token', token);
        localStorage.setItem('refresh_token', data.refresh_token);
        await loadUser();
        hideAuthModal();
        showToast("Demo login success", 'success');
        showView('shop');
    } catch (e) {
        alert(e.message);
    } finally {
        setButtonLoading(btn, false);
    }
}

// ============================================================
//  TICKETS
// ============================================================
async function loadTickets() {
    if (!token) { showAuthModal();
        showToast("Please login", 'error'); return; }
    const container = document.getElementById('tickets-list');
    container.innerHTML = '<div class="text-center py-10"><i class="fa-solid fa-spinner fa-pulse"></i> Loading tickets...</div>';
    try {
        const data = await apiCall('/support/tickets');
        const tickets = data.tickets || [];
        if (tickets.length === 0) {
            container.innerHTML =
                '<div class="bg-white rounded-xl p-8 text-center text-gray-500"><i class="fa-regular fa-ticket-alt text-4xl mb-2"></i><p>No support tickets yet. Start a chat with AI.</p></div>';
            return;
        }
        container.innerHTML = tickets.map(t =>
            `<div class="ticket-card bg-white rounded-xl p-4 shadow-sm border border-gray-100"><div class="flex justify-between items-start"><div><span class="text-xs font-mono text-blue-500">#${t.id.slice(0,8)}</span><span class="ml-2 text-xs uppercase px-2 py-0.5 rounded-full ${t.status==='open'?'bg-amber-100 text-amber-700':'bg-green-100 text-green-700'}">${t.status}</span></div><span class="text-xs text-gray-400">Priority: ${t.priority}</span></div><p class="font-semibold mt-1">${escapeHtml(t.subject || 'General inquiry')}</p><p class="text-sm text-gray-600 mt-1">${escapeHtml(t.message?.substring(0,100) || '')}</p>${t.resolution ? `<div class="mt-2 text-xs bg-gray-50 p-2 rounded"><span class="font-medium">Resolution:</span> ${escapeHtml(t.resolution)}</div>` : ''}<div class="mt-2 text-xs text-gray-400">Created: ${new Date(t.created_at).toLocaleString()}</div></div>`
        ).join('');
    } catch (e) { container.innerHTML = `<div class="text-red-500 p-4">Error: ${e.message}</div>`; }
}

// ============================================================
//  CHAT
// ============================================================
let chatMessagesDiv = null,
    chatSessionId = sessionId;

function addChatMsg(sender, text, isTypingIndicator = false) {
    if (!chatMessagesDiv) return;
    const row = document.createElement('div');
    row.className = `chat-msg ${sender === 'user' ? 'user' : 'assistant'}`;

    if (sender === 'assistant') {
        const avatar = document.createElement('div');
        avatar.className = 'chat-msg-avatar';
        avatar.innerHTML = '<i class="fa-solid fa-sparkles"></i>';
        row.appendChild(avatar);
    }

    const bubble = document.createElement('div');
    bubble.className = 'chat-msg-bubble';
    if (isTypingIndicator && sender === 'assistant') {
        bubble.innerHTML = '<div class="thinking-dots"><span></span><span></span><span></span></div>';
    } else {
        bubble.innerText = text;
    }
    row.appendChild(bubble);
    chatMessagesDiv.appendChild(row);
    chatMessagesDiv.scrollTop = chatMessagesDiv.scrollHeight;
    return row;
}

async function sendChatMessage() {
    const input = document.getElementById('chat-input');
    const msg = input.value.trim();
    if (!msg) return;
    addChatMsg('user', msg);
    input.value = '';
    addChatMsg('assistant', '', true);
    const lastMsgDiv = chatMessagesDiv.lastChild;
    try {
        const data = await apiCall('/support/chat-stream', { method: 'POST', body: JSON.stringify({ session_id: chatSessionId,
                message: msg }) });
        if (lastMsgDiv && lastMsgDiv.classList.contains('bg-gray-100')) lastMsgDiv.remove();
        addChatMsg('assistant', data.response || "Got it!");
    } catch (e) {
        if (lastMsgDiv && lastMsgDiv.classList.contains('bg-gray-100')) lastMsgDiv.remove();
        addChatMsg('assistant', "Sorry, AI is busy.");
    }
}

function initChat() {
    chatMessagesDiv = document.getElementById('chat-messages');
    if (chatMessagesDiv && chatMessagesDiv.children.length === 0) {
        addChatMsg('assistant', "Hi! I'm Penafort AI. I can help you find products, compare options, or get help with an order. What are you shopping for?");
    }
}

function sendQuickChatPrompt(message) {
    const input = document.getElementById('chat-input');
    const modal = document.getElementById('chat-modal');
    if (!input || !modal) return;
    modal.classList.add('active');
    initChat();
    input.value = message;
    sendChatMessage();
}

// ============================================================
//  DELIVERY OPTIONS / GPS (Update #10: persist in localStorage)
// ============================================================
function setDeliveryOpt(opt) {
    deliveryOption = opt;
    localStorage.setItem('pf_delivery_option', opt);
    const pickup = document.getElementById('pickup-option'),
        deliv = document.getElementById('delivery-option');
    if (opt === 'pickup') {
        pickup.classList.add('bg-orange-500', 'text-white');
        deliv.classList.remove('bg-orange-500', 'text-white');
        deliv.classList.add('bg-gray-200');
        document.getElementById('delivery-address-section').classList.add('hidden');
        deliveryFee = 0;
        deliveryAddress = '';
        localStorage.removeItem('pf_delivery_address');
        isDeliveryEstimated = false;
        updateCartUI();
    } else {
        deliv.classList.add('bg-orange-500', 'text-white');
        pickup.classList.remove('bg-orange-500', 'text-white');
        pickup.classList.add('bg-gray-200');
        document.getElementById('delivery-address-section').classList.remove('hidden');
        if (deliveryAddress) {
            // restore address from localStorage
            const savedAddr = localStorage.getItem('pf_delivery_address');
            if (savedAddr) {
                deliveryAddress = savedAddr;
                document.getElementById('delivery-address').value = savedAddr;
                recalcDeliveryFee(true);
            }
        }
        updateCartUI();
    }
}

function hideAddrSugg() {
    const sugg = document.getElementById('cart-address-suggestions');
    sugg.classList.add('hidden');
    sugg.innerHTML = '';
}

function showAddrSugg(items) {
    const sugg = document.getElementById('cart-address-suggestions');
    if (!items.length) return hideAddrSugg();
    sugg.innerHTML = items.map(item =>
            `<div class="suggestion-item">${item.display_name.split(',').slice(0,3).join(',')}</div>`).join('');
    sugg.classList.remove('hidden');
    document.querySelectorAll('#cart-address-suggestions .suggestion-item').forEach((el, idx) => {
        el.addEventListener('click', () => {
            const addrInput = document.getElementById('delivery-address');
            addrInput.value = items[idx].display_name;
            deliveryAddress = items[idx].display_name;
            localStorage.setItem('pf_delivery_address', deliveryAddress);
            hideAddrSugg();
        });
    });
}

async function fetchAddr(q) {
    if (q.length < 3) return hideAddrSugg();
    const resp = await fetch(
        `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(q)}&format=json&limit=5`, { headers: { 'User-Agent': 'KevsStore' } }
    );
    const data = await resp.json();
    showAddrSugg(data);
}

async function estimateDelivery() {
    if (!deliveryAddress) return showToast("Enter address", 'error');
    const btn = document.getElementById('save-address-btn');
    setButtonLoading(btn, true);
    try {
        await recalcDeliveryFee(true);
        // Persist address on successful estimation
        localStorage.setItem('pf_delivery_address', deliveryAddress);
    } catch (e) {
        showToast(e.message, 'error');
    } finally {
        setButtonLoading(btn, false);
    }
}

// ============================================================
//  HERO SLIDER
// ============================================================
function initHeroSlider() {
    const slider = document.getElementById('heroSlider'),
        slides = document.querySelectorAll('.hero-slide');
    const prev = document.getElementById('sliderPrev'),
        next = document.getElementById('sliderNext'),
        dots = document.getElementById('sliderDots');
    if (!slider || slides.length === 0) return;
    let index = 0,
        total = slides.length,
        autoInterval;

    function updateSlider() { slider.style.transform = `translateX(-${index * 100}%)`;
        document.querySelectorAll('.slider-dot').forEach((dot, i) => { dot.classList.toggle('active', i === index); }); }

    function goTo(i) { index = (i + total) % total;
        updateSlider();
        resetAuto(); }

    function nextSlide() { goTo(index + 1); }

    function prevSlide() { goTo(index - 1); }

    function resetAuto() { if (autoInterval) clearInterval(autoInterval);
        autoInterval = setInterval(nextSlide, 5000); }
    dots.innerHTML = '';
    for (let i = 0; i < total; i++) { const dot = document.createElement('div');
        dot.classList.add('slider-dot'); if (i === 0) dot.classList.add('active');
        dot.addEventListener('click', () => goTo(i));
        dots.appendChild(dot); }
    prev?.addEventListener('click', prevSlide);
    next?.addEventListener('click', nextSlide);
    const heroSection = document.querySelector('.hero-slider');
    heroSection?.addEventListener('mouseenter', () => clearInterval(autoInterval));
    heroSection?.addEventListener('mouseleave', resetAuto);
    resetAuto();
}

// ============================================================
//  PAYMENT RETURN HANDLER
// ============================================================
function handlePaymentReturn() {
    const urlParams = new URLSearchParams(window.location.search);
    const reference = urlParams.get('reference') || urlParams.get('trxref');
    const paymentSuccess = urlParams.get('payment') === 'success' || !!reference;
    const pendingOrder = localStorage.getItem('pending_order');
    const pendingFlag = localStorage.getItem('pending_payment') === 'true';

    if (pendingOrder && paymentSuccess && pendingFlag) {
        try {
            const orderData = JSON.parse(pendingOrder);
            if (reference && orderData.receiptNumber === 'PENDING') {
                orderData.receiptNumber = 'PAYSTACK-' + reference.slice(0, 10);
            }
            cart = [];
            saveCart();
            setDeliveryOpt('pickup');
            renderProducts();
            showConfirmation(orderData);
            showToast("✅ Payment successful! Your order is confirmed.", 'success');
            localStorage.removeItem('pending_order');
            localStorage.removeItem('pending_payment');
            isDeliveryEstimated = false;
            window.history.replaceState({}, '', window.location.pathname);
        } catch (e) {
            console.warn("Failed to parse pending order", e);
            showView('shop');
            showToast("Payment successful! Check your email for receipt.", 'success');
            localStorage.removeItem('pending_order');
            localStorage.removeItem('pending_payment');
            window.history.replaceState({}, '', window.location.pathname);
        }
    } else if (paymentSuccess && !pendingOrder) {
        showToast("Payment successful! Check your email for receipt.", 'success');
        localStorage.removeItem('pending_payment');
        window.history.replaceState({}, '', window.location.pathname);
    }
}

// ============================================================
//  DEEP LINKS
// ============================================================
function handleDeepLinks() {
    const chatModal = document.getElementById('chat-modal');
    const chatInput = document.getElementById('chat-input');
    if (!chatModal || !chatInput) return;

    const urlParams = new URLSearchParams(window.location.search);
    const page = urlParams.get('page');
    const shareTitle = urlParams.get('share_title');
    const shareText = urlParams.get('share_text');
    const shareUrl = urlParams.get('share_url');

    function openChatAndAutoSend(message) {
        if (!chatModal.classList.contains('active')) {
            chatModal.classList.add('active');
        }
        initChat();
        if (message) {
            chatInput.value = message;
            setTimeout(() => { sendChatMessage(); }, 500);
        }
    }

    if (page === 'orders') {
        if (token) showView('tickets');
        else showAuthModal();
        return;
    }
    if (page === 'support') {
        openChatAndAutoSend(null);
        return;
    }
    if (shareTitle || shareText || shareUrl) {
        let message = '';
        if (shareText) message = `I found this: ${shareText}`;
        else if (shareUrl) message = `Can you help me with this: ${shareUrl}`;
        else if (shareTitle) message = `Shared: ${shareTitle}`;
        if (message) openChatAndAutoSend(message);
    }
}

// ============================================================
//  DOM CONTENT LOADED - INITIALIZATION
// ============================================================
document.addEventListener('DOMContentLoaded', async function() {

    // --- Static Event Listeners ---

    // Logo
    document.getElementById('marketplace-logo')?.addEventListener('click', () => showView('shop'));

    // Cart icon
    document.getElementById('cart-icon-btn')?.addEventListener('click', () => document.getElementById('cart-drawer').classList.remove('translate-x-full'));
    document.getElementById('close-drawer')?.addEventListener('click', () => document.getElementById('cart-drawer').classList.add('translate-x-full'));

    // User menu
    document.getElementById('user-menu-btn')?.addEventListener('click', (e) => {
        e.stopPropagation();
        document.getElementById('user-dropdown')?.classList.toggle('hidden');
    });
    document.addEventListener('click', (e) => {
        if (!e.target.closest('#user-menu-btn') && !e.target.closest('#user-dropdown')) {
            document.getElementById('user-dropdown')?.classList.add('hidden');
        }
    });

    // Dropdown actions
    document.getElementById('login-dropdown-btn')?.addEventListener('click', showAuthModal);
    document.getElementById('track-order-dropdown')?.addEventListener('click', () => document.getElementById('track-modal').classList.add('active'));
    document.getElementById('complaints-dropdown')?.addEventListener('click', () => showView('tickets'));
    document.getElementById('logout-dropdown')?.addEventListener('click', logout);

    // Auth Modal
    document.getElementById('close-auth-modal')?.addEventListener('click', hideAuthModal);
    document.getElementById('toggle-auth-mode')?.addEventListener('click', () => {
        const reg = document.getElementById('reg-extra');
        const isReg = reg.classList.contains('hidden');
        reg.classList.toggle('hidden');
        document.getElementById('auth-submit').innerText = isReg ? "Create Profile" : "Sign In";
        document.getElementById('modal-title').innerText = isReg ? "Register Organization" : "Sign In";
    });
    document.getElementById('auth-submit')?.addEventListener('click', async function() {
        const btn = this;
        setButtonLoading(btn, true);
        try {
            const email = document.getElementById('auth-email').value,
                pwd = document.getElementById('auth-password').value;
            if (!email || !pwd) { alert("Email & password required"); return; }
            const isReg = !document.getElementById('reg-extra').classList.contains('hidden');
            if (isReg) {
                const fname = document.getElementById('first-name').value,
                    lname = document.getElementById('last-name').value,
                    phone = document.getElementById('phone-number').value;
                if (!fname || !lname || !phone) { alert("First name, last name, phone required"); return; }
                const invite = document.getElementById('invite-code').value.trim();
                const orgName = document.getElementById('org-name').value.trim();
                const loc = document.getElementById('org-location').value.trim(),
                    niche = document.getElementById('org-niche').value.trim();
                if (!invite && (!orgName || !loc || !niche)) { alert("Invite code or org details required"); return; }
                const payload = { email, password: pwd, first_name: fname, last_name: lname, phone };
                if (invite) payload.invite_code = invite;
                else { payload.org_name = orgName;
                    payload.location = loc;
                    payload.niche = niche;
                    payload.budget = parseInt(document.getElementById('budget').value) || 0; }
                await apiCall('/auth/register', { method: 'POST', body: JSON.stringify(payload) });
                alert("Registration success! Please sign in.");
                document.getElementById('reg-extra').classList.add('hidden');
                return;
            }
            const loginRes = await fetch(`${API_BASE}/auth/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password: pwd })
            });
            const data = await loginRes.json();
            if (!loginRes.ok) throw new Error(data.detail);
            token = data.access_token;
            localStorage.setItem('access_token', token);
            localStorage.setItem('refresh_token', data.refresh_token);
            await loadUser();
            hideAuthModal();
            showToast("Logged in", 'success');
            showView('shop');
        } catch (e) {
            alert(e.message);
        } finally {
            setButtonLoading(btn, false);
        }
    });
    document.getElementById('demo-access')?.addEventListener('click', demoLogin);

    // Confirmation View buttons
    document.getElementById('continue-shopping-btn')?.addEventListener('click', () => showView('shop'));
    document.getElementById('track-order-confirm-btn')?.addEventListener('click', () => document.getElementById('track-modal').classList.add('active'));

    // Bottom Nav (App-only)
    document.getElementById('nav-support-chat')?.addEventListener('click', () => {
        document.getElementById('chat-modal').classList.add('active');
        initChat();
    });
    document.getElementById('nav-track')?.addEventListener('click', () => document.getElementById('track-modal').classList.add('active'));
    document.getElementById('nav-ai-helper')?.addEventListener('click', () => document.getElementById('product-search').focus());
    document.getElementById('nav-cart')?.addEventListener('click', () => document.getElementById('cart-drawer').classList.remove('translate-x-full'));

    // Hero Buttons (Multiple)
    document.querySelectorAll('.hero-shop-btn').forEach(btn => btn.addEventListener('click', (e) => {
        e.preventDefault();
        showView('shop');
        const target = document.getElementById('products-grid') || document.getElementById('shop-view');
        if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        setTimeout(() => {
            const input = document.getElementById('product-search');
            if (input && (window.innerWidth < 768 || document.documentElement.classList.contains('pwa-mobile'))) {
                input.focus({ preventScroll: true });
            }
        }, 500);
    }));
    document.querySelectorAll('.hero-track-btn').forEach(btn => btn.addEventListener('click', () => document.getElementById('track-modal').classList.add('active')));
    document.querySelectorAll('.hero-tickets-btn').forEach(btn => btn.addEventListener('click', () => showView('tickets')));
    document.querySelectorAll('.hero-chat-btn').forEach(btn => btn.addEventListener('click', () => {
        document.getElementById('chat-modal').classList.add('active');
        initChat();
    }));

    // Product Modal controls
    document.getElementById('close-product-modal')?.addEventListener('click', closeProductModal);
    document.getElementById('modal-close-btn')?.addEventListener('click', closeProductModal);
    document.getElementById('modal-qty-minus')?.addEventListener('click', () => {
        if (modalQuantity > 1) { modalQuantity--;
            updateModalQtyDisplay(); }
    });
    document.getElementById('modal-qty-plus')?.addEventListener('click', () => {
        const stock = currentProductForModal?.current_qty || 999;
        if (modalQuantity < stock) { modalQuantity++;
            updateModalQtyDisplay(); } else { showToast(`Only ${stock} available`, 'error'); }
    });
    document.getElementById('modal-add-to-cart')?.addEventListener('click', async () => {
        if (currentProductForModal) {
            await addToCart({
                id: currentProductForModal.id,
                name: currentProductForModal.description,
                price: currentProductForModal.price_naira
            }, modalQuantity);
            closeProductModal();
        }
    });

    // Track Modal
    document.getElementById('close-track-modal')?.addEventListener('click', () => {
        document.getElementById('track-modal').classList.remove('active');
        document.getElementById('track-result').classList.add('hidden');
    });
    document.getElementById('track-submit')?.addEventListener('click', async () => {
        const receipt = document.getElementById('track-receipt').value.trim(),
            email = document.getElementById('track-email').value.trim();
        if (!receipt || !email) { showToast("Receipt and email required", 'error'); return; }
        const resultDiv = document.getElementById('track-result');
        resultDiv.innerHTML = '<i class="fa-solid fa-spinner fa-pulse"></i> Tracking...';
        resultDiv.classList.remove('hidden');
        try {
            const data = await apiCall(`/track-order?receipt_number=${receipt}&email=${email}`);
            const statusMap = { pending: "⏳ Pending", completed: "📦 Ready", shipped: "🚚 In transit",
                delivered: "✅ Delivered" };
            resultDiv.innerHTML =
                `<div class="bg-gray-100 p-3 rounded-lg space-y-1 text-sm"><div><strong>Receipt:</strong> ${data.receipt_number}</div><div><strong>Total:</strong> ₦${data.total_amount?.toLocaleString()}</div><div><strong>Status:</strong> <span class="text-orange-600 font-semibold">${statusMap[data.shipping_status] || data.shipping_status}</span></div><div><strong>Carrier:</strong> ${data.shipping_carrier || '—'}</div><div><strong>Tracking #:</strong> ${data.tracking_number || 'N/A'}</div></div>`;
        } catch (e) { resultDiv.innerHTML = `<div class="text-red-500">${e.message}</div>`; }
    });

    // Search
    const searchInput = document.getElementById('product-search');
    const searchClear = document.getElementById('search-clear');
    let searchDebounce;
    if (searchInput) {
        searchInput.addEventListener('input', () => {
            clearTimeout(searchDebounce);
            searchDebounce = setTimeout(() => {
                searchQuery = searchInput.value;
                currentPage = 1;
                loadProducts();
                if (searchClear) searchClear.style.display = searchQuery ? 'block' : 'none';
            }, 300);
        });
    }
    if (searchClear) {
        searchClear.addEventListener('click', () => {
            searchInput.value = '';
            searchQuery = '';
            currentPage = 1;
            loadProducts();
            searchClear.style.display = 'none';
            searchInput.focus();
        });
    }

    // Category & Refresh
    const catSelect = document.getElementById('category-select');
    if (catSelect) {
        catSelect.addEventListener('change', () => {
            selectedCategory = catSelect.value;
            currentPage = 1;
            loadProducts();
        });
    }
    document.getElementById('refresh-categories-btn')?.addEventListener('click', async () => {
        await loadCategories();
        showToast(`Categories reloaded (${categories.length})`, 'success');
    });

    // Storefront navigation
    const goToSection = (id) => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    document.getElementById('nav-deals')?.addEventListener('click', () => goToSection('deals-section'));
    document.getElementById('nav-popular')?.addEventListener('click', () => goToSection('products-section'));
    document.getElementById('nav-needs')?.addEventListener('click', () => goToSection('needs-section'));
    document.getElementById('nav-shop-categories')?.addEventListener('click', () => goToSection('categories-section'));
    document.getElementById('view-all-categories')?.addEventListener('click', () => goToSection('products-section'));
    document.getElementById('view-all-products')?.addEventListener('click', () => goToSection('products-section'));
    document.getElementById('hero-categories-btn')?.addEventListener('click', () => goToSection('categories-section'));
    document.getElementById('nav-track-order')?.addEventListener('click', () => document.getElementById('track-modal')?.classList.add('active'));
    document.getElementById('announcement-track-btn')?.addEventListener('click', () => document.getElementById('track-modal')?.classList.add('active'));
    document.getElementById('nav-support')?.addEventListener('click', () => {
        document.getElementById('chat-modal')?.classList.add('active');
        initChat();
    });
    document.getElementById('search-submit-btn')?.addEventListener('click', () => {
        document.getElementById('product-search')?.dispatchEvent(new Event('input', { bubbles: true }));
        goToSection('products-section');
    });

    // Mobile category selector mirrors the main category selector.
    document.getElementById('category-select-mobile')?.addEventListener('change', (e) => {
        selectedCategory = e.target.value;
        const mainSelect = document.getElementById('category-select');
        if (mainSelect) mainSelect.value = selectedCategory;
        currentPage = 1;
        loadProducts();
        goToSection('products-section');
    });

    document.getElementById('category-cards')?.addEventListener('click', (e) => {
        const card = e.target.closest('[data-category]');
        if (!card) return;
        selectedCategory = card.dataset.category || '';
        const mainSelect = document.getElementById('category-select');
        const mobileSelect = document.getElementById('category-select-mobile');
        if (mainSelect) mainSelect.value = selectedCategory;
        if (mobileSelect) mobileSelect.value = selectedCategory;
        currentPage = 1;
        loadProducts();
        goToSection('products-section');
    });

    document.querySelectorAll('.pf-need-card').forEach(card => {
        card.addEventListener('click', () => {
            const need = card.dataset.need || '';
            const searchMap = {
                breakfast: 'milk',
                kitchen: 'rice',
                cleaning: 'clean',
                party: 'drink'
            };
            const input = document.getElementById('product-search');
            if (input) input.value = searchMap[need] || '';
            searchQuery = searchMap[need] || '';
            currentPage = 1;
            loadProducts();
            goToSection('products-section');
        });
    });

    document.getElementById('footer-track')?.addEventListener('click', (e) => {
        e.preventDefault();
        document.getElementById('track-modal')?.classList.add('active');
    });
    document.getElementById('footer-support')?.addEventListener('click', (e) => {
        e.preventDefault();
        document.getElementById('chat-modal')?.classList.add('active');
        initChat();
    });
    document.getElementById('footer-tickets')?.addEventListener('click', (e) => {
        e.preventDefault();
        showView('tickets');
    });

    // Pagination (Delegation)
    document.getElementById('pagination-container')?.addEventListener('click', function(e) {
        const btn = e.target.closest('.page-btn');
        if (!btn) return;
        const page = parseInt(btn.dataset.page);
        if (!isNaN(page) && page !== currentPage) {
            currentPage = page;
            loadProducts();
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
    });

    // Delivery Options
    document.getElementById('pickup-option')?.addEventListener('click', () => setDeliveryOpt('pickup'));
    document.getElementById('delivery-option')?.addEventListener('click', () => setDeliveryOpt('delivery'));

    // Address & GPS
    const addrInput = document.getElementById('delivery-address');
    const addrSugg = document.getElementById('cart-address-suggestions');
    let addrDeb;
    if (addrInput) {
        addrInput.addEventListener('input', (e) => {
            clearTimeout(addrDeb);
            addrDeb = setTimeout(() => fetchAddr(e.target.value), 400);
        });
        addrInput.addEventListener('blur', () => {
            setTimeout(hideAddrSugg, 300);
        });
    }
    document.getElementById('gps-locate-cart')?.addEventListener('click', function() {
        const btn = this;
        if (navigator.geolocation) {
            setButtonLoading(btn, true);
            navigator.geolocation.getCurrentPosition(
                async pos => {
                    try {
                        const rev = await fetch(
                            `https://nominatim.openstreetmap.org/reverse?lat=${pos.coords.latitude}&lon=${pos.coords.longitude}&format=json`, { headers: { 'User-Agent': 'KevsStore' } }
                        );
                        const data = await rev.json();
                        addrInput.value = data.display_name;
                        deliveryAddress = data.display_name;
                        localStorage.setItem('pf_delivery_address', deliveryAddress);
                        hideAddrSugg();
                        showToast("GPS address loaded! Click Save.", 'success');
                    } catch (e) {
                        showToast("GPS reverse lookup failed", 'error');
                    } finally {
                        setButtonLoading(btn, false);
                    }
                },
                () => {
                    showToast("GPS failed", 'error');
                    setButtonLoading(btn, false);
                }
            );
        } else {
            showToast("GPS not supported", 'error');
        }
    });
    document.getElementById('save-address-btn')?.addEventListener('click', estimateDelivery);

    // Checkout
    document.getElementById('checkout-btn')?.addEventListener('click', checkout);

    // Tickets Refresh
    document.getElementById('refresh-tickets')?.addEventListener('click', loadTickets);

    // Chat Bubble & Modal
    document.getElementById('chat-bubble')?.addEventListener('click', () => {
        const modal = document.getElementById('chat-modal');
        modal.classList.toggle('active');
        if (modal.classList.contains('active')) initChat();
    });
    document.getElementById('close-chat-modal')?.addEventListener('click', () => document.getElementById('chat-modal').classList.remove('active'));
    document.getElementById('chat-send')?.addEventListener('click', sendChatMessage);
    document.getElementById('chat-input')?.addEventListener('keypress', (e) => { if (e.key === 'Enter') { e.preventDefault(); sendChatMessage(); } });
    document.querySelectorAll('[data-chat-prompt]').forEach(btn => {
        btn.addEventListener('click', () => sendQuickChatPrompt(btn.dataset.chatPrompt));
    });

    // --- EVENT DELEGATION FOR DYNAMIC ELEMENTS ---
    document.addEventListener('click', function(e) {
        // Product card click opens detail unless a control was clicked
        const productCard = e.target.closest('.pf-product-card');
        if (productCard && !e.target.closest('button')) {
            const product = allProducts.find(p => String(p.id) === String(productCard.dataset.productId));
            if (product) showProductDetail(product);
            return;
        }

        // Product card quantity buttons
        const qtyBtn = e.target.closest('.qty-btn');
        if (qtyBtn && (qtyBtn.closest('#products-grid') || qtyBtn.closest('#featured-grid'))) {
            const id = qtyBtn.dataset.id;
            const delta = parseInt(qtyBtn.dataset.delta);
            if (id && !isNaN(delta)) updateProductQty(id, delta);
            return;
        }

        // Add to cart from card
        const addBtn = e.target.closest('.add-to-cart-btn');
        if (addBtn) {
            const id = addBtn.dataset.id;
            if (id) addFromCard(id);
            return;
        }

        // View details from card
        const viewBtn = e.target.closest('.view-details-btn');
        if (viewBtn) {
            const id = viewBtn.dataset.id;
            const product = allProducts.find(p => p.id == id);
            if (product) showProductDetail(product);
            return;
        }

        // Cart quantity buttons
        const cartQtyBtn = e.target.closest('.cart-qty-btn');
        if (cartQtyBtn) {
            const idx = parseInt(cartQtyBtn.dataset.index);
            const delta = parseInt(cartQtyBtn.dataset.delta);
            if (!isNaN(idx) && !isNaN(delta)) updateCartQty(idx, delta);
            return;
        }

        // Cart remove button
        const removeBtn = e.target.closest('.cart-remove-btn');
        if (removeBtn) {
            const idx = parseInt(removeBtn.dataset.index);
            if (!isNaN(idx)) removeCartItem(idx);
            return;
        }
    });

    // --- INIT ---
    loadCart();
    // Restore delivery option and address (Update #10)
    if (deliveryOption === 'delivery' && deliveryAddress) {
        document.getElementById('delivery-address').value = deliveryAddress;
        setDeliveryOpt('delivery');
    } else {
        setDeliveryOpt('pickup');
    }
    if (token) {
        try { await loadUser(); } catch (e) { token = null; }
    }
    await loadCategories();
    await loadProducts();
    handlePaymentReturn();
    handleDeepLinks();
    showView('shop');

    // Clear search on load
    if (searchInput) {
        searchInput.value = '';
        localStorage.removeItem('productSearchQuery');
        if (searchClear) searchClear.style.display = 'none';
    }

    // Service Worker
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/sw.js')
            .then(reg => console.log('✅ Service Worker registered', reg))
            .catch(err => console.warn('❌ SW registration failed', err));
    }
});