// CheckEasy API Tester - Main JavaScript
const API_BASE = window.location.origin;
let parcourTestData = null;
let testHistory = JSON.parse(localStorage.getItem('apiTestHistory') || '[]');

// === Initialization ===
document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    initEventListeners();
    checkApiStatus();
    loadHistory();
    setInterval(checkApiStatus, 30000);
});

// === Tab Navigation ===
function initTabs() {
    document.querySelectorAll('.nav-item').forEach(btn => {
        btn.addEventListener('click', () => {
            const tabId = btn.dataset.tab;
            document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById(`tab-${tabId}`).classList.add('active');
            document.getElementById('pageTitle').textContent = btn.querySelector('span').textContent;
        });
    });
}

// === Event Listeners ===
function initEventListeners() {
    // Load parcourtest.json
    document.getElementById('loadParcourTest').addEventListener('click', loadParcourTest);
    document.getElementById('clearAll').addEventListener('click', clearAll);

    // Complete Analysis
    document.getElementById('sendComplete').addEventListener('click', sendCompleteAnalysis);
    document.getElementById('formatJson').addEventListener('click', () => formatEditor('requestEditor'));
    document.getElementById('validateJson').addEventListener('click', () => validateEditor('requestEditor'));
    document.getElementById('copyRequest').addEventListener('click', () => copyToClipboard('requestEditor'));
    document.getElementById('copyResponse').addEventListener('click', () => copyToClipboard('responseViewer', true));
    document.getElementById('exportResponse').addEventListener('click', exportResponse);
    document.getElementById('saveToHistory').addEventListener('click', saveCurrentToHistory);

    // Piece selector
    document.getElementById('pieceSelector').addEventListener('change', filterPieces);

    // Classification
    document.getElementById('sendClassify').addEventListener('click', sendClassification);
    document.getElementById('extractForClassify').addEventListener('click', () => extractPieceFor('classify'));

    // Analysis
    document.getElementById('sendAnalyze').addEventListener('click', sendAnalysis);
    document.getElementById('extractForAnalyze').addEventListener('click', () => extractPieceFor('analyze'));

    // Test Étapes
    document.getElementById('sendEtapeTest').addEventListener('click', sendEtapeTest);

    // Logs toggle
    document.getElementById('logsToggle').addEventListener('click', () => {
        document.getElementById('logsPanel').classList.toggle('collapsed');
    });

    // History
    document.getElementById('exportHistory').addEventListener('click', exportHistory);
    document.getElementById('clearHistory').addEventListener('click', clearHistory);

    // Modal
    document.getElementById('closeCompare').addEventListener('click', () => {
        document.getElementById('compareModal').classList.remove('show');
    });
}

// === API Status Check ===
async function checkApiStatus() {
    const statusEl = document.getElementById('apiStatus');
    try {
        const res = await fetch(`${API_BASE}/health`);
        if (res.ok) {
            statusEl.innerHTML = '<span class="status-dot online"></span><span>API en ligne</span>';
        } else {
            statusEl.innerHTML = '<span class="status-dot offline"></span><span>API hors ligne</span>';
        }
    } catch {
        statusEl.innerHTML = '<span class="status-dot offline"></span><span>API inaccessible</span>';
    }
}

// === Load parcourtest.json ===
async function loadParcourTest() {
    try {
        const res = await fetch(`${API_BASE}/parcourtest.json`);
        if (!res.ok) throw new Error('Fichier non trouvé');
        parcourTestData = await res.json();

        // Update main editor
        document.getElementById('requestEditor').value = JSON.stringify(parcourTestData, null, 2);

        // Populate piece selectors
        populatePieceSelectors();

        addLog('success', 'parcourtest.json chargé avec succès');
    } catch (err) {
        addLog('error', `Erreur: ${err.message}`);
    }
}

// === Populate Piece Selectors ===
function populatePieceSelectors() {
    if (!parcourTestData || !parcourTestData.pieces) return;

    const selectors = ['pieceSelector', 'classifyPieceSelect', 'analyzePieceSelect'];
    selectors.forEach(id => {
        const select = document.getElementById(id);
        if (!select) return;

        // Keep first option
        const firstOption = select.options[0];
        select.innerHTML = '';
        select.appendChild(firstOption);

        parcourTestData.pieces.forEach((piece, idx) => {
            const opt = document.createElement('option');
            opt.value = idx;
            opt.textContent = `${piece.nom} (${piece.checkin_pictures?.length || 0} photos)`;
            select.appendChild(opt);
        });
    });
}

// === Filter Pieces ===
function filterPieces() {
    if (!parcourTestData) return;
    const selector = document.getElementById('pieceSelector');
    const value = selector.value;

    if (value === 'all') {
        document.getElementById('requestEditor').value = JSON.stringify(parcourTestData, null, 2);
    } else {
        const filtered = { ...parcourTestData, pieces: [parcourTestData.pieces[parseInt(value)]] };
        document.getElementById('requestEditor').value = JSON.stringify(filtered, null, 2);
    }
}

// === Extract Piece for Endpoint ===
function extractPieceFor(endpoint) {
    const selectId = endpoint === 'classify' ? 'classifyPieceSelect' : 'analyzePieceSelect';
    const editorId = endpoint === 'classify' ? 'classifyEditor' : 'analyzeEditor';
    const select = document.getElementById(selectId);

    if (!parcourTestData || select.value === '') {
        addLog('warning', 'Sélectionnez une pièce à extraire');
        return;
    }

    const piece = parcourTestData.pieces[parseInt(select.value)];
    const payload = {
        piece_id: piece.piece_id,
        nom: piece.nom,
        type: parcourTestData.type || 'Voyageur',
        checkin_pictures: piece.checkin_pictures || [],
        checkout_pictures: piece.checkout_pictures || [],
        etapes: piece.etapes || []
    };

    document.getElementById(editorId).value = JSON.stringify(payload, null, 2);
    addLog('success', `Pièce "${piece.nom}" extraite pour ${endpoint}`);
}

// === Send Complete Analysis ===
async function sendCompleteAnalysis() {
    const editor = document.getElementById('requestEditor');
    const responseViewer = document.getElementById('responseViewer');
    const loading = document.getElementById('loadingOverlay');
    const httpStatus = document.getElementById('httpStatus');
    const responseTime = document.getElementById('responseTime');

    let payload;
    try {
        payload = JSON.parse(editor.value);
    } catch (e) {
        showJsonError('JSON invalide: ' + e.message);
        return;
    }

    loading.classList.add('show');
    addLog('info', 'Envoi vers /analyze-complete...');
    const startTime = Date.now();

    try {
        const res = await fetch(`${API_BASE}/analyze-complete`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const elapsed = Date.now() - startTime;
        const data = await res.json();

        responseTime.textContent = `${elapsed} ms`;
        httpStatus.textContent = res.status;
        httpStatus.className = `status-badge ${res.ok ? 'success' : 'error'}`;

        responseViewer.innerHTML = syntaxHighlight(JSON.stringify(data, null, 2));

        addLog(res.ok ? 'success' : 'error', `Réponse ${res.status} en ${elapsed}ms`);

        // Render visual results and enable button
        if (res.ok && data.pieces_analysis) {
            renderResultsVisualization(data, payload);
            enableVisualButton();
        }

        // Store for history
        window.lastResponse = { endpoint: '/analyze-complete', request: payload, response: data, status: res.status, time: elapsed };
    } catch (err) {
        httpStatus.textContent = 'ERR';
        httpStatus.className = 'status-badge error';
        responseViewer.textContent = `Erreur: ${err.message}`;
        addLog('error', err.message);
    } finally {
        loading.classList.remove('show');
    }
}

// === Send Classification ===
async function sendClassification() {
    const editor = document.getElementById('classifyEditor');
    const responseViewer = document.getElementById('classifyResponse');
    const meta = document.getElementById('classifyMeta');

    let payload;
    try {
        payload = JSON.parse(editor.value);
    } catch (e) {
        addLog('error', 'JSON invalide: ' + e.message);
        return;
    }

    addLog('info', 'Envoi vers /classify-room...');
    const startTime = Date.now();

    try {
        const res = await fetch(`${API_BASE}/classify-room`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const elapsed = Date.now() - startTime;
        const data = await res.json();

        meta.innerHTML = `<span class="status-badge ${res.ok ? 'success' : 'error'}">${res.status}</span><span class="response-time">${elapsed} ms</span>`;
        responseViewer.innerHTML = syntaxHighlight(JSON.stringify(data, null, 2));

        addLog(res.ok ? 'success' : 'error', `Classification terminée en ${elapsed}ms`);
    } catch (err) {
        meta.innerHTML = '<span class="status-badge error">ERR</span>';
        responseViewer.textContent = `Erreur: ${err.message}`;
        addLog('error', err.message);
    }
}

// === Send Analysis ===
async function sendAnalysis() {
    const editor = document.getElementById('analyzeEditor');
    const responseViewer = document.getElementById('analyzeResponse');
    const meta = document.getElementById('analyzeMeta');

    let payload;
    try {
        payload = JSON.parse(editor.value);
    } catch (e) {
        addLog('error', 'JSON invalide: ' + e.message);
        return;
    }

    addLog('info', 'Envoi vers /analyze-with-classification...');
    const startTime = Date.now();

    try {
        const res = await fetch(`${API_BASE}/analyze-with-classification`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const elapsed = Date.now() - startTime;
        const data = await res.json();

        meta.innerHTML = `<span class="status-badge ${res.ok ? 'success' : 'error'}">${res.status}</span><span class="response-time">${elapsed} ms</span>`;
        responseViewer.innerHTML = syntaxHighlight(JSON.stringify(data, null, 2));

        addLog(res.ok ? 'success' : 'error', `Analyse terminée en ${elapsed}ms`);
    } catch (err) {
        meta.innerHTML = '<span class="status-badge error">ERR</span>';
        responseViewer.textContent = `Erreur: ${err.message}`;
        addLog('error', err.message);
    }
}

// === Syntax Highlighting ===
function syntaxHighlight(json) {
    json = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return json.replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g, (match) => {
        let cls = 'json-number';
        if (/^"/.test(match)) {
            if (/:$/.test(match)) {
                cls = 'json-key';
            } else {
                cls = 'json-string';
            }
        } else if (/true|false/.test(match)) {
            cls = 'json-boolean';
        } else if (/null/.test(match)) {
            cls = 'json-null';
        }
        return `<span class="${cls}">${match}</span>`;
    });
}

// === Utility Functions ===
function formatEditor(editorId) {
    const editor = document.getElementById(editorId);
    try {
        const json = JSON.parse(editor.value);
        editor.value = JSON.stringify(json, null, 2);
        hideJsonError();
        addLog('success', 'JSON formaté');
    } catch (e) {
        showJsonError('JSON invalide: ' + e.message);
    }
}

function validateEditor(editorId) {
    const editor = document.getElementById(editorId);
    try {
        JSON.parse(editor.value);
        hideJsonError();
        addLog('success', 'JSON valide ✓');
    } catch (e) {
        showJsonError('JSON invalide: ' + e.message);
    }
}

function showJsonError(msg) {
    const el = document.getElementById('jsonError');
    el.textContent = msg;
    el.classList.add('show');
}

function hideJsonError() {
    document.getElementById('jsonError').classList.remove('show');
}

function copyToClipboard(elementId, isHtml = false) {
    const el = document.getElementById(elementId);
    const text = isHtml ? el.textContent : el.value;
    navigator.clipboard.writeText(text).then(() => addLog('success', 'Copié !'));
}

function clearAll() {
    document.getElementById('requestEditor').value = '';
    document.getElementById('responseViewer').textContent = '';
    document.getElementById('classifyEditor').value = '';
    document.getElementById('classifyResponse').textContent = '';
    document.getElementById('analyzeEditor').value = '';
    document.getElementById('analyzeResponse').textContent = '';
    parcourTestData = null;
    addLog('info', 'Tout effacé');
}

// === Logging ===
function addLog(type, message) {
    const logs = document.getElementById('logsContent');
    const time = new Date().toLocaleTimeString();
    const entry = document.createElement('div');
    entry.className = 'log-entry';
    entry.innerHTML = `<span class="log-time">${time}</span><span class="log-${type}">${message}</span>`;
    logs.insertBefore(entry, logs.firstChild);

    // Keep only last 50 logs
    while (logs.children.length > 50) {
        logs.removeChild(logs.lastChild);
    }
}



// === Export Response ===
function exportResponse() {
    if (!window.lastResponse) {
        addLog('warning', 'Aucune réponse à exporter');
        return;
    }
    const blob = new Blob([JSON.stringify(window.lastResponse.response, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `response-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
    addLog('success', 'Réponse exportée');
}

// === History Management ===
function saveCurrentToHistory() {
    if (!window.lastResponse) {
        addLog('warning', 'Aucune réponse à sauvegarder');
        return;
    }
    const entry = {
        id: Date.now(),
        timestamp: new Date().toISOString(),
        ...window.lastResponse
    };
    testHistory.unshift(entry);
    if (testHistory.length > 50) testHistory = testHistory.slice(0, 50);
    localStorage.setItem('apiTestHistory', JSON.stringify(testHistory));
    loadHistory();
    addLog('success', 'Sauvegardé dans l\'historique');
}

function loadHistory() {
    const list = document.getElementById('historyList');
    if (!list) return;

    if (testHistory.length === 0) {
        list.innerHTML = '<div class="history-empty">📭 Aucun test sauvegardé</div>';
        return;
    }

    list.innerHTML = testHistory.map(item => `
        <div class="history-item" data-id="${item.id}">
            <div class="history-item-header">
                <span class="history-item-endpoint">${item.endpoint}</span>
                <span class="history-item-time">${new Date(item.timestamp).toLocaleString()}</span>
            </div>
            <div class="history-item-meta">
                <span class="status-badge ${item.status < 400 ? 'success' : 'error'}">${item.status}</span>
                <span>${item.time} ms</span>
            </div>
            <div class="history-item-actions">
                <button class="btn btn-secondary" onclick="viewHistoryItem(${item.id})">👁️ Voir</button>
                <button class="btn btn-secondary" onclick="replayHistoryItem(${item.id})">🔄 Rejouer</button>
                <button class="btn btn-danger" onclick="deleteHistoryItem(${item.id})">🗑️</button>
            </div>
        </div>
    `).join('');
}

function viewHistoryItem(id) {
    const item = testHistory.find(h => h.id === id);
    if (!item) return;

    const modal = document.getElementById('compareModal');
    document.getElementById('compareLeft').innerHTML = `<h4>Request</h4><pre class="json-viewer">${syntaxHighlight(JSON.stringify(item.request, null, 2))}</pre>`;
    document.getElementById('compareRight').innerHTML = `<h4>Response (${item.status})</h4><pre class="json-viewer">${syntaxHighlight(JSON.stringify(item.response, null, 2))}</pre>`;
    modal.classList.add('show');
}

function replayHistoryItem(id) {
    const item = testHistory.find(h => h.id === id);
    if (!item) return;

    document.getElementById('requestEditor').value = JSON.stringify(item.request, null, 2);
    document.querySelector('[data-tab="complete"]').click();
    addLog('info', 'Requête chargée depuis l\'historique');
}

function deleteHistoryItem(id) {
    testHistory = testHistory.filter(h => h.id !== id);
    localStorage.setItem('apiTestHistory', JSON.stringify(testHistory));
    loadHistory();
    addLog('info', 'Élément supprimé');
}

function exportHistory() {
    if (testHistory.length === 0) {
        addLog('warning', 'Historique vide');
        return;
    }
    const blob = new Blob([JSON.stringify(testHistory, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `history-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
    addLog('success', 'Historique exporté');
}

function clearHistory() {
    if (!confirm('Effacer tout l\'historique ?')) return;
    testHistory = [];
    localStorage.removeItem('apiTestHistory');
    loadHistory();
    addLog('info', 'Historique effacé');
}


// === Results Visualization ===
// Store original payload pieces for image comparison
let originalPiecesData = {};

function renderResultsVisualization(data, originalPayload) {
    const container = document.getElementById('resultsVisualization');
    if (!container || !data) return;

    // Store original pieces data for image comparison
    if (originalPayload?.pieces) {
        originalPayload.pieces.forEach(p => {
            originalPiecesData[p.piece_id] = p;
        });
    }

    // Show visualization
    container.style.display = 'block';

    // Render global score
    const globalScore = data.analysis_enrichment?.global_score;
    if (globalScore) {
        const scorePercent = (globalScore.score / 5) * 100;
        const scoreCircle = document.querySelector('.score-circle');
        if (scoreCircle) {
            scoreCircle.style.setProperty('--score-percent', `${scorePercent}%`);
            // Change color based on score
            const color = globalScore.score >= 4 ? 'var(--accent-green)' :
                globalScore.score >= 3 ? 'var(--accent-blue)' :
                    globalScore.score >= 2 ? 'var(--accent-orange)' : 'var(--accent-red)';
            scoreCircle.style.background = `conic-gradient(${color} ${scorePercent}%, var(--bg-hover) 0%)`;
        }

        document.getElementById('globalScoreValue').textContent = globalScore.score.toFixed(1);

        const labelEl = document.getElementById('globalScoreLabel');
        labelEl.textContent = globalScore.label;
        labelEl.className = 'score-label ' + globalScore.label.toLowerCase();

        document.getElementById('globalScoreDesc').textContent = globalScore.description;
        document.getElementById('totalIssues').textContent = `${data.total_issues_count || 0} issues détectées`;
    }

    // Render pieces
    const piecesGrid = document.getElementById('piecesGrid');
    if (piecesGrid && data.pieces_analysis) {
        piecesGrid.innerHTML = data.pieces_analysis.map(piece => {
            const originalPiece = originalPiecesData[piece.piece_id];
            return renderPieceCard(piece, originalPiece);
        }).join('');
    }

    // Render recommendations
    if (data.analysis_enrichment?.recommendations?.length > 0) {
        // Remove existing recommendations if any
        const existingRecs = document.querySelector('.recommendations-section');
        if (existingRecs) existingRecs.remove();

        const recsHtml = `
            <div class="recommendations-section">
                <h4><i class="fas fa-lightbulb"></i> Recommandations</h4>
                ${data.analysis_enrichment.recommendations.map((rec, i) => `
                    <div class="recommendation-item">
                        <span class="recommendation-number">${i + 1}</span>
                        <span class="recommendation-text">${rec}</span>
                    </div>
                `).join('')}
            </div>
        `;
        piecesGrid.insertAdjacentHTML('afterend', recsHtml);
    }
}

function renderPieceCard(piece, originalPiece) {
    const status = piece.analyse_globale?.status || 'ok';
    const score = piece.analyse_globale?.score || 5;
    const issues = piece.issues || [];

    // Get images from original payload
    const checkinImages = originalPiece?.checkin_pictures || [];
    const checkoutImages = originalPiece?.checkout_pictures || [];

    const categoryLabels = {
        'cleanliness': '🧹 Propreté',
        'damage': '💔 Dégât',
        'missing_item': '❌ Manquant',
        'added_item': '➕ Ajouté',
        'positioning': '📐 Position',
        'wrong_room': '⚠️ Mauvaise pièce'
    };

    const severityIcons = {
        'high': '🔴',
        'medium': '🟠',
        'low': '🔵'
    };

    return `
        <div class="piece-card">
            <div class="piece-card-header">
                <h4>${piece.nom_piece}</h4>
                <div class="piece-header-actions">
                    <button class="btn-compare" onclick="openImageCompare('${piece.piece_id}')" title="Comparer les images">
                        <i class="fas fa-images"></i> Comparer
                    </button>
                    <span class="piece-status ${status}">${status.toUpperCase()}</span>
                </div>
            </div>
            <div class="piece-card-body">
                <div class="piece-score-row">
                    <div class="piece-score">${score.toFixed(1)}<span>/5</span></div>
                    <div class="piece-meta">
                        <span><i class="fas fa-clock"></i> ${piece.analyse_globale?.temps_nettoyage_estime || 'N/A'}</span>
                        <span><i class="fas fa-exclamation-circle"></i> ${issues.length} issues</span>
                        <span><i class="fas fa-camera"></i> ${checkinImages.length}/${checkoutImages.length} photos</span>
                    </div>
                </div>

                ${piece.analyse_globale?.commentaire_global ? `
                    <div class="piece-comment">
                        <i class="fas fa-comment"></i> ${piece.analyse_globale.commentaire_global}
                    </div>
                ` : ''}

                ${issues.length > 0 ? `
                    <div class="issues-section">
                        <h5>Issues détectées</h5>
                        ${issues.map(issue => {
        const isDoublePass = issue.description?.includes('Objet manquant:') || issue.description?.includes('Objet déplacé:');
        return `
                            <div class="issue-item ${issue.severity} ${isDoublePass ? 'double-pass' : ''}">
                                <div class="issue-icon ${issue.severity}">
                                    ${severityIcons[issue.severity] || '⚪'}
                                </div>
                                <div class="issue-content">
                                    <div class="issue-desc">${issue.description}</div>
                                    <div class="issue-meta">
                                        <span class="issue-category">${categoryLabels[issue.category] || issue.category}</span>
                                        <span>Confiance: ${issue.confidence}%</span>
                                        ${isDoublePass ? '<span class="double-pass-badge">🔎 Double-Pass</span>' : ''}
                                    </div>
                                </div>
                            </div>
                        `}).join('')}
                    </div>
                ` : '<p style="color: var(--accent-green);"><i class="fas fa-check-circle"></i> Aucune issue détectée</p>'}
            </div>
        </div>
    `;
}

// === View Toggle Functions ===
function enableVisualButton() {
    const btn = document.getElementById('btnShowVisual');
    if (btn) {
        btn.disabled = false;
        btn.classList.remove('disabled');
        addLog('info', 'Visualisation disponible - cliquez sur "Visualiser"');
    }
}

function disableVisualButton() {
    const btn = document.getElementById('btnShowVisual');
    if (btn) {
        btn.disabled = true;
        btn.classList.add('disabled');
    }
}

function showVisualView() {
    document.querySelector('.response-panel').style.display = 'none';
    document.getElementById('resultsVisualization').style.display = 'block';
}

function showJsonView() {
    document.querySelector('.response-panel').style.display = 'flex';
    document.getElementById('resultsVisualization').style.display = 'none';
}

// Button: Show Visual
document.getElementById('btnShowVisual')?.addEventListener('click', () => {
    showVisualView();
});

// Button: Back to JSON
document.getElementById('btnBackToJson')?.addEventListener('click', () => {
    showJsonView();
});


// === Image Comparison Modal ===
function openImageCompare(pieceId) {
    const piece = originalPiecesData[pieceId];
    if (!piece) {
        addLog('error', 'Données de pièce non trouvées');
        return;
    }

    const checkinImages = piece.checkin_pictures || [];
    const checkoutImages = piece.checkout_pictures || [];

    // Create modal HTML
    const modalHtml = `
        <div class="image-compare-modal" id="imageCompareModal">
            <div class="modal-content image-modal-content">
                <div class="modal-header">
                    <h3><i class="fas fa-images"></i> Comparaison: ${piece.nom}</h3>
                    <button class="close-modal" onclick="closeImageCompare()">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
                <div class="compare-grid">
                    <div class="compare-column">
                        <h4><i class="fas fa-sign-in-alt"></i> Check-in (Référence)</h4>
                        <div class="image-gallery">
                            ${checkinImages.map((img, i) => `
                                <div class="gallery-item" onclick="openFullImage('${img.url}')">
                                    <img src="${img.url}" alt="Checkin ${i + 1}" loading="lazy">
                                    <span class="img-number">${i + 1}</span>
                                </div>
                            `).join('')}
                            ${checkinImages.length === 0 ? '<p class="no-images">Aucune photo</p>' : ''}
                        </div>
                    </div>
                    <div class="compare-column">
                        <h4><i class="fas fa-sign-out-alt"></i> Check-out (Actuel)</h4>
                        <div class="image-gallery">
                            ${checkoutImages.map((img, i) => `
                                <div class="gallery-item" onclick="openFullImage('${img.url}')">
                                    <img src="${img.url}" alt="Checkout ${i + 1}" loading="lazy">
                                    <span class="img-number">${i + 1}</span>
                                </div>
                            `).join('')}
                            ${checkoutImages.length === 0 ? '<p class="no-images">Aucune photo</p>' : ''}
                        </div>
                    </div>
                </div>
                <div class="compare-slider-section">
                    <h4><i class="fas fa-arrows-alt-h"></i> Comparaison glissante</h4>
                    <div class="slider-controls">
                        <select id="checkinSelect" onchange="updateSliderImages()">
                            ${checkinImages.map((img, i) => `<option value="${img.url}">Checkin ${i + 1}</option>`).join('')}
                        </select>
                        <span>vs</span>
                        <select id="checkoutSelect" onchange="updateSliderImages()">
                            ${checkoutImages.map((img, i) => `<option value="${img.url}">Checkout ${i + 1}</option>`).join('')}
                        </select>
                    </div>
                    <div class="image-slider-container">
                        <div class="slider-wrapper" id="sliderWrapper">
                            <img src="${checkoutImages[0]?.url || ''}" class="slider-img-back" id="sliderImgBack">
                            <div class="slider-img-front-wrapper" id="sliderFrontWrapper">
                                <img src="${checkinImages[0]?.url || ''}" class="slider-img-front" id="sliderImgFront">
                            </div>
                            <input type="range" min="0" max="100" value="50" class="slider-range" id="compareSlider" oninput="updateSlider(this.value)">
                            <div class="slider-line" id="sliderLine"></div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;

    // Remove existing modal
    const existingModal = document.getElementById('imageCompareModal');
    if (existingModal) existingModal.remove();

    // Add modal to body
    document.body.insertAdjacentHTML('beforeend', modalHtml);

    // Initialize slider
    setTimeout(() => updateSlider(50), 100);

    addLog('info', `Comparaison ouverte pour: ${piece.nom}`);
}

function closeImageCompare() {
    const modal = document.getElementById('imageCompareModal');
    if (modal) modal.remove();
}

function updateSlider(value) {
    const frontWrapper = document.getElementById('sliderFrontWrapper');
    const sliderLine = document.getElementById('sliderLine');
    if (frontWrapper) {
        frontWrapper.style.width = `${value}%`;
    }
    if (sliderLine) {
        sliderLine.style.left = `${value}%`;
    }
}

function updateSliderImages() {
    const checkinSelect = document.getElementById('checkinSelect');
    const checkoutSelect = document.getElementById('checkoutSelect');
    const imgFront = document.getElementById('sliderImgFront');
    const imgBack = document.getElementById('sliderImgBack');

    if (checkinSelect && imgFront) {
        imgFront.src = checkinSelect.value;
    }
    if (checkoutSelect && imgBack) {
        imgBack.src = checkoutSelect.value;
    }
}

function openFullImage(url) {
    const fullscreenHtml = `
        <div class="fullscreen-image" id="fullscreenImage" onclick="closeFullImage()">
            <img src="${url}" alt="Full image">
            <button class="close-fullscreen"><i class="fas fa-times"></i></button>
        </div>
    `;
    document.body.insertAdjacentHTML('beforeend', fullscreenHtml);
}

function closeFullImage() {
    const el = document.getElementById('fullscreenImage');
    if (el) el.remove();
}

// Close modal on escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeImageCompare();
        closeFullImage();
    }
});

// === Test Étapes ===
async function sendEtapeTest() {
    const taskName = document.getElementById('etapeTaskName').value;
    const consigne = document.getElementById('etapeConsigne').value;
    const checkingPicture = document.getElementById('etapeCheckingPicture').value;
    const checkoutPicture = document.getElementById('etapeCheckoutPicture').value;

    // Validation
    if (!taskName || !consigne || !checkoutPicture) {
        addLog('warning', 'Veuillez remplir au moins le nom de la tâche, la consigne et la photo APRÈS');
        return;
    }

    // Préparer le payload
    const payload = {
        logement_id: "test_logement_" + Date.now(),
        pieces: [
            {
                piece_id: "test_piece_" + Date.now(),
                nom: "Test",
                commentaire_ia: "",
                checkin_pictures: [],
                checkout_pictures: [],
                etapes: [
                    {
                        etape_id: "test_etape_" + Date.now(),
                        task_name: taskName,
                        consigne: consigne,
                        checking_picture: checkingPicture || "",
                        checkout_picture: checkoutPicture
                    }
                ]
            }
        ]
    };

    // Afficher le loading
    document.getElementById('etapesLoading').style.display = 'flex';
    document.getElementById('etapesResults').style.display = 'none';

    addLog('info', 'Envoi vers /analyze-etapes...');
    const startTime = Date.now();

    try {
        const res = await fetch(`${API_BASE}/analyze-etapes`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const elapsed = Date.now() - startTime;
        const data = await res.json();

        // Masquer le loading
        document.getElementById('etapesLoading').style.display = 'none';

        if (!res.ok) {
            throw new Error(`HTTP ${res.status}: ${data.detail || 'Erreur inconnue'}`);
        }

        // Afficher les résultats
        displayEtapeResults(data, elapsed);

        addLog('success', `Test terminé en ${elapsed}ms`);

    } catch (err) {
        document.getElementById('etapesLoading').style.display = 'none';
        addLog('error', `Erreur: ${err.message}`);
    }
}

function displayEtapeResults(data, elapsed) {
    const resultsDiv = document.getElementById('etapesResults');
    resultsDiv.style.display = 'block';

    // Extraire les issues
    const issues = data.issues || data.preliminary_issues || [];

    // Mettre à jour les statistiques
    document.getElementById('etapeIssuesCount').textContent = issues.length;
    document.getElementById('etapeResponseTime').textContent = `${(elapsed / 1000).toFixed(2)}s`;

    // Afficher les issues
    const issuesList = document.getElementById('etapeIssuesList');
    if (issues.length === 0) {
        issuesList.innerHTML = `
            <div class="no-issues-message">
                <i class="fas fa-check-circle"></i>
                <div class="message-title">Aucun problème détecté !</div>
                <div class="message-subtitle">L'étape a été validée avec succès.</div>
            </div>
        `;
    } else {
        issuesList.innerHTML = issues.map(issue => `
            <div class="issue-card-etape severity-${issue.severity}">
                <div class="issue-card-header">
                    <span class="issue-category-badge">${issue.category}</span>
                    <span class="issue-confidence-badge">Confiance: ${issue.confidence}%</span>
                </div>
                <div class="issue-description-text">${issue.description}</div>
            </div>
        `).join('');
    }

    // Afficher le JSON complet
    const jsonResponse = document.getElementById('etapeJsonResponse');
    jsonResponse.innerHTML = syntaxHighlight(JSON.stringify(data, null, 2));
}