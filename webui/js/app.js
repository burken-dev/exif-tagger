// EXIF Tagger Dashboard — Client-side JavaScript

const API_BASE = '';
let pollInterval = null;
let currentSessionId = null;
let autoScroll = true;
let lastProcessedLogId = 0;

document.getElementById('auto-scroll-toggle').addEventListener('change', (e) => {
    autoScroll = e.target.checked;
});

document.getElementById('btn-clear-log').addEventListener('click', () => {
    document.getElementById('log-output').innerHTML = '';
    lastProcessedLogId = 0;
});

// ---------------------------------------------------------------------------
// Toast notifications
// ---------------------------------------------------------------------------
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(50px)';
        toast.style.transition = 'opacity 0.3s, transform 0.3s';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// ---------------------------------------------------------------------------
// Tab management
// ---------------------------------------------------------------------------
document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        btn.classList.add('active');
        const tabId = `tab-${btn.dataset.tab}`;
        document.getElementById(tabId).classList.add('active');

        if (btn.dataset.tab === 'gallery') loadGallery();
        if (btn.dataset.tab === 'config') loadConfig();
        if (btn.dataset.tab === 'schedule') loadSchedules();
    });
});

// ... existing status and config logic ...
// ---------------------------------------------------------------------------
// Gallery Management
// ---------------------------------------------------------------------------

let galleryState = {
    selectedTags: new Set(),
    selectedImageIds: new Set(),
    currentPage: 1,
    pageSize: 48,
    totalImages: 0,
    images: [],
    allTags: [],
    searchQuery: '',
    currentFolder: '',
    modalFolder: '',
    currentModalImageId: null,
};

let galleryAbortController = null;
let isSyncingHash = false;

function updateUrlHash() {
    if (isSyncingHash) return;
    const activeTab = document.querySelector('.tab-btn.active')?.dataset?.tab || 'gallery';
    const params = new URLSearchParams();

    if (galleryState.currentFolder) params.set('folder', galleryState.currentFolder);
    if (galleryState.searchQuery) params.set('search', galleryState.searchQuery);
    if (galleryState.selectedTags.size > 0) params.set('tags', Array.from(galleryState.selectedTags).join(','));
    if (galleryState.currentPage > 1) params.set('page', galleryState.currentPage);
    if (galleryState.pageSize !== 48) params.set('limit', galleryState.pageSize);

    const hashStr = `#${activeTab}?${params.toString()}`;
    if (window.location.hash !== hashStr) {
        history.replaceState(null, '', hashStr);
    }
}

function parseUrlHash() {
    const hash = window.location.hash || '#gallery';
    const [tabPart, queryPart] = hash.substring(1).split('?');
    const tabName = tabPart || 'gallery';

    isSyncingHash = true;

    const tabBtn = document.querySelector(`.tab-btn[data-tab="${tabName}"]`);
    if (tabBtn) {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        tabBtn.classList.add('active');
        document.getElementById(`tab-${tabName}`)?.classList.add('active');
    }

    if (queryPart) {
        const params = new URLSearchParams(queryPart);
        galleryState.currentFolder = params.get('folder') || '';
        galleryState.searchQuery = params.get('search') || '';
        const tagsParam = params.get('tags');
        galleryState.selectedTags = new Set(tagsParam ? tagsParam.split(',').filter(Boolean) : []);
        galleryState.currentPage = parseInt(params.get('page')) || 1;
        galleryState.pageSize = parseInt(params.get('limit')) || 48;

        const searchInput = document.getElementById('gallery-search-input');
        if (searchInput) searchInput.value = galleryState.searchQuery;

        const pageSizeSelect = document.getElementById('page-size-select');
        if (pageSizeSelect) pageSizeSelect.value = galleryState.pageSize;
    }

    renderFolderScopeBreadcrumbs();
    renderTagFilters();

    if (tabName === 'gallery') fetchGalleryImages();
    if (tabName === 'config') loadConfig();
    if (tabName === 'schedule') loadSchedules();

    isSyncingHash = false;
}

window.addEventListener('hashchange', parseUrlHash);
window.addEventListener('popstate', parseUrlHash);

async function loadGallery() {
    renderFolderScopeBreadcrumbs();
    await fetchGalleryTags();
    await fetchGalleryImages();
}

async function fetchGalleryTags() {
    try {
        const resp = await fetch(`${API_BASE}/api/gallery/tags`);
        if (!resp.ok) return;
        const data = await resp.json();
        galleryState.allTags = data.tags || [];
        renderTagFilters();
        renderDatalistTags();
    } catch (e) {
        console.error('Failed to load gallery tags:', e);
    }
}

function renderTagFilters() {
    const container = document.getElementById('gallery-tag-filters');
    if (!container) return;

    if (!galleryState.allTags || galleryState.allTags.length === 0) {
        container.innerHTML = '<span style="font-size:0.85rem; color:#888;">No tags found in gallery.</span>';
        return;
    }

    container.innerHTML = galleryState.allTags.map(tag => {
        const isActive = galleryState.selectedTags.has(tag);
        return `
            <label class="tag-filter-chip ${isActive ? 'active' : ''}" data-tag="${tag}">
                <input type="checkbox" ${isActive ? 'checked' : ''} onchange="toggleTagFilter('${tag}')">
                #${tag}
            </label>
        `;
    }).join('');
}

function renderDatalistTags() {
    const datalist = document.getElementById('existing-tags-datalist');
    if (!datalist) return;
    datalist.innerHTML = (galleryState.allTags || []).map(t => `<option value="${t}">`).join('');
}

window.toggleTagFilter = function(tag) {
    if (galleryState.selectedTags.has(tag)) {
        galleryState.selectedTags.delete(tag);
    } else {
        galleryState.selectedTags.add(tag);
    }
    galleryState.currentPage = 1;
    renderTagFilters();
    updateUrlHash();
    fetchGalleryImages();
};

document.getElementById('btn-clear-filters')?.addEventListener('click', () => {
    galleryState.selectedTags.clear();
    galleryState.searchQuery = '';
    const searchInput = document.getElementById('gallery-search-input');
    if (searchInput) searchInput.value = '';
    galleryState.currentPage = 1;
    renderTagFilters();
    updateUrlHash();
    fetchGalleryImages();
});

// Folder navigation functions
function renderFolderScopeBreadcrumbs() {
    const el = document.getElementById('folder-breadcrumbs');
    if (!el) return;

    const currentPath = galleryState.currentFolder || '';
    const breadcrumbs = [{ name: 'Root', path: '' }];
    if (currentPath) {
        let accum = [];
        for (const p of currentPath.split('/')) {
            accum.push(p);
            breadcrumbs.push({ name: p, path: accum.join('/') });
        }
    }

    el.innerHTML = breadcrumbs.map(b => `
        <span class="breadcrumb-item ${b.path === currentPath ? 'active' : ''}" 
              onclick="setFolderScope('${b.path}')">📁 ${b.name}</span>
    `).join('');
}

window.setFolderScope = function(path) {
    galleryState.currentFolder = path;
    galleryState.currentPage = 1;
    renderFolderScopeBreadcrumbs();
    updateUrlHash();
    fetchGalleryImages();
};

async function openFolderModal(path = galleryState.currentFolder) {
    galleryState.modalFolder = path;
    const modal = document.getElementById('folder-modal');
    if (modal) modal.style.display = 'flex';
    await fetchModalFolders(path);
}

async function fetchModalFolders(path = '') {
    galleryState.modalFolder = path;
    try {
        const resp = await fetch(`${API_BASE}/api/gallery/folders?path=${encodeURIComponent(path)}`);
        if (!resp.ok) return;
        const data = await resp.json();
        renderModalFolders(data);
    } catch (e) {
        console.error('Failed to load modal folders:', e);
    }
}
window.fetchModalFolders = fetchModalFolders;

function renderModalFolders(data) {
    const breadcrumbsEl = document.getElementById('modal-folder-breadcrumbs');
    if (breadcrumbsEl) {
        breadcrumbsEl.innerHTML = (data.breadcrumbs || []).map(b => `
            <span class="breadcrumb-item ${b.path === data.current_path ? 'active' : ''}" 
                  onclick="fetchModalFolders('${b.path}')">${b.name}</span>
        `).join('');
    }

    const listEl = document.getElementById('modal-folder-list');
    if (!listEl) return;

    if (!data.folders || data.folders.length === 0) {
        listEl.innerHTML = '<div style="color:#888; font-size:0.85rem; grid-column:1/-1;">No subdirectories found.</div>';
        return;
    }

    listEl.innerHTML = data.folders.map(f => `
        <div class="folder-card" onclick="fetchModalFolders('${f.relative_path}')">
            <span class="folder-card-name" title="${f.name}">📁 ${f.name}</span>
            <span class="folder-card-count">${f.image_count}</span>
        </div>
    `).join('');
}

document.getElementById('btn-open-folder-modal')?.addEventListener('click', () => openFolderModal());
document.getElementById('btn-cancel-folder-modal')?.addEventListener('click', closeFolderModal);
document.getElementById('folder-modal-close')?.addEventListener('click', closeFolderModal);

function closeFolderModal() {
    const modal = document.getElementById('folder-modal');
    if (modal) modal.style.display = 'none';
}

document.getElementById('btn-select-current-folder')?.addEventListener('click', () => {
    setFolderScope(galleryState.modalFolder);
    closeFolderModal();
});

async function fetchGalleryImages() {
    galleryAbortController?.abort();
    const controller = new AbortController();
    galleryAbortController = controller;

    const grid = document.getElementById('gallery-grid');
    if (!grid) return;

    grid.innerHTML = '<div class="empty-gallery-msg">Loading images...</div>';

    const offset = (galleryState.currentPage - 1) * galleryState.pageSize;
    const tagQuery = Array.from(galleryState.selectedTags).join(',');
    const searchQuery = galleryState.searchQuery.trim();

    let url = `${API_BASE}/api/gallery/images?offset=${offset}&limit=${galleryState.pageSize}`;
    if (tagQuery) url += `&tags=${encodeURIComponent(tagQuery)}`;
    if (searchQuery) url += `&search=${encodeURIComponent(searchQuery)}`;
    if (galleryState.currentFolder) url += `&folder=${encodeURIComponent(galleryState.currentFolder)}`;

    try {
        const resp = await fetch(url, { signal: controller.signal });
        if (!resp.ok) throw new Error('Failed to fetch gallery images');
        const data = await resp.json();

        galleryState.images = data.images || [];
        galleryState.totalImages = data.total || 0;

        renderGalleryGrid();
        renderPagination();
        updateSelectedCountUI();
    } catch (e) {
        if (e.name === 'AbortError') return;
        grid.innerHTML = `<div class="empty-gallery-msg" style="color:#f87171;">Error loading images: ${e.message}</div>`;
    }
}

function renderGalleryGrid() {
    const grid = document.getElementById('gallery-grid');
    if (!grid) return;

    if (!galleryState.images || galleryState.images.length === 0) {
        grid.innerHTML = '<div class="empty-gallery-msg">No images match your query.</div>';
        return;
    }

    grid.innerHTML = galleryState.images.map(img => {
        const isSelected = galleryState.selectedImageIds.has(img.id);
        const tagsBadges = (img.tags || []).map(t => `<span class="tag-badge">#${t}</span>`).join(' ');

        return `
            <div class="gallery-item-card ${isSelected ? 'selected' : ''}" data-id="${img.id}">
                <input type="checkbox" class="gallery-checkbox-overlay" ${isSelected ? 'checked' : ''} 
                       onchange="toggleImageSelection(${img.id}, this.checked)">
                <div class="gallery-thumb-wrap" onclick="openImageModal(${img.id})">
                    <img class="gallery-thumb-img" src="${API_BASE}/api/gallery/image/${img.id}/file" alt="${img.filename}" loading="lazy">
                </div>
                <div class="gallery-item-info">
                    <div class="gallery-item-title" title="${img.filename}">${img.filename}</div>
                    <div class="gallery-item-path" title="${img.relative_path}">${img.relative_path}</div>
                    <div class="tags-badge-list">${tagsBadges || '<span style="font-size:0.7rem; color:#666;">No tags</span>'}</div>
                </div>
            </div>
        `;
    }).join('');
}

window.toggleImageSelection = function(id, checked) {
    if (checked) {
        galleryState.selectedImageIds.add(id);
    } else {
        galleryState.selectedImageIds.delete(id);
    }

    const card = document.querySelector(`.gallery-item-card[data-id="${id}"]`);
    if (card) {
        if (checked) card.classList.add('selected');
        else card.classList.remove('selected');
    }
    updateSelectedCountUI();
};

function updateSelectedCountUI() {
    const countSpan = document.getElementById('selected-count');
    if (countSpan) countSpan.textContent = galleryState.selectedImageIds.size;

    const gridCountSpan = document.getElementById('grid-selection-count');
    if (gridCountSpan) {
        const onPageCount = (galleryState.images || []).filter(img => galleryState.selectedImageIds.has(img.id)).length;
        gridCountSpan.textContent = onPageCount;
    }

    const batchBtn = document.getElementById('btn-apply-batch');
    if (batchBtn) batchBtn.disabled = galleryState.selectedImageIds.size === 0;
}

// Select/Deselect All buttons
document.getElementById('btn-select-all-page')?.addEventListener('click', () => {
    (galleryState.images || []).forEach(img => {
        galleryState.selectedImageIds.add(img.id);
    });
    renderGalleryGrid();
    updateSelectedCountUI();
});

document.getElementById('btn-deselect-all')?.addEventListener('click', () => {
    galleryState.selectedImageIds.clear();
    renderGalleryGrid();
    updateSelectedCountUI();
});

// Page size selector handler
document.getElementById('page-size-select')?.addEventListener('change', (e) => {
    galleryState.pageSize = parseInt(e.target.value) || 48;
    galleryState.currentPage = 1;
    updateUrlHash();
    fetchGalleryImages();
});

// Page jump input handler
document.getElementById('page-jump-input')?.addEventListener('change', (e) => {
    const pageNum = parseInt(e.target.value);
    if (!isNaN(pageNum)) {
        goToPage(pageNum);
    }
});

// Pagination handlers
function renderPagination() {
    const totalPages = Math.ceil(galleryState.totalImages / galleryState.pageSize) || 1;
    const pageInfo = document.getElementById('pagination-info');
    const prevBtn = document.getElementById('btn-prev-page');
    const nextBtn = document.getElementById('btn-next-page');
    const numbersContainer = document.getElementById('pagination-numbers');
    const jumpInput = document.getElementById('page-jump-input');

    if (pageInfo) {
        pageInfo.textContent = `Page ${galleryState.currentPage} of ${totalPages} (${galleryState.totalImages} total)`;
    }

    if (jumpInput) {
        jumpInput.value = galleryState.currentPage;
        jumpInput.max = totalPages;
    }

    if (prevBtn) prevBtn.disabled = galleryState.currentPage <= 1;
    if (nextBtn) nextBtn.disabled = galleryState.currentPage >= totalPages;

    if (numbersContainer) {
        let pagesToDisplay = [];
        const current = galleryState.currentPage;

        pagesToDisplay.push(1);
        for (let p = Math.max(2, current - 2); p <= Math.min(totalPages - 1, current + 2); p++) {
            pagesToDisplay.push(p);
        }
        if (totalPages > 1 && !pagesToDisplay.includes(totalPages)) {
            pagesToDisplay.push(totalPages);
        }

        pagesToDisplay = Array.from(new Set(pagesToDisplay)).sort((a, b) => a - b);

        let html = '';
        let lastP = 0;
        for (const p of pagesToDisplay) {
            if (lastP && p - lastP > 1) {
                html += '<span style="color:#666; padding:0 2px;">...</span>';
            }
            const isActive = p === current;
            html += `<button class="page-num-btn ${isActive ? 'active' : ''}" onclick="goToPage(${p})">${p}</button>`;
            lastP = p;
        }
        numbersContainer.innerHTML = html;
    }
}

window.goToPage = function(pageNumber) {
    const totalPages = Math.ceil(galleryState.totalImages / galleryState.pageSize) || 1;
    let target = Math.max(1, Math.min(totalPages, pageNumber));
    if (galleryState.currentPage !== target) {
        galleryState.currentPage = target;
        updateUrlHash();
        fetchGalleryImages();
    }
};

document.getElementById('btn-prev-page')?.addEventListener('click', () => {
    if (galleryState.currentPage > 1) {
        goToPage(galleryState.currentPage - 1);
    }
});

document.getElementById('btn-next-page')?.addEventListener('click', () => {
    const totalPages = Math.ceil(galleryState.totalImages / galleryState.pageSize) || 1;
    if (galleryState.currentPage < totalPages) {
        goToPage(galleryState.currentPage + 1);
    }
});

// Search input debouncing
let searchDebounceTimeout = null;
document.getElementById('gallery-search-input')?.addEventListener('input', (e) => {
    clearTimeout(searchDebounceTimeout);
    searchDebounceTimeout = setTimeout(() => {
        galleryState.searchQuery = e.target.value;
        galleryState.currentPage = 1;
        updateUrlHash();
        fetchGalleryImages();
    }, 300);
});


// Sync Gallery Index
document.getElementById('btn-sync-gallery')?.addEventListener('click', async () => {
    showToast('Syncing gallery index...', 'info');
    try {
        const resp = await fetch(`${API_BASE}/api/gallery/sync`, { method: 'POST' });
        if (resp.ok) {
            let finished = false;
            while (!finished) {
                await new Promise(r => setTimeout(r, 800));
                const statusResp = await fetch(`${API_BASE}/api/gallery/sync/status`);
                if (statusResp.ok) {
                    const statusData = await statusResp.json();
                    if (statusData.status === 'complete') {
                        showToast(`Sync complete! Total: ${statusData.stats?.total || 0}, Updated: ${statusData.stats?.updated || 0}`, 'success');
                        loadGallery();
                        finished = true;
                    } else if (statusData.status === 'error') {
                        showToast(statusData.error || 'Sync failed', 'error');
                        finished = true;
                    }
                }
            }
        } else {
            showToast('Sync failed', 'error');
        }
    } catch (e) {
        showToast('Network error during sync', 'error');
    }
});


// Batch Tag Modification
document.getElementById('btn-apply-batch')?.addEventListener('click', async () => {
    const selectedIds = Array.from(galleryState.selectedImageIds);
    if (selectedIds.length === 0) return;

    const addTagsStr = document.getElementById('batch-add-input')?.value || '';
    const removeTagsStr = document.getElementById('batch-remove-input')?.value || '';

    const addTags = addTagsStr.split(',').map(t => t.trim()).filter(Boolean);
    const removeTags = removeTagsStr.split(',').map(t => t.trim()).filter(Boolean);

    if (addTags.length === 0 && removeTags.length === 0) {
        showToast('Specify at least one tag to add or remove.', 'error');
        return;
    }

    showToast(`Updating tags for ${selectedIds.length} images...`, 'info');

    try {
        const resp = await fetch(`${API_BASE}/api/gallery/batch-tags`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                image_ids: selectedIds,
                add_tags: addTags,
                remove_tags: removeTags,
            }),
        });

        if (resp.ok) {
            const data = await resp.json();
            showToast(`Successfully updated ${data.modified} images!`, 'success');
            document.getElementById('batch-add-input').value = '';
            document.getElementById('batch-remove-input').value = '';
            loadGallery();
        } else {
            const err = await resp.json();
            showToast('Batch update failed: ' + (err.detail || 'Unknown error'), 'error');
        }
    } catch (e) {
        showToast('Network error during batch update', 'error');
    }
});

// Global Tag Removal
document.getElementById('btn-remove-global-tag')?.addEventListener('click', async () => {
    const tagInput = document.getElementById('global-tag-input');
    const tagName = tagInput ? tagInput.value.trim().toLowerCase() : '';

    if (!tagName) {
        showToast('Please enter a tag name to remove globally.', 'error');
        return;
    }

    if (!confirm(`Are you sure you want to remove tag "${tagName}" from ALL photos in the gallery?`)) {
        return;
    }

    showToast(`Removing tag "${tagName}" globally...`, 'info');

    try {
        const resp = await fetch(`${API_BASE}/api/gallery/remove-tag-global`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tag_name: tagName }),
        });

        if (resp.ok) {
            const data = await resp.json();
            showToast(`Removed tag "${tagName}" from ${data.modified} photos.`, 'success');
            tagInput.value = '';
            loadGallery();
        } else {
            const err = await resp.json();
            showToast('Global removal failed: ' + (err.detail || 'Unknown error'), 'error');
        }
    } catch (e) {
        showToast('Network error during global tag removal', 'error');
    }
});

// ---------------------------------------------------------------------------
// Image Lightbox & Tag Editor Modal
// ---------------------------------------------------------------------------

window.openImageModal = async function(imageId) {
    galleryState.currentModalImageId = imageId;
    const modal = document.getElementById('image-modal');
    if (!modal) return;

    try {
        const resp = await fetch(`${API_BASE}/api/gallery/image/${imageId}`);
        if (!resp.ok) throw new Error('Image not found');
        const imgData = await resp.json();

        document.getElementById('modal-filename').textContent = imgData.filename;
        document.getElementById('modal-path').textContent = imgData.file_path;
        document.getElementById('modal-image-view').src = `${API_BASE}/api/gallery/image/${imageId}/file`;

        const tagsList = document.getElementById('modal-tags-list');
        tagsList.innerHTML = (imgData.tags || []).map(t => `
            <span class="tag-badge">
                #${t}
                <span class="remove-tag-btn" onclick="removeSingleModalTag('${t}')">&times;</span>
            </span>
        `).join('') || '<span style="font-size:0.8rem; color:#888;">No tags applied</span>';

        document.getElementById('modal-tags-input').value = (imgData.tags || []).join(', ');

        modal.style.display = 'flex';
    } catch (e) {
        showToast('Failed to load image details', 'error');
    }
};

window.removeSingleModalTag = function(tagToRemove) {
    const input = document.getElementById('modal-tags-input');
    if (!input) return;
    const currentTags = input.value.split(',').map(t => t.trim().toLowerCase()).filter(Boolean);
    const filtered = currentTags.filter(t => t !== tagToRemove.toLowerCase());
    input.value = filtered.join(', ');
};

document.getElementById('btn-cancel-modal')?.addEventListener('click', closeModal);
document.getElementById('modal-close')?.addEventListener('click', closeModal);

function closeModal() {
    const modal = document.getElementById('image-modal');
    if (modal) modal.style.display = 'none';
    galleryState.currentModalImageId = null;
}

document.getElementById('btn-save-modal-tags')?.addEventListener('click', async () => {
    const imageId = galleryState.currentModalImageId;
    if (!imageId) return;

    const inputVal = document.getElementById('modal-tags-input')?.value || '';
    const newTags = inputVal.split(',').map(t => t.trim().toLowerCase()).filter(Boolean);

    try {
        const resp = await fetch(`${API_BASE}/api/gallery/image/${imageId}/tags`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tags: newTags }),
        });

        if (resp.ok) {
            showToast('Tags updated successfully!', 'success');
            closeModal();
            loadGallery();
        } else {
            const err = await resp.json();
            showToast('Failed to update tags: ' + (err.detail || 'Unknown error'), 'error');
        }
    } catch (e) {
        showToast('Network error saving tags', 'error');
    }
});

// Load config on startup
loadConfig();


// ---------------------------------------------------------------------------
// Status polling
// ---------------------------------------------------------------------------
async function fetchStatus() {
    try {
        const resp = await fetch(`${API_BASE}/api/status`);
        const data = await resp.json();
        updateStatusUI(data);
        return data;
    } catch (e) { /* silent fail during startup */ }
}

function updateStatusUI(data) {
    const indicator = document.getElementById('status-indicator');
    const btnStart = document.getElementById('btn-start');
    const btnStop = document.getElementById('btn-stop');
    const progressBar = document.getElementById('progress-bar');
    const progressText = document.getElementById('progress-text');

    if (data.running) {
        isRunning = true;
        indicator.textContent = 'Running';
        indicator.className = 'status-badge running';
        btnStart.disabled = true;
        btnStop.disabled = false;
    } else if (data.stopRequested) {
        isRunning = false;
        indicator.textContent = 'Stopping...';
        indicator.className = 'status-badge stopped';
    } else {
        const hasFailures = data.summary && (data.summary.failed > 0 || (data.summary.errors && data.summary.errors.length > 0));
        indicator.textContent = data.summary ? (hasFailures ? 'Completed with errors' : 'Completed') : 'Idle';
        if (hasFailures) {
            indicator.className = 'status-badge warning';
        } else if (data.summary) {
            indicator.className = 'status-badge completed';
        } else {
            indicator.className = 'status-badge idle';
        }
        isRunning = false;
        btnStart.disabled = false;
        btnStop.disabled = true;
    }

    // Update progress
    if (data.total > 0) {
        const pct = data.progressPct || 0;
        progressBar.style.width = `${pct}%`;
        progressText.textContent = `${data.processed} / ${data.total} images processed (${pct}%)`;
    }

    // Update log output continuously without duplicate repetition
    if (data.logs && Array.isArray(data.logs)) {
        data.logs.forEach(log => {
            if (log.id > lastProcessedLogId) {
                appendLog(log.text, log.level || 'info');
                lastProcessedLogId = log.id;
            }
        });
    }

    setupPolling();
}

function appendLog(text, severity = 'info') {
    const el = document.getElementById('log-output');
    const line = document.createElement('div');
    line.className = `log-line ${severity}`;
    line.textContent = text;
    el.appendChild(line);
    if (autoScroll) {
        el.scrollTop = el.scrollHeight;
    }
}

let isRunning = false;

function setupPolling() {
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(fetchStatus, isRunning ? 1000 : 5000);
}

// Start polling when page loads
fetchStatus().then(() => setupPolling());

// ---------------------------------------------------------------------------
// Processing controls
// ---------------------------------------------------------------------------
document.getElementById('btn-start').addEventListener('click', async () => {
    const folderPath = document.getElementById('folder-path').value.trim() || null;
    const maxImages = document.getElementById('max-images').value ? parseInt(document.getElementById('max-images').value) : null;

    try {
        const resp = await fetch(`${API_BASE}/api/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rootDirectory: folderPath, maxImages }),
        });
        if (resp.ok) {
            document.getElementById('log-output').innerHTML = '';
            lastProcessedLogId = 0;
            document.getElementById('progress-bar').style.width = '0%';
            document.getElementById('progress-text').textContent = '0 / 0 images processed (0%)';
            appendLog('Session started.', 'info');
        } else {
            const err = await resp.json();
            showToast(err.detail || 'Failed to start session', 'error');
        }
    } catch (e) { showToast('Network error: ' + e.message, 'error'); }
});

document.getElementById('btn-stop').addEventListener('click', async () => {
    try {
        const resp = await fetch(`${API_BASE}/api/stop`, { method: 'POST' });
        if (resp.ok) appendLog('Stop requested.', 'info');
    } catch (e) { showToast('Network error: ' + e.message, 'error'); }
});

// ---------------------------------------------------------------------------
// Config management
// ---------------------------------------------------------------------------
async function loadConfig() {
    try {
        const resp = await fetch(`${API_BASE}/api/config`);
        if (!resp.ok) return;
        const config = await resp.json();

        document.getElementById('config-root').value = config.root_directory || '';
        const folderPathEl = document.getElementById('folder-path');
        if (folderPathEl) {
            folderPathEl.placeholder = config.root_directory ? `Default: ${config.root_directory}` : '/data/images/this-month';
        }
        document.getElementById('model-base-url').value = config.model?.base_url || '';
        document.getElementById('model-name').value = config.model?.model_name || '';
        document.getElementById('model-max-tokens').value = config.model?.max_tokens || 500;
        const tempSlider = document.getElementById('model-temperature');
        const tempVal = config.model?.temperature ?? 0.1;
        tempSlider.value = tempVal;
        document.getElementById('temp-value').textContent = tempVal;

        // Populate API key field (only if server returned one)
        document.getElementById('model-api-key').value = config.model?.api_key || '';

        // Populate structured outputs and max dimension
        document.getElementById('model-use-structured').checked = config.model?.use_structured_outputs || false;
        document.getElementById('model-max-dimension').value = config.model?.max_image_dimension || 720;

        // Populate extra params textarea
        const modelParams = config.model?.params || {};
        document.getElementById('model-params').value = JSON.stringify(modelParams, null, 2);

        // Render tags
        renderTags(config.tags || {});

        // Render exclude patterns
        renderExcludes(config.exclude_patterns || []);
    } catch (e) { console.error('Failed to load config:', e); }
}

function renderTags(tags) {
    const container = document.getElementById('tags-container');
    container.innerHTML = '';
    for (const [name, data] of Object.entries(tags)) {
        addTagCard(name, data.description || '', data.threshold || 0.7);
    }
    updateTagMoveButtons();
}

function updateTagMoveButtons() {
    const cards = document.querySelectorAll('#tags-container .tag-card');
    cards.forEach((card, index) => {
        const btnUp = card.querySelector('.tag-move-btn[data-dir="up"]');
        const btnDown = card.querySelector('.tag-move-btn[data-dir="down"]');
        if (btnUp) btnUp.disabled = (index === 0);
        if (btnDown) btnDown.disabled = (index === cards.length - 1);
    });
}

function addTagCard(name = '', desc = '', threshold = 0.7) {
    const container = document.getElementById('tags-container');
    const card = document.createElement('div');
    card.className = 'tag-card';
    card.innerHTML = `
        <input type="text" class="tag-name-input" placeholder="e.g. landscape" value="${name}">
        <input type="text" class="tag-desc-input" placeholder="What should this tag detect?" value="${desc}">
        <input type="number" class="tag-threshold-input" min="0" max="1" step="0.05" value="${threshold}" title="Threshold">
        <button class="btn btn-secondary tag-move-btn" data-dir="up" style="padding:2px 6px; font-size:0.8rem;">↑</button>
        <button class="btn btn-secondary tag-move-btn" data-dir="down" style="padding:2px 6px; font-size:0.8rem;">↓</button>
        <button class="btn btn-danger tag-remove-btn" style="padding:4px 8px;">×</button>
    `;
    card.querySelector('.tag-remove-btn').addEventListener('click', () => {
        card.remove();
        updateTagMoveButtons();
    });
    card.querySelectorAll('.tag-move-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const dir = btn.dataset.dir;
            if (dir === 'up') {
                const prev = card.previousElementSibling;
                if (prev) container.insertBefore(card, prev);
            } else {
                const next = card.nextElementSibling;
                if (next) container.insertBefore(next, card);
            }
            updateTagMoveButtons();
        });
    });
    container.appendChild(card);
    updateTagMoveButtons();
}

document.getElementById('btn-add-tag').addEventListener('click', () => addTagCard());

function renderExcludes(patterns) {
    const container = document.getElementById('exclude-container');
    container.innerHTML = '';
    patterns.forEach(p => addExcludeItem(p));
    updateExcludeMoveButtons();
}

function updateExcludeMoveButtons() {
    const items = document.querySelectorAll('#exclude-container .exclude-item');
    items.forEach((item, index) => {
        const btnUp = item.querySelector('.exclude-move-btn[data-dir="up"]');
        const btnDown = item.querySelector('.exclude-move-btn[data-dir="down"]');
        if (btnUp) btnUp.disabled = (index === 0);
        if (btnDown) btnDown.disabled = (index === items.length - 1);
    });
}

function addExcludeItem(pattern = '') {
    const container = document.getElementById('exclude-container');
    const item = document.createElement('div');
    item.className = 'exclude-item';
    item.innerHTML = `
        <input type="text" class="exclude-input" placeholder="e.g. thumbs?_?(db|cache)?/i?" value="${pattern}">
        <button class="btn btn-secondary exclude-move-btn" data-dir="up" style="padding:2px 6px; font-size:0.8rem;">↑</button>
        <button class="btn btn-secondary exclude-move-btn" data-dir="down" style="padding:2px 6px; font-size:0.8rem;">↓</button>
        <button class="btn btn-danger exclude-remove-btn" style="padding:4px 8px;">×</button>
    `;
    item.querySelector('.exclude-remove-btn').addEventListener('click', () => {
        item.remove();
        updateExcludeMoveButtons();
    });
    item.querySelectorAll('.exclude-move-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const dir = btn.dataset.dir;
            if (dir === 'up') {
                const prev = item.previousElementSibling;
                if (prev) container.insertBefore(item, prev);
            } else {
                const next = item.nextElementSibling;
                if (next) container.insertBefore(next, item);
            }
            updateExcludeMoveButtons();
        });
    });
    container.appendChild(item);
    updateExcludeMoveButtons();
}

document.getElementById('btn-add-exclude').addEventListener('click', () => addExcludeItem());

// API key toggle visibility
document.getElementById('btn-toggle-api-key').addEventListener('click', () => {
    const apiKeyInput = document.getElementById('model-api-key');
    const toggleBtn = document.getElementById('btn-toggle-api-key');
    if (apiKeyInput.type === 'password') {
        apiKeyInput.type = 'text';
        toggleBtn.textContent = '🔒';
    } else {
        apiKeyInput.type = 'password';
        toggleBtn.textContent = '👁️';
    }
});

// Temperature slider display sync
document.getElementById('model-temperature').addEventListener('input', (e) => {
    document.getElementById('temp-value').textContent = e.target.value;
});

document.getElementById('btn-save-config').addEventListener('click', async () => {
    const btn = document.getElementById('btn-save-config');
    btn.disabled = true;
    const originalText = btn.textContent;
    btn.textContent = 'Saving...';

    try {
        const tags = {};
        document.querySelectorAll('.tag-card').forEach(card => {
            const name = card.querySelector('.tag-name-input').value.trim();
            if (!name) return;
            tags[name] = {
                description: card.querySelector('.tag-desc-input').value,
                threshold: parseFloat(card.querySelector('.tag-threshold-input').value) || 0.7,
            };
        });

        const excludes = [];
        document.querySelectorAll('.exclude-input').forEach(input => {
            const v = input.value.trim();
            if (v) excludes.push(v);
        });

        // Parse extra params JSON
        const paramsText = document.getElementById('model-params').value.trim();
        let modelParams = {};
        if (paramsText) {
            try {
                modelParams = JSON.parse(paramsText);
            } catch (e) {
                showToast('Invalid JSON in Extra Params field', 'error');
                return;
            }
        }

        const resp = await fetch(`${API_BASE}/api/config`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                root_directory: document.getElementById('config-root').value.trim(),
                model: {
                    base_url: document.getElementById('model-base-url').value.trim(),
                    model_name: document.getElementById('model-name').value.trim(),
                    max_tokens: parseInt(document.getElementById('model-max-tokens').value) || 500,
                    temperature: parseFloat(document.getElementById('model-temperature').value) || 0.1,
                    api_key: document.getElementById('model-api-key').value.trim() || null,
                    use_structured_outputs: document.getElementById('model-use-structured').checked,
                    max_image_dimension: parseInt(document.getElementById('model-max-dimension').value) || 720,
                    params: modelParams,
                },
                tags,
                exclude_patterns: excludes,
            }),
        });
        if (resp.ok) {
            showToast('Configuration saved successfully.', 'success');
        } else {
            const err = await resp.json();
            showToast('Failed to save config: ' + (err.detail || 'Unknown error'), 'error');
        }
    } catch (e) { showToast('Network error: ' + e.message, 'error'); }
    finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
});

// Export config as JSON download
document.getElementById('btn-export-config').addEventListener('click', async () => {
    try {
        const resp = await fetch(`${API_BASE}/api/config`);
        if (!resp.ok) { showToast('Failed to export config', 'error'); return; }
        const config = await resp.json();
        const blob = new Blob([JSON.stringify(config, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'exif-tagger-config.json';
        a.click();
        URL.revokeObjectURL(url);
    } catch (e) { showToast('Export failed: ' + e.message, 'error'); }
});

// Import config from JSON file
document.getElementById('import-config-input').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
        const text = await file.text();
        const config = JSON.parse(text);
        document.getElementById('config-root').value = config.root_directory || '';
        document.getElementById('model-base-url').value = config.model?.base_url || '';
        document.getElementById('model-name').value = config.model?.model_name || '';
        document.getElementById('model-max-tokens').value = config.model?.max_tokens || 500;
        const tempSlider = document.getElementById('model-temperature');
        const tempVal = config.model?.temperature ?? 0.1;
        tempSlider.value = tempVal;
        document.getElementById('temp-value').textContent = tempVal;
        document.getElementById('model-use-structured').checked = config.model?.use_structured_outputs || false;
        document.getElementById('model-max-dimension').value = config.model?.max_image_dimension || 720;
        const modelParams = config.model?.params || {};
        document.getElementById('model-params').value = JSON.stringify(modelParams, null, 2);
        renderTags(config.tags || {});
        renderExcludes(config.exclude_patterns || []);
        showToast('Config imported — click Save to apply', 'success');
    } catch (err) { showToast('Failed to import config: ' + err.message, 'error'); }
    // Reset input so the same file can be re-imported
    e.target.value = '';
});

// ---------------------------------------------------------------------------
// Schedule management
// ---------------------------------------------------------------------------
async function loadSchedules() {
    try {
        const resp = await fetch(`${API_BASE}/api/schedule`);
        if (!resp.ok) return;
        const schedules = await resp.json();
        renderSchedules(schedules);
    } catch (e) { console.error('Failed to load schedules:', e); }
}

function renderSchedules(schedules) {
    const tbody = document.getElementById('schedules-tbody');
    tbody.innerHTML = '';
    if (schedules.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#888;">No schedules configured</td></tr>';
        return;
    }
    for (const s of schedules) {
        const tr = document.createElement('tr');
        const freqType = s.cron_expression ? 'Cron' : `Every ${s.interval_hours}h`;
        const statusColor = s.last_status === 'success' ? '#2ecc71' : s.last_status === 'failed' ? '#e74c3c' : '#888';
        tr.innerHTML = `
            <td>${s.name}</td>
            <td>${s.folder}</td>
            <td>${freqType}</td>
            <td>${s.next_run_at || '-'}</td>
            <td style="color:${statusColor}">${s.last_status || 'Never'}</td>
            <td>
                <button class="btn btn-primary schedule-run-btn" data-id="${s.id}" style="padding:4px 8px; margin-right:4px;">Run Now</button>
                <button class="btn btn-danger schedule-delete-btn" data-id="${s.id}" style="padding:4px 8px;">Delete</button>
            </td>
        `;
        tbody.appendChild(tr);
    }

    // Attach run now handlers
    document.querySelectorAll('.schedule-run-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            try {
                const resp = await fetch(`${API_BASE}/api/schedule/${btn.dataset.id}/run`, { method: 'POST' });
                if (resp.ok) {
                    showToast('Schedule execution started.', 'success');
                } else {
                    const err = await resp.json();
                    showToast('Failed to run schedule: ' + (err.detail || 'Unknown error'), 'error');
                }
            } catch (e) { showToast('Network error: ' + e.message, 'error'); }
        });
    });

    // Attach delete handlers
    document.querySelectorAll('.schedule-delete-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            if (!confirm('Delete this schedule?')) return;
            try {
                const resp = await fetch(`${API_BASE}/api/schedule/${btn.dataset.id}`, { method: 'DELETE' });
                if (resp.ok) loadSchedules();
            } catch (e) { showToast('Network error', 'error'); }
        });
    });
}

// Schedule type toggle
document.getElementById('schedule-type').addEventListener('change', (e) => {
    const isCron = e.target.value === 'cron';
    document.getElementById('interval-input-group').style.display = isCron ? 'none' : '';
    document.getElementById('cron-input-group').style.display = isCron ? '' : 'none';
});

// Preset buttons
document.querySelectorAll('.preset-buttons button').forEach(btn => {
    btn.addEventListener('click', () => {
        const type = btn.dataset.type;
        document.getElementById('schedule-type').value = type;
        if (type === 'interval') {
            document.getElementById('schedule-interval').value = btn.dataset.hours;
        } else {
            document.getElementById('schedule-cron').value = btn.dataset.cron;
        }
    });
});

document.getElementById('btn-add-schedule').addEventListener('click', async () => {
    const name = document.getElementById('schedule-name').value.trim();
    const folder = document.getElementById('schedule-folder').value.trim();
    const type = document.getElementById('schedule-type').value;

    if (!name || !folder) { showToast('Name and folder are required', 'error'); return; }

    const body = { name, folder };
    if (type === 'interval') {
        body.interval_hours = parseFloat(document.getElementById('schedule-interval').value);
    } else {
        body.cron_expression = document.getElementById('schedule-cron').value.trim();
    }

    try {
        const resp = await fetch(`${API_BASE}/api/schedule`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (resp.ok) {
            showToast('Schedule added.', 'success');
            document.getElementById('schedule-name').value = '';
            document.getElementById('schedule-folder').value = '';
            document.getElementById('schedule-type').value = 'interval';
            document.getElementById('schedule-interval').value = '6';
            document.getElementById('schedule-cron').value = '';
            document.getElementById('interval-input-group').style.display = '';
            document.getElementById('cron-input-group').style.display = 'none';
            loadSchedules();
        } else {
            const err = await resp.json();
            showToast('Failed to add schedule: ' + (err.detail || 'Unknown error'), 'error');
        }
    } catch (e) { showToast('Network error: ' + e.message, 'error'); }
});

// Keyboard shortcuts
document.addEventListener('keydown', (e) => {
    const isInput = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName);
    if (isInput) return;

    // Ctrl+Enter to start processing
    if (e.ctrlKey && e.key === 'Enter') {
        e.preventDefault();
        const btnStart = document.getElementById('btn-start');
        if (!btnStart.disabled) btnStart.click();
    }
    // Escape to stop
    if (e.key === 'Escape') {
        e.preventDefault();
        const btnStop = document.getElementById('btn-stop');
        if (!btnStop.disabled) btnStop.click();
    }
    // Number keys for tabs
    if (!e.ctrlKey && !e.altKey && !e.metaKey) {
        const tabBtns = document.querySelectorAll('.tab-btn');
        const num = parseInt(e.key);
        if (num >= 1 && num <= 3 && tabBtns[num - 1]) {
            tabBtns[num - 1].click();
        }
    }
});

// Load config on first tab activation
loadConfig();
