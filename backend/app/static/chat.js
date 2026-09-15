const chat = document.getElementById("chat");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
const badge = document.getElementById("conn-badge");
const sessionList = document.getElementById("session-list");
const newChatBtn = document.getElementById("new-chat");
const replayBtn = document.getElementById("replay-btn");
const replayOverlay = document.getElementById("replay-overlay");
const replayBody = document.getElementById("replay-body");
const replayClose = document.getElementById("replay-close");
const humanBtn = document.getElementById("human-btn");
const ticketBar = document.getElementById("ticket-bar");
const ticketDot = document.getElementById("ticket-dot");
const ticketText = document.getElementById("ticket-text");
const ticketListEl = document.getElementById("ticket-list");
const ticketDetailEl = document.getElementById("ticket-detail");
const ticketRefreshBtn = document.getElementById("ticket-refresh");
const filterSessionBtn = document.getElementById("filter-session");
const filterAllBtn = document.getElementById("filter-all");

let ws = null;
let sessionId = localStorage.getItem("agentservice_session") || "";
let currentBubble = null;
let lastUserMsg = null;
let ticketTimer = null;
let currentTicketId = null;
let lastTicketStatus = null;
let ticketFilter = "session";
let selectedTicketId = null;

const INTENT_LABELS = {
  order: "订单查询",
  logistics: "物流查询",
  refund: "退换货/退款",
  escalate: "投诉/转人工",
  knowledge: "知识库查询",
  fallback: "其他"
};

const WELCOME = "您好，我是智能客服小助。现在可以问我：我的订单到哪了？这个能退吗？退货运费谁出？";

const TICKET_STATUS_LABELS = {
  NEW: "新建/待处理",
  PROCESSING: "处理中",
  ESCALATED: "已升级（超时待人工）",
  RESOLVED: "已解决",
  REFUNDED: "已退款",
  CLOSED: "已关闭"
};

function ticketLabel(status) {
  return TICKET_STATUS_LABELS[status] || status || "未知";
}

function isTicketFinal(status) {
  return status === "RESOLVED" || status === "CLOSED" || status === "REFUNDED";
}

function barClass(status) {
  if (isTicketFinal(status)) return "ok";
  if (status === "ESCALATED") return "warn";
  return "";
}

function showTicketBar(ticket) {
  if (!ticket) return;
  currentTicketId = ticket.id;
  lastTicketStatus = ticket.status;
  ticketBar.className = "ticket-bar " + barClass(ticket.status);
  ticketBar.classList.remove("hidden");
  const escalatedNote = ticket.status === "ESCALATED" ? " · 已超时自动升级，等待人工处理" : "";
  ticketText.textContent = "工单 #" + ticket.id + " · 状态：" + ticketLabel(ticket.status) + escalatedNote;
}

function hideTicketBar() {
  ticketBar.classList.add("hidden");
  currentTicketId = null;
  lastTicketStatus = null;
}

function fmtTime(iso) {
  if (!iso) return "";
  return String(iso).replace("T", " ").slice(0, 19);
}

function renderTicketList(tickets) {
  ticketListEl.innerHTML = "";
  if (!tickets || !tickets.length) {
    const empty = document.createElement("div");
    empty.className = "ticket-empty";
    empty.textContent = ticketFilter === "all"
      ? "暂无工单（转人工/投诉后会自动创建）"
      : "本会话暂无工单（转人工/投诉后会自动创建）";
    ticketListEl.appendChild(empty);
    ticketDetailEl.classList.add("hidden");
    return;
  }
  tickets.forEach(t => {
    const item = document.createElement("div");
    item.className = "ticket-item" + (t.id === selectedTicketId ? " active" : "");
    item.dataset.tid = String(t.id);
    const top = document.createElement("div");
    top.className = "ticket-item-top";
    const title = document.createElement("div");
    title.className = "ticket-item-title";
    title.textContent = t.title || "未命名工单";
    const chip = document.createElement("span");
    chip.className = "ticket-chip " + barClass(t.status);
    chip.textContent = ticketLabel(t.status);
    top.appendChild(title);
    top.appendChild(chip);
    const sub = document.createElement("div");
    sub.className = "ticket-item-sub";
    sub.innerHTML = "";
    const left = document.createElement("span");
    left.textContent = "#" + t.id + " · " + (t.category || "") + "/" + (t.priority || "");
    const right = document.createElement("span");
    right.textContent = fmtTime(t.updated_at || t.updatedAt || "");
    sub.appendChild(left);
    sub.appendChild(right);
    item.appendChild(top);
    item.appendChild(sub);
    item.addEventListener("click", () => selectTicket(t));
    ticketListEl.appendChild(item);
  });
}

function renderTicketDetail(t) {
  ticketDetailEl.innerHTML = "";
  const head = document.createElement("h3");
  head.textContent = "工单 #" + t.id + " 详情";
  ticketDetailEl.appendChild(head);
  const rows = [
    ["状态", ticketLabel(t.status)],
    ["会话", t.session_id || t.sessionId || ""],
    ["分类", t.category || ""],
    ["优先级", t.priority || ""],
    ["创建时间", fmtTime(t.created_at || t.createdAt || "")],
    ["更新时间", fmtTime(t.updated_at || t.updatedAt || "")]
  ];
  rows.forEach(([k, v]) => {
    const row = document.createElement("div");
    row.className = "ticket-detail-row";
    row.innerHTML = "<b>" + k + "：</b>" + escapeHtml(v || "-");
    ticketDetailEl.appendChild(row);
  });
  const actionsTitle = document.createElement("div");
  actionsTitle.className = "ticket-actions-title";
  actionsTitle.textContent = "动作留痕（actions）";
  ticketDetailEl.appendChild(actionsTitle);
  const actions = t.actions || [];
  if (!actions.length) {
    const line = document.createElement("div");
    line.className = "ticket-action-line";
    line.textContent = "（暂无留痕）";
    ticketDetailEl.appendChild(line);
  } else {
    actions.forEach(a => {
      const line = document.createElement("div");
      line.className = "ticket-action-line";
      line.textContent = a;
      ticketDetailEl.appendChild(line);
    });
  }
  ticketDetailEl.classList.remove("hidden");
}

function selectTicket(t) {
  selectedTicketId = t.id;
  renderTicketDetail(t);
  Array.from(ticketListEl.children).forEach(el => {
    el.classList.toggle("active", el.dataset.tid === String(t.id));
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

async function loadTicketPanel() {
  const url = ticketFilter === "all"
    ? "/api/tickets"
    : "/api/tickets?session_id=" + encodeURIComponent(sessionId || "");
  if (!ticketListEl.children.length) {
    const loading = document.createElement("div");
    loading.className = "ticket-empty loading";
    loading.textContent = "工单加载中…";
    ticketListEl.appendChild(loading);
  }
  try {
    const res = await fetch(url);
    const data = await res.json();
    if (data.available) renderTicketList(data.tickets || []);
  } catch (e) {
    renderTicketList([]);
  }
}

function setTicketFilter(mode) {
  ticketFilter = mode;
  filterSessionBtn.classList.toggle("active", mode === "session");
  filterAllBtn.classList.toggle("active", mode === "all");
  selectedTicketId = null;
  ticketDetailEl.classList.add("hidden");
  loadTicketPanel();
}

function stopTicketPolling() {
  if (ticketTimer) {
    clearInterval(ticketTimer);
    ticketTimer = null;
  }
}

async function refreshTicketStatus() {
  if (!sessionId) return;
  try {
    const res = await fetch("/api/tickets?session_id=" + encodeURIComponent(sessionId));
    const data = await res.json();
    if (!data.available) {
      if (!ticketBar.classList.contains("hidden")) ticketText.textContent = "工单服务暂不可用，稍后自动重试…";
      return;
    }
    const list = data.tickets || [];
    if (!list.length) return;
    const t = list[list.length - 1];
    const changed = currentTicketId === t.id && lastTicketStatus && t.status && lastTicketStatus !== t.status;
    const firstSeen = currentTicketId === null;
    if (changed || firstSeen) showTicketBar(t);
    if (changed) {
      addSteps("工单 #" + t.id + " 状态更新 → " + ticketLabel(t.status) +
        (t.status === "ESCALATED" ? "（超时自动升级）" : ""));
    }
    if (!ticketTimer && !isTicketFinal(t.status)) {
      ticketTimer = setInterval(() => {
        refreshTicketStatus();
        loadTicketPanel();
      }, 6000);
    }
    if (isTicketFinal(t.status)) stopTicketPolling();
  } catch (e) {
    /* 轮询失败忽略，下轮重试 */
  }
}

function newSessionId() {
  if (window.crypto && crypto.randomUUID) {
    return crypto.randomUUID().replace(/-/g, "");
  }
  return "s" + Date.now() + Math.floor(Math.random() * 1e6);
}

function addMsg(role, text) {
  const msg = document.createElement("div");
  msg.className = "msg msg-" + role;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  msg.appendChild(bubble);
  chat.appendChild(msg);
  chat.scrollTop = chat.scrollHeight;
  return msg;
}

function addSteps(text) {
  const div = document.createElement("div");
  div.className = "steps";
  div.textContent = text;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

function addProtocol(messages) {
  const details = document.createElement("details");
  details.className = "protocol";
  const summary = document.createElement("summary");
  summary.textContent = "消息协议回放（Planner / Worker / Critic / Ticket）";
  const body = document.createElement("div");
  body.className = "protocol-body";
  messages.forEach(m => {
    const line = document.createElement("div");
    line.className = "protocol-line";
    if (m.role === "planner") {
      const dep = m.task.depends_on && m.task.depends_on.length ? "（依赖 " + m.task.depends_on.join(",") + "）" : "（并行）";
      line.textContent = "planner " + m.task_id + " → 派发 " + m.task.tool + dep;
    } else if (m.role === "worker") {
      const r = m.result || {};
      line.textContent = "worker " + m.task_id + " → " + (r.error ? "结果错误：" + r.error : "结果 found=" + r.found);
    } else if (m.role === "critic") {
      const v = m.verdict || {};
      line.textContent = "critic → " + (v.pass ? "复核通过" : "需转人工") + "：" + v.reason;
    } else if (m.role === "ticket") {
      const tk = m.ticket || {};
      line.textContent = "ticket → " + (tk.id
        ? "自动建单 #" + tk.id + "（" + ticketLabel(tk.status) + "）"
        : "建单失败：" + (m.error || "未知错误"));
    }
    body.appendChild(line);
  });
  details.appendChild(summary);
  details.appendChild(body);
  chat.appendChild(details);
  chat.scrollTop = chat.scrollHeight;
}

function clearChat() {
  chat.innerHTML = "";
  addMsg("agent", WELCOME);
}

function ensureBubble() {
  if (!currentBubble) {
    const msg = document.createElement("div");
    msg.className = "msg msg-agent";
    currentBubble = document.createElement("div");
    currentBubble.className = "bubble";
    msg.appendChild(currentBubble);
    chat.appendChild(msg);
  }
  return currentBubble;
}

function setBadge(text, cls) {
  badge.textContent = text;
  badge.className = "badge" + (cls ? " " + cls : "");
}

function connect() {
  if (!sessionId) sessionId = newSessionId();
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(proto + "://" + location.host + "/ws/chat?session_id=" + sessionId);

  ws.onopen = () => setBadge("已连接 · 流式对话", "ok");
  ws.onclose = () => setBadge("连接断开", "err");
  ws.onerror = () => setBadge("连接异常", "err");

  ws.onmessage = (ev) => {
    const data = JSON.parse(ev.data);
    if (data.type === "session") {
      sessionId = data.session_id;
      localStorage.setItem("agentservice_session", sessionId);
      return;
    }
    if (data.type === "history") {
      clearChat();
      (data.messages || []).forEach(m => {
        if (m.role === "user") addMsg("user", m.content);
        else if (m.role === "assistant") addMsg("agent", m.content);
      });
      chat.scrollTop = chat.scrollHeight;
      renderSessionsHighlight();
      refreshTicketStatus();
      loadTicketPanel();
      return;
    }
    if (data.type === "steps") {
      const brief = data.steps.map(s => s.tool.replace(/_/g, " ")).join(" → ");
      addSteps("处理过程：" + brief);
      return;
    }
    if (data.type === "token") {
      ensureBubble().textContent += data.content;
      chat.scrollTop = chat.scrollHeight;
      return;
    }
    if (data.type === "done") {
      ensureBubble().textContent = data.reply;
      if (data.messages && data.messages.length) addProtocol(data.messages);
      if (data.critic_pass === true) {
        addSteps("Critic 复核通过（未发现幻觉/答非所问）");
      }
      if (data.critic_escalate === true) {
        addSteps("Critic 判定需人工介入");
      }
      if (data.intent && lastUserMsg) {
        const tag = document.createElement("span");
        tag.className = "intent-tag";
        tag.textContent = "意图：" + (INTENT_LABELS[data.intent] || data.intent);
        lastUserMsg.querySelector(".bubble").appendChild(tag);
      }
      lastUserMsg = null;
      currentBubble = null;
      sendBtn.disabled = false;
      humanBtn.disabled = false;
      input.focus();
      if (data.escalated) addSteps("已转人工");
      const tmsg = (data.messages || []).filter(m => m.role === "ticket").pop();
      if (tmsg) {
        if (tmsg.ticket) {
          addSteps("已自动创建工单 #" + tmsg.ticket.id + "（" + ticketLabel(tmsg.ticket.status) + "）");
          refreshTicketStatus();
          loadTicketPanel();
        } else if (tmsg.error) {
          addSteps("工单创建暂不可用（已记录，将尽快补建）");
        }
      }
      loadSessions();
      return;
    }
    if (data.type === "error") {
      ensureBubble().textContent = "出错了：" + (data.message || "未知错误");
      currentBubble = null;
      sendBtn.disabled = false;
      humanBtn.disabled = false;
    }
  };
}

async function openReplay() {
  try {
    const res = await fetch("/api/sessions/" + encodeURIComponent(sessionId) + "/trace");
    const data = await res.json();
    replayBody.innerHTML = "";
    const trace = data.trace || [];
    if (!trace.length) {
      replayBody.textContent = "该会话暂无回放记录。";
    }
    trace.forEach(entry => {
      const block = document.createElement("div");
      block.className = "replay-block";
      const userLine = document.createElement("div");
      userLine.className = "replay-user";
      userLine.textContent = "▶ " + entry.user;
      block.appendChild(userLine);
      (entry.messages || []).forEach(m => {
        const line = document.createElement("div");
        line.className = "replay-line";
        if (m.role === "planner") {
          const dep = m.task.depends_on && m.task.depends_on.length ? "（依赖 " + m.task.depends_on.join(",") + "）" : "（并行）";
          line.textContent = "planner " + m.task_id + " → " + m.task.tool + dep;
        } else if (m.role === "worker") {
          const r = m.result || {};
          line.textContent = "worker " + m.task_id + " → " + (r.error ? "错误：" + r.error : "结果 found=" + r.found);
        } else if (m.role === "critic") {
          const v = m.verdict || {};
          line.textContent = "critic → " + (v.pass ? "复核通过" : "需转人工") + "：" + v.reason;
        } else if (m.role === "ticket") {
          const tk = m.ticket || {};
          line.textContent = "ticket → " + (tk.id
            ? "自动建单 #" + tk.id + "（" + ticketLabel(tk.status) + "）"
            : "建单失败：" + (m.error || "未知错误"));
        }
        block.appendChild(line);
      });
      const replyLine = document.createElement("div");
      replyLine.className = "replay-reply";
      replyLine.textContent = "回答：" + entry.reply;
      block.appendChild(replyLine);
      replayBody.appendChild(block);
    });
    replayOverlay.classList.remove("hidden");
  } catch (e) {
    alert("回放加载失败：" + e.message);
  }
}

async function loadSessions() {
  try {
    const res = await fetch("/api/sessions");
    const data = await res.json();
    renderSessions(data.sessions || []);
  } catch (e) {
    /* 忽略：侧栏拉取失败不阻塞对话 */
  }
}

function renderSessions(sessions) {
  sessionList.innerHTML = "";
  sessions.forEach(s => {
    const li = document.createElement("li");
    li.className = "session-item" + (s.session_id === sessionId ? " active" : "");

    const main = document.createElement("div");
    main.className = "session-main";
    const title = document.createElement("div");
    title.className = "session-title";
    title.textContent = s.title || "新对话";
    const sub = document.createElement("div");
    sub.className = "session-sub";
    sub.textContent = (s.count ? s.count + " 条 · " : "") + (s.updated_at || "").slice(5, 16);
    main.appendChild(title);
    main.appendChild(sub);

    const del = document.createElement("button");
    del.className = "session-del";
    del.textContent = "×";
    del.title = "删除该对话";
    del.addEventListener("click", (e) => {
      e.stopPropagation();
      deleteSession(s.session_id);
    });

    li.appendChild(main);
    li.appendChild(del);
    li.addEventListener("click", () => switchSession(s.session_id));
    sessionList.appendChild(li);
  });
}

function renderSessionsHighlight() {
  Array.from(sessionList.children).forEach(li => {
    li.classList.toggle("active", li.dataset.sid === sessionId);
  });
}

function switchSession(id) {
  if (id === sessionId) return;
  sessionId = id;
  localStorage.setItem("agentservice_session", sessionId);
  stopTicketPolling();
  hideTicketBar();
  clearChat();
  if (ws) ws.close();
  connect();
  loadTicketPanel();
}

function newChat() {
  sessionId = newSessionId();
  localStorage.setItem("agentservice_session", sessionId);
  stopTicketPolling();
  hideTicketBar();
  clearChat();
  if (ws) ws.close();
  connect();
  loadSessions();
  loadTicketPanel();
}

async function deleteSession(id) {
  if (!confirm("删除这个对话？")) return;
  try {
    await fetch("/api/sessions/" + encodeURIComponent(id), { method: "DELETE" });
  } catch (e) {
    /* 忽略 */
  }
  if (id === sessionId) newChat();
  else loadSessions();
}

function sendMessage() {
  const text = input.value.trim();
  if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
  lastUserMsg = addMsg("user", text);
  input.value = "";
  sendBtn.disabled = true;
  humanBtn.disabled = true;
  ws.send(JSON.stringify({ type: "user", message: text }));
}

function sendText(text) {
  if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
  lastUserMsg = addMsg("user", text);
  sendBtn.disabled = true;
  humanBtn.disabled = true;
  ws.send(JSON.stringify({ type: "user", message: text }));
}

sendBtn.addEventListener("click", sendMessage);
humanBtn.addEventListener("click", () => sendText("请转人工客服，帮我升级处理"));
ticketRefreshBtn.addEventListener("click", () => {
  refreshTicketStatus();
  loadTicketPanel();
});
filterSessionBtn.addEventListener("click", () => setTicketFilter("session"));
filterAllBtn.addEventListener("click", () => setTicketFilter("all"));
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendMessage();
});
newChatBtn.addEventListener("click", newChat);
replayBtn.addEventListener("click", openReplay);
replayClose.addEventListener("click", () => replayOverlay.classList.add("hidden"));
replayOverlay.addEventListener("click", (e) => {
  if (e.target === replayOverlay) replayOverlay.classList.add("hidden");
});

connect();
loadSessions();
