"use strict";

const $ = (selector) => document.querySelector(selector);
const messages = $("#messages");
const form = $("#chat-form");
const input = $("#message-input");
const sendButton = $("#send-button");
const workingIndicator = $("#working-indicator");
const errorBanner = $("#error-banner");
let busy = false;
let pendingConfirmation = null;
let renderedHistory = "";
let toastTimer = null;
let currentState = null;
let currentView = "chat";

function applyTheme(theme) {
  const dark = theme === "dark";
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  const toggle = $("#theme-toggle");
  toggle.textContent = dark ? "☀" : "☾";
  toggle.setAttribute("aria-label", dark ? "Ativar modo claro" : "Ativar modo escuro");
  toggle.title = dark ? "Ativar modo claro" : "Ativar modo escuro";
  toggle.setAttribute("aria-pressed", String(dark));
}

let savedTheme = "light";
try { savedTheme = localStorage.getItem("nova-theme") === "dark" ? "dark" : "light"; } catch (_) { /* armazenamento local indisponível */ }
applyTheme(savedTheme);
$("#theme-toggle").addEventListener("click", () => {
  const theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  applyTheme(theme);
  try { localStorage.setItem("nova-theme", theme); } catch (_) { /* tema vale até fechar esta janela */ }
});

function showToast(text) {
  const toast = $("#toast");
  toast.textContent = text;
  toast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("visible"), 3200);
}

function showError(text) {
  errorBanner.textContent = text;
  errorBanner.hidden = false;
}

function clearError() {
  errorBanner.textContent = "";
  errorBanner.hidden = true;
}

function setBusy(value, label = "A Nova está pensando…") {
  busy = value;
  sendButton.disabled = value;
  input.disabled = value;
  workingIndicator.hidden = !value;
  $("#working-label").textContent = label;
}

function makeId() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((value) => value.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

async function rpc(op, payload = {}) {
  const id = makeId();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 65000);
  try {
    const response = await fetch("/api/v1/rpc", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version: 1, id, op, payload }),
      signal: controller.signal,
      cache: "no-store",
    });
    let envelope;
    try { envelope = await response.json(); } catch (_) { throw new Error("O núcleo retornou uma resposta inválida."); }
    if (envelope.id !== id) throw new Error("A resposta não corresponde a esta requisição.");
    if (!response.ok || envelope.ok !== true) {
      const error = envelope.error || {};
      throw new Error(error.message || `A operação falhou (HTTP ${response.status}).`);
    }
    return envelope.result;
  } catch (error) {
    if (error.name === "AbortError") throw new Error("A operação excedeu o tempo de espera. Confira o histórico antes de tentar novamente.");
    if (error instanceof TypeError) throw new Error("Não consegui alcançar o núcleo local da Nova.");
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

async function establishSession() {
  const token = decodeURIComponent(location.hash.slice(1));
  if (!token) return;
  const response = await fetch("/api/v1/session", {
    method: "POST",
    credentials: "same-origin",
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!response.ok) throw new Error("Não foi possível abrir uma sessão segura com a Nova.");
  history.replaceState(null, "", location.pathname);
}

function formatTime(value) {
  if (typeof value !== "string") return "Horário local";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value.replace("T", " ").slice(0, 16);
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(parsed);
}

function renderHistory(history) {
  const snapshot = JSON.stringify(history || []);
  if (snapshot === renderedHistory) return;
  renderedHistory = snapshot;
  messages.replaceChildren();
  const items = (history || []).filter((item) => item && ["user", "assistant"].includes(item.role) && typeof item.content === "string");
  for (const item of items) {
    const wrapper = document.createElement("article");
    wrapper.className = `message ${item.role}`;
    const meta = document.createElement("span");
    meta.className = "message-meta";
    meta.textContent = item.role === "user" ? "Você" : "Nova";
    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    bubble.textContent = item.content;
    wrapper.append(meta, bubble);
    messages.append(wrapper);
  }
  $("#welcome").hidden = items.length > 0;
  messages.scrollTop = messages.scrollHeight;
}

function appendMessage(role, content) {
  const wrapper = document.createElement("article");
  wrapper.className = `message ${role}`;
  const meta = document.createElement("span");
  meta.className = "message-meta";
  meta.textContent = role === "user" ? "Você" : "Nova";
  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  bubble.textContent = content;
  wrapper.append(meta, bubble);
  messages.append(wrapper);
  $("#welcome").hidden = true;
  messages.scrollTop = messages.scrollHeight;
}

function renderState(state) {
  if (!state || typeof state !== "object") throw new Error("O núcleo retornou um estado inválido.");
  currentState = state;
  const dot = $("#connection-dot");
  dot.classList.remove("disconnected");
  dot.classList.add("connected");
  $("#connection-label").textContent = "Conectada ao núcleo Python";
  $("#activity-label").textContent = state.ai_busy ? "Nova está respondendo" : "Nova está por aqui";
  $("#pet-pose").textContent = state.pose_label || "Disponível para conversar";
  const name = typeof state.user_name === "string" && state.user_name.trim() ? `, ${state.user_name.trim()}` : "";
  $("#user-greeting").textContent = name;
  const provider = typeof state.provider === "string" ? state.provider : "ollama";
  $("#provider-value").textContent = provider;
  $("#provider-label").textContent = provider === "ollama" ? "Ollama · local" : `${provider} · configurado`;
  $("#mode-value").textContent = state.mode || "companhia";
  const focusActive = state.focus_mode && state.focus_mode !== "idle";
  $("#focus-title").textContent = focusActive ? (state.focus_mode === "focus" ? "Sessão de foco ativa" : "Pausa ativa") : "Sem sessão ativa";
  $("#focus-subtitle").textContent = focusActive ? (state.focus_goal || "A Nova está acompanhando seu ritmo.") : "Quando quiser, começamos.";
  $("#start-focus-shortcut").textContent = focusActive ? "Parar" : "Iniciar";
  $("#start-focus-shortcut").dataset.stopFocus = focusActive ? "true" : "false";
  const reminderList = $("#reminder-list");
  reminderList.replaceChildren();
  const reminders = (state.reminders || []).filter((item) => item && !item.done).slice(0, 3);
  if (!reminders.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "Nenhum lembrete pendente.";
    reminderList.append(empty);
  } else {
    for (const reminder of reminders) {
      const row = document.createElement("div");
      row.className = "reminder-item";
      const text = document.createElement("strong");
      text.textContent = typeof reminder.text === "string" ? reminder.text : "Lembrete";
      const time = document.createElement("span");
      time.textContent = formatTime(reminder.at);
      row.append(text, time);
      reminderList.append(row);
    }
  }
  renderHistory(state.history);
  renderDataViews();
  if (busy !== Boolean(state.ai_busy) && !busy) setBusy(Boolean(state.ai_busy));
}

function showView(view) {
  currentView = view;
  document.querySelector(".chat-layout").hidden = view !== "chat";
  $("#history-view").hidden = view !== "history";
  $("#reminders-view").hidden = view !== "reminders";
  $("#page-title").textContent = view === "chat" ? "Conversa" : view === "history" ? "Histórico" : "Lembretes";
  document.querySelectorAll(".nav-item[data-view]").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  if (currentState) renderDataViews();
}

function renderDataViews() {
  if (!currentState) return;
  const list = $("#history-list");
  list.replaceChildren();
  const historyItems = (currentState.history || []).filter((item) => item && typeof item.content === "string");
  if (!historyItems.length) {
    const empty = document.createElement("p"); empty.className = "muted"; empty.textContent = "Ainda não há mensagens salvas."; list.append(empty);
  }
  for (const item of [...historyItems].reverse()) {
    const row = document.createElement("article"); row.className = "record-row";
    const copy = document.createElement("div");
    const title = document.createElement("strong"); title.textContent = item.role === "user" ? "Você" : "Nova";
    const stamp = document.createElement("span"); stamp.textContent = formatTime(item.timestamp);
    const body = document.createElement("p"); body.textContent = item.content;
    copy.append(title, stamp, body);
    const remove = document.createElement("button"); remove.className = "text-action"; remove.textContent = "Apagar";
    remove.addEventListener("click", () => mutate("history.delete", { index: item.index }, "Mensagem apagada."));
    row.append(copy, remove); list.append(row);
  }
  const reminderList = $("#reminders-view-list");
  reminderList.replaceChildren();
  const reminders = currentState.reminders || [];
  if (!reminders.length) { const empty = document.createElement("p"); empty.className = "muted"; empty.textContent = "Nenhum lembrete cadastrado."; reminderList.append(empty); }
  for (const item of reminders) {
    const row = document.createElement("article"); row.className = `record-row${item.done ? " completed" : ""}`;
    const copy = document.createElement("div"); const title = document.createElement("strong"); title.textContent = item.text || "Lembrete";
    const stamp = document.createElement("span"); stamp.textContent = `${formatTime(item.at)}${item.done ? " · Concluído" : " · Pendente"}`;
    copy.append(title, stamp);
    const actions = document.createElement("div"); actions.className = "record-actions";
    if (!item.done) { const complete = document.createElement("button"); complete.className = "text-action"; complete.textContent = "Concluir"; complete.addEventListener("click", () => mutate("reminder.complete", { index: item.index }, "Lembrete concluído.")); actions.append(complete); }
    const remove = document.createElement("button"); remove.className = "text-action"; remove.textContent = "Excluir"; remove.addEventListener("click", () => mutate("reminder.delete", { index: item.index }, "Lembrete excluído."));
    actions.append(remove); row.append(copy, actions); reminderList.append(row);
  }
}

async function mutate(operation, payload, successMessage) {
  try { const result = await rpc(operation, payload); await refreshState(); showToast(result.message || successMessage); }
  catch (error) { showError(error.message); }
}

async function refreshState() {
  try {
    const state = await rpc("state.get");
    renderState(state);
    return state;
  } catch (error) {
    $("#connection-dot").classList.add("disconnected");
    $("#connection-label").textContent = "Núcleo indisponível";
    showError(error.message);
    return null;
  }
}

async function sendMessage(text) {
  const message = (text || "").trim();
  if (!message || busy || message.length > 4000) return;
  clearError();
  setBusy(true, "A Nova está pensando…");
  try {
    const result = await rpc("chat.send", { message });
    if (result && result.confirmation_required) {
      pendingConfirmation = result;
      appendMessage("user", result.question || message);
      $("#confirm-app-name").textContent = result.app_name || "aplicativo";
      $("#confirm-app-command").textContent = result.command || "Comando não disponível";
      $("#confirmation-dialog").showModal();
      setBusy(false);
      await refreshState();
      return;
    }
    await refreshState();
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy(false);
    input.focus();
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = input.value;
  input.value = "";
  input.style.height = "auto";
  sendMessage(text);
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});
input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
});

document.querySelectorAll(".prompt-chip").forEach((button) => {
  button.addEventListener("click", () => sendMessage(button.dataset.prompt));
});

document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => showView(button.dataset.view)));
$("#clear-history").addEventListener("click", () => {
  if (currentState?.history?.length && window.confirm("Apagar todas as mensagens do histórico?")) mutate("history.clear", {}, "Histórico apagado.");
});
$("#reminder-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const at = $("#reminder-at").value;
  const text = $("#reminder-text").value.trim();
  if (!at || !text) return;
  try { const result = await rpc("reminder.add", { at, text }); event.currentTarget.reset(); await refreshState(); showToast(result.message || "Lembrete adicionado."); }
  catch (error) { showError(error.message); }
});

$("#refresh-button").addEventListener("click", refreshState);

$("#start-focus-shortcut").addEventListener("click", async (event) => {
  if (event.currentTarget.dataset.stopFocus === "true") {
    try { await rpc("focus.stop"); await refreshState(); showToast("Sessão de foco encerrada."); }
    catch (error) { showError(error.message); }
    return;
  }
  $("#focus-dialog").showModal();
  $("#focus-goal-input").focus();
});

$("#cancel-focus-button").addEventListener("click", () => $("#focus-dialog").close());
$("#focus-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const focusMinutes = Number($("#focus-minutes-input").value);
  const breakMinutes = Number($("#break-minutes-input").value);
  const goal = $("#focus-goal-input").value.trim();
  if (!Number.isInteger(focusMinutes) || focusMinutes < 5 || focusMinutes > 180 || !Number.isInteger(breakMinutes) || breakMinutes < 1 || breakMinutes > 60) {
    showToast("Use foco de 5–180 min e pausa de 1–60 min.");
    return;
  }
  try {
    const result = await rpc("focus.start", { goal, focus_minutes: focusMinutes, break_minutes: breakMinutes });
    $("#focus-dialog").close();
    showToast(result.message || "Sessão iniciada pela Nova.");
    await refreshState();
  } catch (error) { showError(error.message); }
});

async function cancelPendingAppConfirmation() {
  const pending = pendingConfirmation;
  pendingConfirmation = null;
  if (!pending) return;
  try { await rpc("app.confirm", { confirmation_id: pending.confirmation_id, confirmed: false }); await refreshState(); }
  catch (error) { showError(error.message); }
}

$("#cancel-app-button").addEventListener("click", async () => {
  $("#confirmation-dialog").close();
  await cancelPendingAppConfirmation();
});

// Escape fires the native dialog's cancel event. Route it through the same
// cancellation RPC as the button so the Python core releases its token.
$("#confirmation-dialog").addEventListener("cancel", (event) => {
  event.preventDefault();
  $("#confirmation-dialog").close();
  void cancelPendingAppConfirmation();
});

$("#confirm-app-button").addEventListener("click", async () => {
  const pending = pendingConfirmation;
  pendingConfirmation = null;
  $("#confirmation-dialog").close();
  if (!pending) return;
  setBusy(true, "Abrindo o aplicativo confirmado…");
  try {
    const result = await rpc("app.confirm", { confirmation_id: pending.confirmation_id, confirmed: true });
    showToast(result.message || "A Nova iniciou a abertura solicitada.");
    await refreshState();
  } catch (error) { showError(error.message); }
  finally { setBusy(false); }
});

(async function initialize() {
  try {
    await establishSession();
    await refreshState();
    setInterval(refreshState, 5000);
  } catch (error) {
    $("#connection-dot").classList.add("disconnected");
    $("#connection-label").textContent = "Falha na conexão";
    showError(error.message);
  }
})();
