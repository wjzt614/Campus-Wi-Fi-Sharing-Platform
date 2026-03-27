let currentUser = null;
let bwChart = null;

// ---- Tips carousel ----------------------------------------------------------
const TIPS = [
    "The more you share, the higher your credit and the bigger your consumption discount (up to 30% off).",
    "Share bandwidth during peak hours to double your credit rewards 🔥",
    "Join mutual-aid groups to save more with roommates.",
    "Your flow currency updates in real time when others consume your bandwidth.",
    "New users have a 7-day protection period—no rejection or freezing.",
    "Higher credit means higher sharing gains; rewards up to 2x.",
    "Top 10% on the leaderboard get an extra 5% discount.",
    "Guarantee new users to automatically earn a 1% commission on every consumption they make.",
];
let tipIdx = 0;
function rotateTip() {
    const el = document.getElementById('tipText');
    if (el) { el.style.opacity = 0; setTimeout(() => { el.textContent = TIPS[tipIdx++ % TIPS.length]; el.style.opacity = 1; }, 300); }
}
setInterval(rotateTip, 5000);

// ---- Level config -----------------------------------------------------------
const LEVEL_LABELS  = { diamond: '🦅 Eagle', gold: '🐯 Tiger', silver: '🐬 Dolphin', bronze: '🐢 Turtle' };
const LEVEL_CLASSES = { diamond: 'level-diamond', gold: 'level-gold', silver: 'level-silver', bronze: 'level-bronze' };
const LEVEL_AVATARS = { diamond: '🦅', gold: '🐯', silver: '🐬', bronze: '🐢' };
const DISCOUNT_LABELS = {
    diamond: 'Excellent credit; 30% off',
    gold: 'Good credit; 15% off',
    silver: 'Standard price',
    bronze: 'Insufficient credit; paused'
};

// ---- Utilities --------------------------------------------------------------
function showMessage(msg, type = 'info') {
    const el = document.createElement('div');
    el.className = `message ${type}`;
    el.textContent = msg;
    const c = document.querySelector('.container');
    c.insertBefore(el, c.firstChild);
    setTimeout(() => el.remove(), 4500);
}

function showTab(name) {
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.getElementById(name + 'Tab').classList.add('active');
    document.querySelectorAll('.tab-btn').forEach(b => {
        const onclick = b.getAttribute('onclick') || '';
        if (onclick.includes("'" + name + "'")) b.classList.add('active');
    });
}

function showSection(name) {
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    document.querySelectorAll('.stab').forEach(b => b.classList.remove('active'));
    document.getElementById(name + 'Section').classList.add('active');
    document.querySelectorAll('.stab').forEach(b => {
        if (b.getAttribute('onclick').includes("'" + name + "'")) b.classList.add('active');
    });
    if (name === 'leaderboard') loadLeaderboard();
    if (name === 'coalition') loadCoalitions();
}

// ---- Authentication ---------------------------------------------------------
async function register() {
    const username = document.getElementById('regUsername').value.trim();
    const password = document.getElementById('regPassword').value;
    const email    = document.getElementById('regEmail').value.trim();
    if (!username || !password || !email) { showMessage('Please fill in all fields', 'error'); return; }
    try {
        const res  = await fetch('/api/register', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({username, password, email}) });
        const data = await res.json();
        if (res.ok) { showMessage('Registration successful. Please log in.', 'success'); showTab('login'); }
        else showMessage('Registration failed.', 'error');
    } catch { showMessage('Network error.', 'error'); }
}

async function login() {
    const username = document.getElementById('loginUsername').value.trim();
    const password = document.getElementById('loginPassword').value;
    if (!username || !password) { showMessage('Please enter username and password', 'error'); return; }
    try {
        const res  = await fetch('/api/login', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({username, password}) });
        const data = await res.json();
        if (res.ok) {
            currentUser = data;
            document.getElementById('authSection').style.display = 'none';
            document.getElementById('dashboard').style.display = 'block';
            showMessage('Login successful.', 'success');
            rotateTip();
            refreshStats();
            loadSystemData();
            loadLeaderboard();
            startCurrencyStream(data.user_id);
        } else showMessage('Login failed.', 'error');
    } catch { showMessage('Network error.', 'error'); }
}

// ---- Newcomer guide ---------------------------------------------------------
function updateNewbieGuide(stats) {
    const guide = document.getElementById('newbieGuide');
    if (!stats.new_user_exempt) { guide.style.display = 'none'; return; }
    guide.style.display = '';
    const hasShared = stats.total_bandwidth_shared > 0;
    const hasUsed   = stats.total_bandwidth_used > 0;
    const hasCoal   = !!stats.coalition_id;
    setStep('step1', hasShared);
    setStep('step2', hasUsed);
    setStep('step3', hasCoal);
    if (hasShared && hasUsed && hasCoal) {
        setTimeout(() => { guide.style.display = 'none'; }, 3000);
    }
}
function setStep(id, done) {
    const el = document.getElementById(id);
    const st = document.getElementById(id + 'Status');
    if (done) { el.classList.add('done'); st.textContent = '✅ Done'; }
    else       { el.classList.remove('done'); st.textContent = 'Pending'; }
}

// ---- User stats -------------------------------------------------------------
async function refreshStats() {
    if (!currentUser) return;
    try {
        const res = await fetch(`/api/user-stats/${currentUser.user_id}`);
        if (!res.ok) return;
        const d = await res.json();
        currentUser.reputation_score = d.reputation_score;
        currentUser.virtual_currency = d.virtual_currency;

        // Avatar & level
        document.getElementById('usernameDisplay').textContent = d.username;
        document.getElementById('userAvatar').textContent = LEVEL_AVATARS[d.reputation_level] || '🐬';
        const badge = document.getElementById('levelBadge');
        badge.textContent = LEVEL_LABELS[d.reputation_level] || d.reputation_level;
        badge.className = 'level-badge ' + (LEVEL_CLASSES[d.reputation_level] || '');

        // New user badge
        const newBadge = document.getElementById('newUserBadge');
        newBadge.style.display = d.new_user_exempt ? '' : 'none';

        // Frozen
        document.getElementById('frozenBanner').style.display = d.is_frozen ? '' : 'none';

        // Credit score ring
        document.getElementById('reputationScore').textContent = d.reputation_score.toFixed(0);
        const maxRep = 200, pct = Math.min(d.reputation_score / maxRep, 1);
        const circ = 213.6;
        const fill = document.getElementById('repRingFill');
        fill.style.strokeDashoffset = circ * (1 - pct);
        fill.style.stroke = d.reputation_score >= 90 ? '#81e6d9' : d.reputation_score >= 70 ? '#f6e05e' : d.reputation_score >= 50 ? '#63b3ed' : '#fc8181';
        document.getElementById('reputationDesc').textContent = LEVEL_LABELS[d.reputation_level];

        // Flow currency
        document.getElementById('virtualCurrency').textContent = d.virtual_currency.toFixed(1);

        // Sharing ratio bar chart
        const ratio = d.contribution_ratio;
        document.getElementById('shareBarFill').style.width = (ratio * 100).toFixed(0) + '%';
        const descEl = document.getElementById('contributionDesc');
        if (d.new_user_exempt) {
            descEl.textContent = '🆕 Protection period: no penalties';
            descEl.style.color = '#63b3ed';
        } else if (ratio < 0.1) {
            descEl.textContent = `⚠️ Only ${(ratio*100).toFixed(0)}%. Requests may be rejected.`;
            descEl.style.color = '#fc8181';
        } else if (ratio < 0.2) {
            descEl.textContent = `⚠️ ${(ratio*100).toFixed(0)}%. Price has increased.`;
            descEl.style.color = '#f6ad55';
        } else {
            descEl.textContent = `✅ ${(ratio*100).toFixed(0)}%. Looks good.`;
            descEl.style.color = '#68d391';
        }

        // Sharing gain (discount factor converted to multiplier)
        const gainMult = 1.0 + (d.discount_factor - 0.5) / 0.49;
        document.getElementById('discountFactor').textContent = 'x' + gainMult.toFixed(2);

        // Low-sharing warning count
        document.getElementById('violationCount').textContent = d.violation_count;
        document.getElementById('frozenStatus').textContent = d.is_frozen ? '🔒 Frozen' : `Accumulated ${d.violation_count}/5 warnings`;

        // Guarantee commission
        const earnedCard = document.getElementById('guarantorEarnedCard');
        if (d.guarantor_earned > 0) {
            earnedCard.style.display = '';
            document.getElementById('guarantorEarned').textContent = d.guarantor_earned.toFixed(2);
        }

        // Warning bar
        const warnBar  = document.getElementById('warningBar');
        const warnText = document.getElementById('warningText');
        const warnAct  = document.getElementById('warningAction');
        if (!d.new_user_exempt && ratio < 0.2) {
            warnBar.style.display = '';
            if (ratio < 0.1) {
                const needed = Math.ceil((d.recent_used_30d * 0.1 - d.recent_shared_30d) / 0.9);
                warnText.textContent = `Your sharing ratio is low (${(ratio*100).toFixed(0)}%). Consumption may be rejected or the price may rise.`;
                warnAct.textContent  = `Share about ${Math.max(10, needed)} MB to get back to normal.`;
            } else {
                warnText.textContent = `Low sharing ratio (${(ratio*100).toFixed(0)}%). Current consumption price is +50%.`;
                warnAct.textContent  = 'Click to share bandwidth';
                warnAct.onclick = () => showSection('bandwidth');
            }
        } else {
            warnBar.style.display = 'none';
        }

        // Discount info
        const discountEl = document.getElementById('discountInfo');
        if (discountEl) discountEl.textContent = `${LEVEL_LABELS[d.reputation_level]}  |  ${DISCOUNT_LABELS[d.reputation_level]}`;

        // Trust info
        const trustEl = document.getElementById('myTrustInfo');
        if (trustEl) {
            trustEl.innerHTML = `Trust quota: <strong>${d.trust_quota}</strong> &nbsp;|&nbsp; Guarantor: <strong>${d.guarantor_id || 'None'}</strong> &nbsp;|&nbsp; Mutual-aid group: <strong>${d.coalition_id || 'Not joined'}</strong>`;
        }

        // Advanced details
        const advDelta = document.getElementById('advDelta');
        if (advDelta) {
            advDelta.textContent = d.discount_factor.toFixed(3);
            document.getElementById('advRatio').textContent   = (ratio * 100).toFixed(1) + '%';
            document.getElementById('advReject').textContent  = (d.reject_probability * 100).toFixed(0) + '%';
        }

        // Newcomer guide
        updateNewbieGuide(d);

        // Share preview sync
        updateSharePreview();
    } catch (e) { console.error(e); }
}

// ---- SSE realtime flow currency --------------------------------------------
let _currencyES = null;
function startCurrencyStream(userId) {
    if (_currencyES) _currencyES.close();
    _currencyES = new EventSource(`/api/currency-stream/${userId}`);
    _currencyES.onmessage = (e) => {
        try {
            const d = JSON.parse(e.data);
            if (d.virtual_currency !== undefined) {
                currentUser.virtual_currency = d.virtual_currency;
                const el = document.getElementById('virtualCurrency');
                el.textContent = d.virtual_currency.toFixed(1);
                el.classList.remove('coin-updated');
                void el.offsetWidth;
                el.classList.add('coin-updated');
            }
            // Any transaction (share/use) refreshes the bandwidth pool
            if (d.pool_updated || d.virtual_currency !== undefined) {
                loadSystemData();
            }
        } catch {}
    };
}

// ---- Share preview ---------------------------------------------------------
function updateSharePreview() {
    const amountInput = document.getElementById('shareAmount');
    const valEl = document.getElementById('shareAmountVal');
    const amount = parseFloat(amountInput.value) || 100;
    if (valEl) valEl.textContent = amount;

    const isPeak = document.getElementById('isPeak') && document.getElementById('isPeak').checked;
    const gainEl = document.getElementById('discountFactor');
    let mult = 1.0;
    if (gainEl) {
        const txt = gainEl.textContent.replace('x','');
        mult = parseFloat(txt) || 1.0;
    }
    const baseRep = amount * (isPeak ? 0.2 : 0.1);
    const rep = baseRep * mult;
    const repEl = document.getElementById('shareRepPreview');
    if (repEl) repEl.textContent = `+${rep.toFixed(1)} Credit`;
    const peakTag = document.getElementById('sharePeakTag');
    if (peakTag) peakTag.style.display = isPeak ? '' : 'none';
}

// ---- Cost preview ----------------------------------------------------------
let _previewTimer = null;
async function updateCostPreview() {
    if (!currentUser) return;
    clearTimeout(_previewTimer);
    _previewTimer = setTimeout(async () => {
        const amount = parseFloat(document.getElementById('requestAmount').value);
        if (!amount || amount < 1) { document.getElementById('costPreview').style.display = 'none'; return; }
        try {
            const res = await fetch(`/api/cost-preview?user_id=${currentUser.user_id}&amount=${amount}`);
            if (!res.ok) return;
            const d = await res.json();
            document.getElementById('costPreview').style.display = '';
            document.getElementById('previewCost').textContent = d.estimated_cost.toFixed(3);
            document.getElementById('previewPrice').textContent = `${d.actual_price_per_mb.toFixed(4)} Flow Currency/MB`;
            document.getElementById('previewRepBefore').textContent = d.current_reputation.toFixed(1);
            document.getElementById('previewRepAfter').textContent  = d.after_reputation.toFixed(1);

            // Rejection risk
            const rp = d.reject_probability;
            const dot = document.getElementById('riskDot');
            const rejectEl = document.getElementById('previewReject');
            if (rp === 0) {
                dot.style.background = '#68d391';
                rejectEl.textContent = 'No risk';
                rejectEl.style.color = '#68d391';
            } else if (rp < 0.3) {
                dot.style.background = '#f6ad55';
                rejectEl.textContent = `${(rp*100).toFixed(0)}% Possible rejection`;
                rejectEl.style.color = '#f6ad55';
            } else {
                dot.style.background = '#fc8181';
                rejectEl.textContent = `${(rp*100).toFixed(0)}% Possible rejection`;
                rejectEl.style.color = '#fc8181';
            }

            // New user exemption
            document.getElementById('previewExempt').style.display = d.new_user_exempt ? '' : 'none';

            // Low sharing warning
            const lowWarn = document.getElementById('previewLowShareWarn');
            if (!d.new_user_exempt && d.contribution_ratio < 0.2) {
                lowWarn.style.display = '';
                lowWarn.textContent = d.contribution_ratio < 0.1
                    ? `⚠️ Sharing ratio is only ${(d.contribution_ratio*100).toFixed(0)}%. Please share some bandwidth before consuming.`
                    : `💡 Low sharing ratio (${(d.contribution_ratio*100).toFixed(0)}%). Price has increased by 50%.`;
            } else {
                lowWarn.style.display = 'none';
            }

            // Advanced details
            const advBase = document.getElementById('advBasePrice');
            if (advBase) advBase.textContent = d.base_price.toFixed(4) + ' Flow Currency/MB';
        } catch {}
    }, 400);
}

// ---- Bandwidth operations -------------------------------------------------
async function shareBandwidth() {
    if (!currentUser) { showMessage('Please log in first', 'error'); return; }
    const amount = parseFloat(document.getElementById('shareAmount').value);
    const isPeak = document.getElementById('isPeak').checked;
    if (!amount || amount < 10) { showMessage('Please share at least 10 MB', 'error'); return; }
    try {
        const res  = await fetch('/api/share-bandwidth', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({bandwidth_amount: amount, user_id: currentUser.user_id, is_peak_hour: isPeak}) });
        const data = await res.json();
        if (res.ok) {
            const peakTip = data.is_peak ? ' (Peak hours: credit reward x2)' : '';
            showMessage(`Share successful! Credit +${data.reputation_reward.toFixed(1)}${peakTip}. Wait for others to consume your bandwidth to receive flow currency.`, 'success');
            refreshStats(); loadSystemData();
        } else showMessage('Share failed.', 'error');
    } catch { showMessage('Network error.', 'error'); }
}

async function requestBandwidth() {
    if (!currentUser) { showMessage('Please log in first', 'error'); return; }
    const amount = parseFloat(document.getElementById('requestAmount').value);
    if (!amount || amount < 10) { showMessage('Please request at least 10 MB', 'error'); return; }
    try {
        const res  = await fetch('/api/request-bandwidth', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({bandwidth_amount: amount, user_id: currentUser.user_id}) });
        const data = await res.json();
        if (res.ok) {
            const parts = [];
            if (data.discount > 0)          parts.push(`Credit discount -${(data.discount*100).toFixed(0)}%`);
            if (data.from_coalition)         parts.push('Mutual-aid group -8%');
            if (data.top_bonus > 0)          parts.push('Top 10% on leaderboard -5%');
            if (data.penalty > 1)            parts.push(`Low-sharing price increase +${((data.penalty-1)*100).toFixed(0)}%`);
            const detail = parts.length ? ` (${parts.join(', ')})` : '';
            showMessage(`Requested ${amount}MB successfully! Spent ${data.total_cost.toFixed(2)} Flow Currency${detail}`, 'success');
            refreshStats(); loadSystemData();
        } else showMessage('Request failed.', 'error');
    } catch { showMessage('Network error.', 'error'); }
}

// ---- Bandwidth pool & charts -----------------------------------------------
async function loadSystemData() {
    try {
        const uid = currentUser ? `?user_id=${currentUser.user_id}` : '';
        const res  = await fetch(`/api/available-bandwidth${uid}`);
        if (!res.ok) return;
        const data = await res.json();

        const maxReq = data.max_requestable ?? data.total_available_bandwidth;
        document.getElementById('availableBandwidth').textContent = maxReq.toFixed(1) + ' MB';

        // Pool animation
        const total = data.total_available_bandwidth;
        const tankWater = document.getElementById('tankWater');
        const tankLabel = document.getElementById('tankLabel');
        if (tankWater) {
            const pct = Math.min(total / 1000, 1) * 100;
            tankWater.style.height = Math.max(5, pct) + '%';
        }
        if (tankLabel) tankLabel.textContent = total.toFixed(0) + ' MB';

        // Pool stats
        const poolMax  = document.getElementById('poolMaxRequest');
        const poolMine = document.getElementById('poolMyContrib');
        const poolAvg  = document.getElementById('poolAvgPrice');
        if (poolMax)  poolMax.textContent  = maxReq.toFixed(1) + ' MB';
        if (poolMine) poolMine.textContent = (data.my_contributed ?? 0).toFixed(1) + ' MB';
        if (poolAvg)  poolAvg.textContent  = (data.average_price_per_mb ?? 0).toFixed(3) + ' Flow Currency/MB';

        // Dynamic price
        const dynEl   = document.getElementById('poolDynamicPrice');
        const dynNote = document.getElementById('poolDynamicPriceNote');
        if (dynEl && data.dynamic_base_price !== undefined) {
            dynEl.textContent = data.dynamic_base_price.toFixed(4) + ' Flow Currency/MB';
            const base = 0.1;
            if (data.dynamic_base_price > base) {
                dynEl.style.color = '#fc8181';
                if (dynNote) dynNote.textContent = '⬆ Bandwidth is tight; price increases';
            } else if (data.dynamic_base_price < base) {
                dynEl.style.color = '#68d391';
                if (dynNote) dynNote.textContent = '⬇ Bandwidth is abundant; price decreases';
            } else {
                dynEl.style.color = '#e2e8f0';
                if (dynNote) dynNote.textContent = 'Normal base price';
            }
        }

        renderBandwidthChart(data);
    } catch {}
}

function renderBandwidthChart(data) {
    const ctx = document.getElementById('bandwidthChart');
    if (!ctx) return;
    if (bwChart) bwChart.destroy();
    const avail = data.total_available_bandwidth;
    bwChart = new Chart(ctx.getContext('2d'), {
        type: 'doughnut',
        data: {
            labels: ['Available', 'Allocated', 'Pending match'],
            datasets: [{ data: [avail, avail * 0.3, avail * 0.15],
                backgroundColor: ['#68d391','#63b3ed','#f6ad55'],
                borderWidth: 2, borderColor: 'rgba(0,0,0,0.3)' }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: { position: 'bottom', labels: { color: '#a0aec0', padding: 16 } },
                tooltip: { callbacks: { label: c => `${c.label}: ${c.raw.toFixed(1)} MB` } }
            }
        }
    });
}

// ---- Mutual-aid groups (coalitions) ---------------------------------------
async function createCoalition() {
    if (!currentUser) { showMessage('Please log in first', 'error'); return; }
    const name = document.getElementById('coalitionName').value.trim();
    if (!name) { showMessage('Please enter a mutual-aid group name', 'error'); return; }
    try {
        const res  = await fetch('/api/coalition/create', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({name, user_id: currentUser.user_id}) });
        const data = await res.json();
        if (res.ok) { showMessage(`Mutual-aid group "${data.name}" created successfully. ID: ${data.coalition_id}`, 'success'); loadCoalitions(); refreshStats(); }
        else showMessage('Create failed.', 'error');
    } catch { showMessage('Network error.', 'error'); }
}

async function joinCoalition() {
    if (!currentUser) { showMessage('Please log in first', 'error'); return; }
    const id = parseInt(document.getElementById('joinCoalitionId').value);
    if (!id) { showMessage('Please enter a mutual-aid group ID', 'error'); return; }
    try {
        const res  = await fetch('/api/coalition/join', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({user_id: currentUser.user_id, coalition_id: id}) });
        const data = await res.json();
        if (res.ok) { showMessage('Joined successfully.', 'success'); loadCoalitions(); refreshStats(); }
        else showMessage('Join failed.', 'error');
    } catch { showMessage('Network error.', 'error'); }
}

async function loadCoalitions() {
    try {
        const res  = await fetch('/api/coalitions');
        const data = await res.json();
        const el   = document.getElementById('coalitionList');
        if (!data.coalitions.length) { el.innerHTML = '<div style="color:#718096;padding:20px">No mutual-aid groups found</div>'; return; }
        el.innerHTML = data.coalitions.map(c => `
            <div class="coalition-item" onclick="loadCoalitionDetail(${c.id})" style="cursor:pointer">
                <strong>${c.name}</strong> (ID: ${c.id})&nbsp;|&nbsp;
                Members ${c.member_count} &nbsp;|&nbsp; Shared ${c.total_shared.toFixed(1)} MB
                &nbsp;|&nbsp; Group jackpot <span style="color:#9f7aea">${(c.total_saved||0).toFixed(3)} Flow Currency</span>
                <span style="color:#718096;font-size:.75rem"> Click to view allocation</span>
            </div>
        `).join('');
    } catch {}
}

async function loadCoalitionDetail(id) {
    try {
        const res  = await fetch(`/api/coalition/${id}`);
        const data = await res.json();
        const el   = document.getElementById('myCoalitionDetail');
        el.innerHTML = `<div class="coalition-detail">
            <strong>${data.name}</strong> — Shared ${data.total_shared.toFixed(1)} MB &nbsp;|&nbsp;
            Group jackpot: <span style="color:#9f7aea;font-weight:700">${(data.total_saved||0).toFixed(3)} Flow Currency</span>
            <div style="font-size:.72rem;color:#718096;margin:4px 0 10px">Allocated by each member's contribution ratio</div>
            ${data.members.map(m => `
                <div class="shapley-row">
                    <span>${m.username} <span class="level-badge ${LEVEL_CLASSES[m.reputation_level]}">${LEVEL_LABELS[m.reputation_level]}</span></span>
                    <span>Contributed ${m.shared.toFixed(1)} MB → Jackpot <strong>${m.shapley_value.toFixed(3)} Flow Currency</strong></span>
                </div>
            `).join('')}
        </div>`;
    } catch {}
}

// ---- Trust guarantee -------------------------------------------------------
async function guaranteeUser() {
    if (!currentUser) { showMessage('Please log in first', 'error'); return; }
    const newUserId = parseInt(document.getElementById('guaranteeUserId').value);
    if (!newUserId) { showMessage('Please enter the guaranteed user ID', 'error'); return; }
    try {
        const res  = await fetch('/api/trust/guarantee', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({guarantor_id: currentUser.user_id, new_user_id: newUserId}) });
        const data = await res.json();
        if (res.ok) showMessage('Guarantee successful.', 'success');
        else showMessage('Guarantee failed.', 'error');
    } catch { showMessage('Network error.', 'error'); }
}

// ---- Leaderboard -----------------------------------------------------------
async function loadLeaderboard() {
    try {
        const res  = await fetch('/api/leaderboard');
        const data = await res.json();
        const el   = document.getElementById('leaderboardList');
        if (!data.leaderboard.length) { el.innerHTML = '<div style="color:#718096;padding:20px">No data available</div>'; return; }
        el.innerHTML = data.leaderboard.map(u => {
            const isMe = currentUser && u.username === currentUser.username;
            const rankClass = u.rank === 1 ? 'gold-rank' : u.rank === 2 ? 'silver-rank' : u.rank === 3 ? 'bronze-rank' : '';
            const tags = [];
            if (u.top_bonus)                          tags.push('<span class="lb-tag top">🏅 Top 10%: -5%</span>');
            if (u.total_bandwidth_shared > 500)       tags.push('<span class="lb-tag star">⭐ Sharing Star</span>');
            if (u.reputation_level === 'diamond')     tags.push('<span class="lb-tag helper">🤝 Mutual-aid Expert</span>');
            return `<div class="lb-item ${isMe ? 'me' : ''}">
                <div class="lb-rank ${rankClass}">${u.rank === 1 ? '🥇' : u.rank === 2 ? '🥈' : u.rank === 3 ? '🥉' : u.rank}</div>
                <div style="flex:1">
                    <div class="lb-name">
                        ${LEVEL_AVATARS[u.reputation_level] || ''} ${u.username} ${isMe ? '👤' : ''}
                        <span class="level-badge ${LEVEL_CLASSES[u.reputation_level]}">${LEVEL_LABELS[u.reputation_level]}</span>
                    </div>
                    ${tags.length ? `<div class="lb-tags">${tags.join('')}</div>` : ''}
                    <div class="lb-meta">Credit ${u.reputation_score.toFixed(1)} | Shared ${u.total_bandwidth_shared.toFixed(1)} MB | Flow Currency ${u.virtual_currency.toFixed(1)}</div>
                </div>
            </div>`;
        }).join('');
    } catch {}
}

// ---- Initialization ---------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
    rotateTip();
    loadSystemData();
    loadLeaderboard();
    // Refresh bandwidth pool every 5 seconds
    setInterval(() => { loadSystemData(); }, 5000);
    // Refresh user stats & leaderboard every 30 seconds
    setInterval(() => {
        if (currentUser) { refreshStats(); loadLeaderboard(); }
    }, 30000);
});
