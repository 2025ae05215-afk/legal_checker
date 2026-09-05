document.addEventListener('DOMContentLoaded', () => {
    const btnAnalyze = document.getElementById('btnAnalyze');
    const btnLoadSample = document.getElementById('btnLoadSample');
    const btnClear = document.getElementById('btnClear');
    const btnExport = document.getElementById('btnExport');
    const fileUpload = document.getElementById('fileUpload');
    const clauseTextInput = document.getElementById('clauseText');
    const clauseIdInput = document.getElementById('clauseId');
    const toggleWhitelist = document.getElementById('toggleWhitelist');

    const issuesListEl = document.getElementById('issuesList');
    const inlineDisplayEl = document.getElementById('inlineDisplay');
    const correctedDisplayEl = document.getElementById('correctedDisplay');
    const issueCounterEl = document.getElementById('issueCounter');

    const metricClauses = document.getElementById('metricClauses');
    const metricIssues = document.getElementById('metricIssues');
    const metricResolved = document.getElementById('metricResolved');
    const metricConfidence = document.getElementById('metricConfidence');

    let currentIssues = [];
    let originalText = "";
    let activeReplacements = {}; // index/key -> chosen string
    let resolvedCount = 0;

    // Sample Contract Clause containing both genuine typos and valid legal terms
    const SAMPLE_LEGAL_CLAUSE = 
`Section 8.2 (Indemnification and Liability).
WHEREAS, the Contractor agree to indemnify, defend, and hold harmless the Client and its Affiliates against any and all tortious actions, damages, and liquidatted claims arising hereunder.
Notwithstanding anything to the contrary herein, the obligations shall be hold valid in perpetuity; provided that neither party shall be liable for force majeure events.
In witness whereof, the promisor hereto has executed this Agreement as of the Effective Date.`;

    btnLoadSample.addEventListener('click', () => {
        clauseIdInput.value = "Section 8.2";
        clauseTextInput.value = SAMPLE_LEGAL_CLAUSE;
    });

    btnClear.addEventListener('click', () => {
        clauseTextInput.value = "";
        inlineDisplayEl.innerHTML = "";
        correctedDisplayEl.innerText = "";
        issuesListEl.innerHTML = '<div class="empty-state"><p>No active errors.</p></div>';
        resetMetrics();
    });

    btnAnalyze.addEventListener('click', () => {
        const text = clauseTextInput.value.trim();
        const cid = clauseIdInput.value.trim() || "Clause 1.0";
        if (!text) {
            alert("Please provide legal text or upload a batch file.");
            return;
        }
        submitSingleClause(text, cid);
    });

    fileUpload.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (!file) return;

        const formData = new FormData();
        formData.append('file', file);

        fetch('/api/upload', {
            method: 'POST',
            body: formData
        })
        .then(res => res.json())
        .then(data => {
            if (data.success && data.results.length > 0) {
                // Load first clause to UI and report batch statistics
                const first = data.results[0];
                clauseIdInput.value = first.clause_id;
                clauseTextInput.value = first.original_text;
                renderAnalysisResults(first.original_text, first.issues, first.clause_id);
                metricClauses.innerText = data.batch_count;
                alert(`Successfully parsed ${data.batch_count} clauses from batch file.`);
            } else {
                alert("Upload failed: " + (data.error || "Unknown error"));
            }
        })
        .catch(err => alert("File upload request error: " + err));
    });

    btnExport.addEventListener('click', () => {
        const text = correctedDisplayEl.innerText;
        if (!text) return;
        navigator.clipboard.writeText(text);
        alert("Corrected clause copied to clipboard.");
    });

    function submitSingleClause(text, clauseId) {
        fetch('/api/check', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text, clause_id: clauseId })
        })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                metricClauses.innerText = "1";
                renderAnalysisResults(data.original_text, data.issues, data.clause_id);
            }
        })
        .catch(err => console.error("API error:", err));
    }

    function renderAnalysisResults(text, issues, clauseId) {
        originalText = text;
        currentIssues = issues;
        activeReplacements = {};
        resolvedCount = 0;

        // Update metrics
        metricIssues.innerText = issues.length;
        metricResolved.innerText = "0";
        issueCounterEl.innerText = `${issues.length} Issues`;
        metricConfidence.innerText = issues.length === 0 ? "100%" : `${Math.max(70, 100 - (issues.length * 4))}%`;

        renderIssueCards(issues);
        renderInlineHighlight(text, issues);
        updateCorrectedView();
    }

    function renderIssueCards(issues) {
        issuesListEl.innerHTML = "";
        if (issues.length === 0) {
            issuesListEl.innerHTML = '<div class="empty-state"><p>✓ No spelling or syntactic defects found. Archaic legal phrasing preserved.</p></div>';
            return;
        }

        issues.forEach((issue, idx) => {
            const card = document.createElement('div');
            card.className = `issue-card ${issue.category}`;
            card.id = `issue-card-${idx}`;

            let suggestionsHtml = "";
            if (issue.suggestions && issue.suggestions.length > 0) {
                suggestionsHtml = issue.suggestions.map(s => 
                    `<button class="suggestion-btn" onclick="window.applySuggestion(${idx}, '${escapeHtml(s.text)}')">
                        ${escapeHtml(s.text)} <small>(${Math.round(s.score * 100)}%)</small>
                     </button>`
                ).join("");
            }

            card.innerHTML = `
                <div class="issue-meta">
                    <span>${escapeHtml(issue.clause_id)} | ${escapeHtml(issue.error_type)}</span>
                    <span class="badge">${issue.category.toUpperCase()}</span>
                </div>
                <div class="issue-desc">
                    Defect: <strong>"${escapeHtml(issue.original)}"</strong><br>
                    <small style="color: #64748b;">${escapeHtml(issue.description)}</small>
                </div>
                <div class="suggestion-pill-box">
                    ${suggestionsHtml}
                </div>
                <div class="card-actions">
                    <button class="btn btn-outline btn-sm" onclick="window.dismissIssue(${idx})">Ignore</button>
                </div>
            `;
            issuesListEl.appendChild(card);
        });
    }

    function renderInlineHighlight(text, issues) {
        let annotated = escapeHtml(text);
        
        // Sort issues by reverse length to avoid nested replacement collisions
        const sorted = [...issues].sort((a, b) => b.original.length - a.original.length);

        sorted.forEach((issue, idx) => {
            const regex = new RegExp(`\\b${escapeRegExp(issue.original)}\\b`, 'g');
            annotated = annotated.replace(regex, (match) => {
                return `<span class="token-highlight ${issue.category}" data-issue-index="${idx}">${match}</span>`;
            });
        });

        inlineDisplayEl.innerHTML = annotated;
    }

    function updateCorrectedView() {
        let result = originalText;
        for (const [orig, fix] of Object.entries(activeReplacements)) {
            const regex = new RegExp(`\\b${escapeRegExp(orig)}\\b`, 'g');
            result = result.replace(regex, fix);
        }
        correctedDisplayEl.innerText = result;
    }

    window.applySuggestion = function(idx, suggestedFix) {
        const issue = currentIssues[idx];
        if (!issue) return;

        activeReplacements[issue.original] = suggestedFix;
        resolvedCount++;
        metricResolved.innerText = resolvedCount;

        // Grey out resolved card
        const card = document.getElementById(`issue-card-${idx}`);
        if (card) {
            card.style.opacity = "0.5";
            card.style.pointerEvents = "none";
        }

        updateCorrectedView();
    };

    window.dismissIssue = function(idx) {
        const card = document.getElementById(`issue-card-${idx}`);
        if (card) {
            card.style.display = "none";
        }
    };

    function resetMetrics() {
        metricClauses.innerText = "0";
        metricIssues.innerText = "0";
        metricResolved.innerText = "0";
        metricConfidence.innerText = "100%";
        issueCounterEl.innerText = "0 Issues";
    }

    function escapeHtml(string) {
        return String(string).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function escapeRegExp(string) {
        return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }
});
