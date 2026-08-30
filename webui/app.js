let currentPage = 1;
let totalPages = 1;

async function api(url, options = {}) {
    const res = await fetch(url, {
        ...options,
        headers: {
            "Content-Type": "application/json",
            ...(options.headers || {})
        }
    });
    if (res.status === 401) {
        document.getElementById("loginOverlay").style.display = "flex";
        throw new Error("unauthorized");
    }
    return res.json();
}

async function doLogin() {
    const pwd = document.getElementById("loginPwd").value;
    const errEl = document.getElementById("loginErr");
    errEl.innerText = "";
    try {
        const res = await api("/api/auth/login", {
            method: "POST",
            body: JSON.stringify({ password: pwd })
        });
        if (res.status === "ok") {
            document.getElementById("loginOverlay").style.display = "none";
            initApp();
        } else {
            errEl.innerText = res.error || "登录失败";
        }
    } catch (e) {
        errEl.innerText = "网络异常或密码错误";
    }
}

async function doLogout() {
    await api("/api/auth/logout", { method: "POST" });
    location.reload();
}

function switchTab(tabId, btn) {
    document.querySelectorAll(".panel").forEach(p => p.classList.remove("on"));
    document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("on"));
    const target = document.getElementById(`p-${tabId}`);
    if (target) target.classList.add("on");
    if (btn) btn.classList.add("on");

    if (tabId === "rank") loadRank();
    if (tabId === "players") loadPlayers(1);
    if (tabId === "stocks") loadStocks();
    if (tabId === "world") loadWorld();
    if (tabId === "config") loadConfig();
}

async function loadMeta() {
    const meta = await api("/api/meta");
    document.getElementById("metaVer").innerText = `v${meta.version}`;
    document.getElementById("metaPort").innerText = `端口: ${meta.port}`;
}

async function loadOverview() {
    const data = await api("/api/overview");
    document.getElementById("statPlayers").innerText = data.players;
    document.getElementById("statMoney").innerText = data.total_money.toLocaleString() + " 元";
    document.getElementById("statCmds").innerText = data.commands;
    document.getElementById("statDb").innerText = data.db_size_kb + " KB";
}

async function loadRank() {
    const data = await api("/api/rank");
    const tbody = document.getElementById("wealthBody");
    tbody.innerHTML = (data.wealth || []).map((u, idx) => `
        <tr>
            <td><strong>#${idx + 1}</strong></td>
            <td>${u.name || u.uid}</td>
            <td>${u.career || '无业'}</td>
            <td><span style="color: var(--primary); font-weight: bold;">${u.value.toLocaleString()} 元</span></td>
        </tr>
    `).join("");
}

async function loadPlayers(page = 1) {
    currentPage = page;
    const res = await api(`/api/players?page=${page}`);
    totalPages = res.pages || 1;
    document.getElementById("pageInfo").innerText = `${currentPage} / ${totalPages}`;
    document.getElementById("prevBtn").disabled = currentPage <= 1;
    document.getElementById("nextBtn").disabled = currentPage >= totalPages;

    const tbody = document.getElementById("playerBody");
    tbody.innerHTML = (res.items || []).map(u => `
        <tr>
            <td><code>${u.uid}</code></td>
            <td>${u.name}</td>
            <td>${u.career}</td>
            <td>Lv.${u.level}</td>
            <td>${u.money} 元</td>
            <td>${u.stamina}</td>
            <td>
                <button class="btn ghost" style="padding: 4px 10px; font-size: 12px;" onclick="editMoney('${u.uid}', ${u.money})">改金币</button>
                <button class="btn ghost" style="padding: 4px 10px; font-size: 12px; color: #ff4d79; border-color: #ff4d79;" onclick="banUser('${u.uid}')">封禁</button>
            </td>
        </tr>
    `).join("");
}

function prevPage() {
    if (currentPage > 1) loadPlayers(currentPage - 1);
}

function nextPage() {
    if (currentPage < totalPages) loadPlayers(currentPage + 1);
}

async function editMoney(uid, current) {
    const val = prompt(`修改玩家 ${uid} 的金币数量:`, current);
    if (val !== null && !isNaN(val)) {
        await api("/api/player/update", {
            method: "POST",
            body: JSON.stringify({ uid, fields: { money: parseInt(val) } })
        });
        loadPlayers(currentPage);
        loadOverview();
    }
}

async function banUser(uid) {
    if (confirm(`确定要封禁玩家 ${uid} 7天吗？`)) {
        await api("/api/player/ban", {
            method: "POST",
            body: JSON.stringify({ uid, days: 7 })
        });
        alert(`已成功封禁 ${uid}`);
    }
}

async function loadStocks() {
    const data = await api("/api/stocks");
    const tbody = document.getElementById("stockBody");
    tbody.innerHTML = (data.stocks || []).map(s => `
        <tr>
            <td><strong>${s.id}</strong></td>
            <td>${s.name}</td>
            <td><input type="number" id="stk_${s.id}" value="${s.price}" step="0.1" style="width: 90px;"></td>
            <td><span style="color: ${s.change >= 0 ? '#ff4d79' : '#2ecc71'}; font-weight: bold;">${s.change >= 0 ? '+' : ''}${s.change}%</span></td>
            <td><button class="btn" style="padding: 4px 10px; font-size: 12px;" onclick="saveStockPrice('${s.id}')">保存</button></td>
        </tr>
    `).join("");
}

async function saveStockPrice(sid) {
    const price = parseFloat(document.getElementById(`stk_${sid}`).value);
    await api("/api/stocks/edit", {
        method: "POST",
        body: JSON.stringify({ id: sid, price })
    });
    alert(`股票 ${sid} 价格已更新为 ${price}`);
    loadStocks();
}

async function loadWorld() {
    const data = await api("/api/world/current");
    const box = document.getElementById("worldEventBox");
    if (data.event) {
        box.innerHTML = `
            <h4 style="color: var(--primary); margin-bottom: 6px;">✨ ${data.event.name}</h4>
            <p>${data.event.desc || '全服随机事件正在生效中'}</p>
        `;
    } else {
        box.innerHTML = `<p>暂无正在进行的世界事件</p>`;
    }
}

async function forceWorldEvent() {
    await api("/api/world/force", { method: "POST" });
    loadWorld();
    alert("已触发新的世界事件！");
}

async function loadConfig() {
    const cfg = await api("/api/config");
    const form = document.getElementById("configForm");
    form.innerHTML = Object.entries(cfg).map(([k, v]) => `
        <div>
            <label style="font-weight: 600; font-size: 14px;">${k}</label>
            <input type="text" id="cfg_${k}" value="${v}" style="width: 100%; margin-top: 4px;">
        </div>
    `).join("");
}

async function saveConfig() {
    const inputs = document.querySelectorAll("#configForm input");
    const payload = {};
    inputs.forEach(input => {
        const k = input.id.replace("cfg_", "");
        payload[k] = input.value;
    });
    await api("/api/config", {
        method: "POST",
        body: JSON.stringify(payload)
    });
    alert("配置已成功更新！");
}

async function initApp() {
    const auth = await api("/api/auth/check");
    if (!auth.authed && auth.auth_required) {
        document.getElementById("loginOverlay").style.display = "flex";
        return;
    }
    loadMeta();
    loadOverview();
    loadRank();
}

window.onload = initApp;
