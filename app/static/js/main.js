// ── Globals ───────────────────────────────────────────────────────────────────
let currentSessionId = null;

// ── DOM refs ──────────────────────────────────────────────────────────────────
const uploadForm        = document.getElementById('uploadForm');
const documentFile      = document.getElementById('documentFile');
const dropzone          = document.getElementById('dropzone');
const selectedFileName  = document.getElementById('selectedFileName');
const analyzeBtn        = document.getElementById('analyzeBtn');
const documentName      = document.getElementById('documentName');
const documentStatus    = document.getElementById('documentStatus');
const documentSummary   = document.getElementById('documentSummary');
const simplifiedContent = document.getElementById('simplifiedContent');
const loadingOverlay    = document.getElementById('loadingOverlay');
const loadingText       = document.getElementById('loadingText');
const loadingSubtext    = document.getElementById('loadingSubtext');
const toastContainer    = document.getElementById('toastContainer');

// Sidebar extended refs
const clauseList       = document.getElementById('clauseList');
const countCritical    = document.getElementById('countCritical');
const countHigh        = document.getElementById('countHigh');
const countMedium      = document.getElementById('countMedium');
const countLow         = document.getElementById('countLow');
const headerDocChip    = document.getElementById('headerDocChip');
const headerDocName    = document.getElementById('headerDocName');

// ── Analysis KPI header (Bento Grid) ─────────────────────────────────────────
function buildAnalysisHeader(riskData, fileName) {
    if (!riskData) return '';
    const rs     = riskData.risk_summary || {};
    const level  = riskData.risk_level_overall || 'medium';
    const svcName = riskData.service_name || fileName || 'Documento';
    const juris  = riskData.jurisdiction || '';
    const verdict = riskData.quick_verdict || '';

    const cards = ['critical','high','medium','low'].map(l => {
        const labels = { critical:'Crítico', high:'Alto', medium:'Medio', low:'Bajo' };
        return `<div class="kpi-card kpi-card-${l}">
            <div class="kpi-num">${rs[l] ?? 0}</div>
            <div class="kpi-label">${labels[l]}</div>
        </div>`;
    }).join('');

    const jurisdictionBadge = juris ? `
        <span class="kpi-badge">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
            ${escapeHtml(juris)}
        </span>` : '';

    const verdictHtml = verdict ? `
        <div class="kpi-verdict kpi-verdict-${level}">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><polyline points="9 12 11 14 15 10"/></svg>
            ${escapeHtml(verdict)}
        </div>` : '';

    return `<div class="analysis-kpi-header">
        <div class="kpi-top">
            <h2 class="kpi-service">${escapeHtml(svcName)}</h2>
            <div class="kpi-badges">${jurisdictionBadge}</div>
        </div>
        <div class="kpi-bento">${cards}</div>
        ${verdictHtml}
    </div>`;
}

// ── Analysis skeleton screen ──────────────────────────────────────────────────
function showAnalysisSkeleton() {
    const panel = document.getElementById('documentSummary');
    if (!panel) return;
    panel.innerHTML = `
    <div class="analysis-skeleton">
        <div class="skel-header">
            <div class="skel skel-title"></div>
            <div class="skel skel-subtitle"></div>
            <div class="skel-kpi-row">
                <div class="skel skel-kpi"></div>
                <div class="skel skel-kpi"></div>
                <div class="skel skel-kpi"></div>
                <div class="skel skel-kpi"></div>
            </div>
            <div class="skel skel-verdict"></div>
        </div>
        <div class="skel-body">
            <div class="skel skel-section"></div>
            <div class="skel skel-line skel-line-a"></div>
            <div class="skel skel-line skel-line-b"></div>
            <div class="skel skel-line skel-line-c"></div>
            <div class="skel skel-line skel-line-d"></div>
            <div class="skel skel-section"></div>
            <div class="skel skel-line skel-line-e"></div>
            <div class="skel skel-line skel-line-f"></div>
            <div class="skel skel-line skel-line-g"></div>
            <div class="skel skel-line skel-line-h"></div>
        </div>
    </div>`;
}

// ── Loading ───────────────────────────────────────────────────────────────────
function showLoading(text = 'Procesando…', subtext = '') {
    if (loadingText)    loadingText.textContent    = text;
    if (loadingSubtext) loadingSubtext.textContent = subtext;
    loadingOverlay?.classList.add('active');
}

function hideLoading() {
    loadingOverlay?.classList.remove('active');
}

// ── Toast ─────────────────────────────────────────────────────────────────────
function showToast(type, message) {
    const icons = {
        success: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
        error:   '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
        warning: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
        info:    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
    };
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.innerHTML = `<span class="toast-icon">${icons[type] || ''}</span><span class="toast-msg">${message}</span><div class="toast-progress"></div>`;
    toastContainer?.appendChild(el);
    setTimeout(() => {
        el.style.opacity   = '0';
        el.style.transform = 'translateX(12px)';
        el.style.transition = 'opacity .3s, transform .3s';
        setTimeout(() => el.remove(), 320);
    }, 3500);
}

// ── Tabs ──────────────────────────────────────────────────────────────────────
function switchTab(tab) {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        const active = btn.dataset.tab === tab;
        btn.classList.toggle('active', active);
        btn.setAttribute('aria-selected', String(active));
    });
    document.querySelectorAll('.panel').forEach(panel => {
        panel.classList.toggle('active', panel.id === tab + 'Panel');
    });
    if (tab === 'analysis') hideAnalysisDot();
}

// ── Analysis tab notification dot ────────────────────────────────────────────
function showAnalysisDot() {
    document.getElementById('analysisDot')?.classList.add('show');
}
function hideAnalysisDot() {
    document.getElementById('analysisDot')?.classList.remove('show');
}

// ── Risk header badge ─────────────────────────────────────────────────────────
function updateRiskHeaderBadge(level) {
    const badge   = document.getElementById('riskHeaderBadge');
    const levelEl = document.getElementById('riskBadgeLevel');
    if (!badge) return;
    const labels = { critical: 'Riesgo Crítico', high: 'Riesgo Alto', medium: 'Riesgo Medio', low: 'Riesgo Bajo' };
    badge.className = `risk-header-badge ${level}`;
    if (levelEl) levelEl.textContent = labels[level] || '—';
    badge.style.display = 'flex';
}

// ── Custom confirm modal ──────────────────────────────────────────────────────
function confirmAction(onConfirm) {
    const modal  = document.getElementById('confirmModal');
    if (!modal) { onConfirm(); return; }
    modal.classList.add('active');

    const ok     = document.getElementById('confirmOk');
    const cancel = document.getElementById('confirmCancel');

    function cleanup() {
        modal.classList.remove('active');
        ok?.removeEventListener('click', handleOk);
        cancel?.removeEventListener('click', handleCancel);
        document.removeEventListener('keydown', handleEsc);
    }
    async function handleOk()     { cleanup(); await onConfirm(); }
    function handleCancel()       { cleanup(); }
    function handleEsc(e)         { if (e.key === 'Escape') cleanup(); }

    ok?.addEventListener('click', handleOk);
    cancel?.addEventListener('click', handleCancel);
    document.addEventListener('keydown', handleEsc);
}

// ── Doc meta visibility ───────────────────────────────────────────────────────
function showDocMeta(show) {
    document.querySelectorAll('.doc-meta').forEach(el => {
        el.style.display = show ? '' : 'none';
    });
}

// ── Risk data → sidebar ───────────────────────────────────────────────────────
function populateRiskData(riskData) {
    if (!riskData) return;

    const rs = riskData.risk_summary || {};
    const levels = { critical: 0, high: 0, medium: 0, low: 0, ...rs };

    // Update counts
    if (countCritical) countCritical.textContent = levels.critical || '0';
    if (countHigh)     countHigh.textContent     = levels.high     || '0';
    if (countMedium)   countMedium.textContent   = levels.medium   || '0';
    if (countLow)      countLow.textContent      = levels.low      || '0';

    // Animate bars proportionally
    const max = Math.max(...Object.values(levels), 1);
    const barMap = { critical: '.risk-bar-fill.critical', high: '.risk-bar-fill.high', medium: '.risk-bar-fill.medium', low: '.risk-bar-fill.low' };
    Object.entries(barMap).forEach(([lvl, sel]) => {
        const el = document.querySelector(sel);
        if (el) el.style.width = Math.round((levels[lvl] / max) * 100) + '%';
    });

    // Populate clause navigator
    // ── Gauge de riesgo ──
    updateRiskGauge(riskData.risk_level_overall);
    updateRiskHeaderBadge(riskData.risk_level_overall);

    if (clauseList && riskData.clauses?.length) {
        clauseList.innerHTML = '';
        riskData.clauses.forEach(clause => {
            const item = document.createElement('button');
            item.className = `clause-item level-${clause.level}`;
            item.type = 'button';
            item.title = clause.explanation || '';
            item.innerHTML = `
                <span class="clause-dot ${clause.level}" aria-hidden="true"></span>
                <span class="clause-name">${escapeHtml(clause.title)}</span>`;
            // ── Cláusula clickeable → pregunta automática al chat ──
            item.addEventListener('click', () => {
                switchTab('chat');
                const qInput = document.getElementById('questionInput');
                const qForm  = document.getElementById('questionForm');
                if (qInput && qForm && !qInput.disabled) {
                    qInput.value = `¿Qué implica para el usuario la cláusula "${clause.title}"? ¿Es problemática?`;
                    qInput.dispatchEvent(new Event('input'));
                    setTimeout(() => qForm.dispatchEvent(new Event('submit')), 150);
                }
            });
            clauseList.appendChild(item);
        });
    }

    if (riskData.quick_verdict) {
        const level = riskData.risk_level_overall || 'medium';
        const toastType = level === 'critical' ? 'error' : level === 'high' ? 'warning' : 'info';
        showToast(toastType, riskData.quick_verdict);
    }
}

// ── Risk gauge ───────────────────────────────────────────────────────────────
function updateRiskGauge(level) {
    const scores = { critical: 95, high: 72, medium: 46, low: 18 };
    const colors = { critical: '#ef4444', high: '#f97316', medium: '#eab308', low: '#22c55e' };
    const score  = scores[level] ?? 0;
    const color  = colors[level] ?? '#22c55e';
    const circ   = 2 * Math.PI * 44; // r=44 → ~276.46
    const offset = circ - (score / 100) * circ;

    const fill  = document.getElementById('gaugeFill');
    const label = document.getElementById('gaugeScore');
    if (fill)  { fill.style.strokeDashoffset = offset; fill.style.stroke = color; }
    if (label) {
        let current = 0;
        const step = score / 40;
        const interval = setInterval(() => {
            current = Math.min(current + step, score);
            label.textContent = Math.round(current);
            if (current >= score) clearInterval(interval);
        }, 20);
    }
}

// Escape HTML utility (also used in chat.js scope)
function escapeHtml(str) {
    const d = document.createElement('div');
    d.textContent = str || '';
    return d.innerHTML;
}

// ── Header doc chip ───────────────────────────────────────────────────────────
function updateHeaderChip(name, show) {
    if (!headerDocChip || !headerDocName) return;
    headerDocName.textContent = name || '—';
    headerDocChip.style.display = show ? 'flex' : 'none';
}

// ── Session history ───────────────────────────────────────────────────────────
async function loadHistory() {
    const historySection = document.getElementById('historySection');
    const historyList    = document.getElementById('historyList');
    if (!historySection || !historyList) return;

    try {
        const res  = await fetch('/api/history');
        const data = await res.json();
        if (!data.success || !data.history?.length) {
            historySection.style.display = 'none';
            return;
        }
        historyList.innerHTML = '';
        data.history.forEach(item => {
            if (item.session_id === currentSessionId) return;
            const el = document.createElement('button');
            el.className = 'clause-item';
            el.type = 'button';

            const levelDot = item.risk_level_overall
                ? `<span class="clause-dot ${item.risk_level_overall}" aria-hidden="true"></span>`
                : `<span class="clause-dot" style="background:var(--gray-300)" aria-hidden="true"></span>`;

            const name = item.service_name || item.file_name || '—';
            el.innerHTML = `${levelDot}<span class="clause-name" title="${escapeHtml(item.file_name)}">${escapeHtml(name)}</span>`;
            el.addEventListener('click', () => restoreSession(item.session_id, item.file_name));
            historyList.appendChild(el);
        });
        historySection.style.display = data.history.filter(i => i.session_id !== currentSessionId).length ? '' : 'none';
    } catch (e) {
        console.error('Error cargando historial:', e);
    }
}

async function restoreSession(sessionId, fileName) {
    currentSessionId = sessionId;
    documentName.textContent = fileName || 'Documento';
    updateHeaderChip(fileName, true);
    showDocMeta(true);
    switchTab('chat');
    initChat(sessionId);
    showToast('info', `Sesión restaurada: ${fileName}`);
    pollAnalysisStatus();
}

// ── Upload ────────────────────────────────────────────────────────────────────
async function handleDocumentUpload(e) {
    e.preventDefault();
    if (!documentFile.files?.length) {
        showToast('error', 'Seleccioná un archivo para subir');
        return;
    }

    const file = documentFile.files[0];

    // Client-side size check (50MB)
    if (file.size > 50 * 1024 * 1024) {
        showToast('error', 'El archivo supera el límite de 50MB');
        return;
    }

    const formData = new FormData();
    formData.append('file', file);
    formData.append('analyze', 'true');

    showLoading('Subiendo documento…', 'Enviando al servidor');

    try {
        const response = await fetch('/api/upload', { method: 'POST', body: formData });

        if (response.status === 415) {
            const err = await response.json();
            showToast('error', err.detail || 'Formato de archivo no soportado');
            return;
        }
        if (!response.ok) {
            showToast('error', `Error del servidor (${response.status})`);
            return;
        }

        const result = await response.json();

        if (result.success) {
            currentSessionId = result.document_id;
            documentName.textContent = file.name;
            updateHeaderChip(file.name, true);
            documentStatus.className = 'doc-badge badge-processing';
            documentStatus.innerHTML = '<span class="badge-dot"></span><span id="statusText">Analizando…</span>';

            showDocMeta(true);
            showAnalysisSkeleton();
            initChat(currentSessionId);
            switchTab('chat');
            showToast('success', 'Documento subido. Analizando con IA…');
            pollAnalysisStatus();
        } else {
            showToast('error', result.message || 'Error al subir el documento');
        }
    } catch (err) {
        console.error(err);
        showToast('error', 'Error de conexión con el servidor');
    } finally {
        hideLoading();
    }
}

// ── Poll analysis status ──────────────────────────────────────────────────────
async function pollAnalysisStatus() {
    if (!currentSessionId) return;

    try {
        const response = await fetch(`/api/document/${currentSessionId}`);
        const result   = await response.json();

        if (result.success && result.summary && result.summary !== 'El análisis aún no está disponible') {
            // Analysis ready
            const statusEl = document.getElementById('statusText');
            if (statusEl) statusEl.textContent = 'Analizado';
            documentStatus.className = 'doc-badge badge-done';
            documentStatus.innerHTML = '<span class="badge-dot"></span><span id="statusText">Analizado</span>';

            // Populate risk sidebar
            if (result.risk_data) {
                populateRiskData(result.risk_data);
            }

            // Refresh history
            await loadHistory();

            // Auto-populate analysis panel silently (no tab switch)
            const analysisPanel = document.getElementById('documentSummary');
            if (analysisPanel && result.summary) {
                const fileName = documentName?.textContent || '';
                const header = buildAnalysisHeader(result.risk_data, fileName);
                analysisPanel.innerHTML = header + marked.parse(result.summary);
            }
            showAnalysisDot();
            return;
        }
    } catch (err) {
        console.error('Error al verificar estado:', err);
    }

    setTimeout(pollAnalysisStatus, 4000);
}

// ── View analysis ─────────────────────────────────────────────────────────────
async function viewDocumentSummary() {
    if (!currentSessionId) { showToast('warning', 'Primero subí un documento'); return; }

    showLoading('Cargando análisis…', 'Recuperando hallazgos');

    try {
        const response = await fetch(`/api/document/${currentSessionId}`);
        const result   = await response.json();

        if (result.success) {
            const summary  = result.summary || '';
            const fileName = documentName?.textContent || '';
            const header   = buildAnalysisHeader(result.risk_data, fileName);
            documentSummary.innerHTML = header + marked.parse(summary);

            if (result.risk_data) {
                populateRiskData(result.risk_data);
            }

            switchTab('analysis');
        } else {
            showToast('error', result.message || 'Error al obtener el análisis');
        }
    } catch (err) {
        console.error(err);
        showToast('error', 'Error de conexión');
    } finally {
        hideLoading();
    }
}

function injectRiskBar(riskData) {
    // Remove existing bar if any
    document.getElementById('risk-summary-bar')?.remove();

    const rs = riskData.risk_summary || {};
    const chips = [
        { level: 'critical', label: 'Crítico', count: rs.critical, color: 'var(--risk-critical)', bg: 'var(--risk-critical-bg)', bd: 'var(--risk-critical-bd)' },
        { level: 'high',     label: 'Alto',    count: rs.high,     color: 'var(--risk-high)',     bg: 'var(--risk-high-bg)',     bd: 'var(--risk-high-bd)'     },
        { level: 'medium',   label: 'Medio',   count: rs.medium,   color: 'var(--risk-medium)',   bg: 'var(--risk-medium-bg)',   bd: 'var(--risk-medium-bd)'   },
        { level: 'low',      label: 'Bajo',    count: rs.low,      color: 'var(--risk-low)',       bg: 'var(--risk-low-bg)',      bd: 'var(--risk-low-bd)'      },
    ].filter(c => c.count > 0);

    if (!chips.length) return;

    const bar = document.createElement('div');
    bar.id = 'risk-summary-bar';
    bar.style.cssText = 'display:flex;gap:8px;flex-wrap:wrap;margin-bottom:24px';
    chips.forEach(c => {
        bar.insertAdjacentHTML('beforeend', `
            <span style="display:inline-flex;align-items:center;gap:6px;padding:4px 12px;border-radius:6px;font-size:12px;font-weight:600;background:${c.bg};color:${c.color};border:1px solid ${c.bd}">
                ${c.count} ${c.label}
            </span>`);
    });

    if (riskData.quick_verdict) {
        bar.insertAdjacentHTML('afterend', `
            <div style="background:var(--gold-dim);border-radius:var(--r-md);padding:10px 14px;margin-bottom:20px;font-size:13px;font-weight:500;color:var(--t2);border:1px solid rgba(201,162,39,.2);line-height:1.65">
                ${escapeHtml(riskData.quick_verdict)}
            </div>`);
    }

    documentSummary.prepend(bar);
}

// ── Simplify ──────────────────────────────────────────────────────────────────
async function simplifyDocument() {
    if (!currentSessionId) { showToast('warning', 'Primero subí un documento'); return; }

    showLoading('Generando versión simplificada…', 'Reescribiendo el documento en lenguaje claro');

    try {
        const response = await fetch(`/api/simplify/${currentSessionId}`);
        const result   = await response.json();

        if (result.success) {
            simplifiedContent.innerHTML = marked.parse(result.simplified_content || '');
            switchTab('simplified');
        } else {
            showToast('error', result.message || 'Error al simplificar');
        }
    } catch (err) {
        console.error(err);
        showToast('error', 'Error de conexión');
    } finally {
        hideLoading();
    }
}

// ── Export PDF ────────────────────────────────────────────────────────────────
function exportReport() {
    if (!currentSessionId) { showToast('warning', 'Primero analizá un documento'); return; }
    window.open(`/api/export/${currentSessionId}`, '_blank');
}

// ── Delete session ────────────────────────────────────────────────────────────
function deleteSession() {
    if (!currentSessionId) return;
    confirmAction(async () => {
        showLoading('Eliminando sesión…');
        try {
            const response = await fetch(`/api/session/${currentSessionId}`, { method: 'DELETE' });
            const result   = await response.json();

            if (result.success) {
                currentSessionId = null;
                showDocMeta(false);
                uploadForm.reset();
                selectedFileName.textContent = '';
                dropzone.classList.remove('has-file');
                analyzeBtn.disabled = true;
                updateHeaderChip('', false);

                // Reset risk badge + dot
                const riskBadge = document.getElementById('riskHeaderBadge');
                if (riskBadge) riskBadge.style.display = 'none';
                hideAnalysisDot();

                clearChatMessages?.();
                const placeholder = document.getElementById('chatPlaceholder');
                if (placeholder) placeholder.style.display = '';
                const quickQs = document.getElementById('quickQuestions');
                if (quickQs) quickQs.style.display = 'none';
                const qInput = document.getElementById('questionInput');
                if (qInput) qInput.disabled = true;
                const sBtn = document.getElementById('sendBtn');
                if (sBtn) sBtn.disabled = true;

                // Reset risk bars
                [countCritical, countHigh, countMedium, countLow].forEach(el => { if (el) el.textContent = '—'; });
                if (clauseList) clauseList.innerHTML = '<div style="font-size:11px;color:rgba(255,255,255,.28);padding:4px 8px">Disponible tras el análisis</div>';

                switchTab('chat');
                showToast('success', 'Sesión eliminada');
                await loadHistory();
            } else {
                showToast('error', result.message || 'Error al eliminar la sesión');
            }
        } catch (err) {
            console.error(err);
            showToast('error', 'Error de conexión');
        } finally {
            hideLoading();
        }
    });
}

// ── DOMContentLoaded ──────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {

    // Tabs
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });

    // Upload form
    uploadForm?.addEventListener('submit', handleDocumentUpload);

    // File input via dropzone
    documentFile.style.display = 'none';
    dropzone?.addEventListener('click', () => documentFile.click());
    dropzone?.addEventListener('keydown', e => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); documentFile.click(); }
    });

    documentFile?.addEventListener('change', () => {
        if (documentFile.files.length > 0) {
            const name = documentFile.files[0].name;
            selectedFileName.textContent = '✓ ' + name;
            dropzone.classList.add('has-file');
            analyzeBtn.disabled = false;
            analyzeBtn.removeAttribute('aria-disabled');
        }
    });

    // Drag & drop
    dropzone?.addEventListener('dragover', e => { e.preventDefault(); dropzone.classList.add('dragover'); });
    dropzone?.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
    dropzone?.addEventListener('drop', e => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            try {
                const dt = new DataTransfer();
                dt.items.add(files[0]);
                documentFile.files = dt.files;
            } catch (_) {}
            selectedFileName.textContent = '✓ ' + files[0].name;
            dropzone.classList.add('has-file');
            analyzeBtn.disabled = false;
        }
    });

    // Action buttons
    document.getElementById('viewSummaryBtn')?.addEventListener('click', viewDocumentSummary);
    document.getElementById('simplifyBtn')?.addEventListener('click', simplifyDocument);
    document.getElementById('deleteSessionBtn')?.addEventListener('click', deleteSession);
    document.getElementById('exportBtn')?.addEventListener('click', exportReport);

    // Load history on startup
    loadHistory();

    // Compare tab: populate selector when opened
    document.querySelector('[data-tab="compare"]')?.addEventListener('click', populateCompareSelector);

    // ── THEME TOGGLE ──────────────────────────────────────────────────────────
    document.getElementById('themeToggle')?.addEventListener('click', function() {
        const html = document.documentElement;
        const next = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
        html.setAttribute('data-theme', next);
        localStorage.setItem('ltm-theme', next);
        this.setAttribute('aria-label', next === 'dark' ? 'Cambiar a modo claro' : 'Cambiar a modo oscuro');
    });

    // Custom select toggle
    document.getElementById('compareSelectTrigger')?.addEventListener('click', function(e) {
        e.stopPropagation();
        const list   = document.getElementById('compareSelectList');
        const isOpen = list?.classList.contains('open');
        list?.classList.toggle('open', !isOpen);
        this.setAttribute('aria-expanded', String(!isOpen));
    });
    // Cerrar custom select al hacer clic fuera
    document.addEventListener('click', function(e) {
        if (!e.target.closest('.custom-sel')) {
            document.getElementById('compareSelectList')?.classList.remove('open');
            document.getElementById('compareSelectTrigger')?.setAttribute('aria-expanded', 'false');
        }
    });
    // Cerrar con Escape
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            document.getElementById('compareSelectList')?.classList.remove('open');
            document.getElementById('compareSelectTrigger')?.setAttribute('aria-expanded', 'false');
        }
    });
});

// ── Comparación de documentos ────────────────────────────────────────────────
async function populateCompareSelector() {
    const selector  = document.getElementById('compareSelector');
    const noSession = document.getElementById('compareNoSession');
    const list      = document.getElementById('compareSelectList');
    const trigger   = document.getElementById('compareSelectTrigger');
    const labelEl   = document.getElementById('compareSelectLabel');
    if (!list) return;

    // reset estado
    if (trigger) { trigger.dataset.value = ''; trigger.setAttribute('aria-expanded', 'false'); }
    if (labelEl) { labelEl.textContent = '— Seleccioná un documento —'; labelEl.className = 'custom-sel-val placeholder'; }
    list.classList.remove('open');

    if (!currentSessionId) {
        if (selector)  selector.style.display = 'none';
        if (noSession) noSession.style.display = '';
        return;
    }

    try {
        const res    = await fetch('/api/history');
        const data   = await res.json();
        const others = (data.history || []).filter(h => h.session_id !== currentSessionId);

        if (!others.length) {
            if (selector)  selector.style.display = 'none';
            if (noSession) { noSession.textContent = 'No hay otros documentos en el historial para comparar.'; noSession.style.display = ''; }
            return;
        }

        list.innerHTML = '';
        others.forEach(h => {
            const name  = h.service_name || h.file_name || h.session_id.slice(0, 8);
            const levelColors = { critical: 'var(--risk-critical)', high: 'var(--risk-high)', medium: 'var(--risk-medium)', low: 'var(--risk-low)' };
            const dotColor = levelColors[h.risk_level_overall] || 'var(--t4)';

            const btn = document.createElement('button');
            btn.className = 'custom-sel-opt';
            btn.type      = 'button';
            btn.setAttribute('role', 'option');
            btn.setAttribute('aria-selected', 'false');
            btn.innerHTML = `<span class="opt-dot" style="background:${dotColor}"></span><span>${escapeHtml(name)}</span>`;

            btn.addEventListener('click', () => {
                list.querySelectorAll('.custom-sel-opt').forEach(o => { o.classList.remove('selected'); o.setAttribute('aria-selected','false'); });
                btn.classList.add('selected');
                btn.setAttribute('aria-selected', 'true');
                if (trigger) { trigger.dataset.value = h.session_id; trigger.setAttribute('aria-expanded', 'false'); }
                if (labelEl) { labelEl.textContent = name; labelEl.className = 'custom-sel-val'; }
                list.classList.remove('open');
            });
            list.appendChild(btn);
        });

        if (selector)  selector.style.display = 'block';
        if (noSession) noSession.style.display = 'none';
    } catch (e) {
        console.error('Error cargando historial para comparar:', e);
    }
}

async function runComparison() {
    const trigger = document.getElementById('compareSelectTrigger');
    const sidB    = trigger?.dataset.value;
    if (!currentSessionId) { showToast('warning', 'Primero subí y analizá un documento'); return; }
    if (!sidB)              { showToast('warning', 'Seleccioná un documento para comparar'); return; }

    showLoading('Comparando documentos…', 'Analizando diferencias con IA');

    try {
        const res  = await fetch('/api/compare', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id_a: currentSessionId, session_id_b: sidB }),
        });
        const data = await res.json();

        if (data.success) {
            const empty  = document.getElementById('compareEmpty');
            const result = document.getElementById('compareResult');
            if (empty)  empty.style.display  = 'none';
            if (result) {
                result.style.display = '';
                result.innerHTML = `
                    <div style="margin-bottom:24px;padding:14px 18px;border-radius:var(--r-lg);background:var(--gold-dim);border:1px solid rgba(201,162,39,.2);display:flex;align-items:center;gap:10px">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--gold)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 20V10"/><path d="M12 20V4"/><path d="M6 20v-6"/></svg>
                        <span style="font-size:12.5px;font-weight:600;color:var(--gold)">${escapeHtml(data.name_a)} vs ${escapeHtml(data.name_b)}</span>
                    </div>
                    <div class="compare-markdown">${marked.parse(data.content)}</div>`;
            }
        } else {
            showToast('error', 'Error al comparar documentos');
        }
    } catch (e) {
        console.error(e);
        showToast('error', 'Error de conexión al comparar');
    } finally {
        hideLoading();
    }
}
