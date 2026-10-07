"use strict";
const $ = (sel) => document.querySelector(sel);
const FIELDS = [
  ["full_name", "Full name"], ["home_address", "Home address"],
  ["covers_worldwide_assets", "Covers worldwide assets"], ["has_children", "Has children"],
  ["children_names", "Children's names"], ["executor.name", "Executor"],
  ["executor.relationship", "Executor's relationship"], ["specific_gifts", "Specific gifts"],
  ["additional_wishes", "Additional wishes"],
];
let sessionId = null;
let busy = false;

async function api(path, options = {}) {
  const res = await fetch(`/api${path}`, { headers: { "Content-Type": "application/json" }, ...options });
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(body?.error?.message || `Request failed (${res.status}).`);
  return body;
}

function showBanner(text, info = false) {
  const el = $("#banner");
  el.textContent = text || "";
  el.hidden = !text;
  el.classList.toggle("info", info);
}

function showNotice(lines) {
  const el = $("#notice");
  el.textContent = lines.join(" ");
  el.hidden = lines.length === 0;
}

const getPath = (obj, path) => path.split(".").reduce((o, k) => (o == null ? o : o[k]), obj);

function display(value) {
  if (value === null || value === undefined) return "-";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.length ? value.join("; ") : "None";
  return String(value);
}

function renderMessages(messages, pending = null) {
  const list = $("#messages");
  list.replaceChildren();
  const all = pending ? [...messages, { role: "user", content: pending }, { role: "assistant", content: "Thinking...", pending: true }] : messages;
  for (const m of all) {
    const li = document.createElement("li");
    li.className = `msg ${m.role}${m.pending ? " pending" : ""}`;
    li.textContent = m.content;
    list.append(li);
  }
  list.scrollTop = list.scrollHeight;
}

function renderPreview(snap) {
  $("#document").textContent = snap.document_markdown || snap.document || "";
  $("#bar").style.width = `${snap.fields_total ? (100 * snap.fields_done) / snap.fields_total : 0}%`;
  $("#progress-text").textContent = snap.complete ? "Complete" : `${snap.fields_done} of ${snap.fields_total} confirmed`;
  $("#raw").textContent = JSON.stringify(snap.state.structured, null, 2);
  const fields = $("#fields"); fields.replaceChildren();
  for (const [path, label] of FIELDS) {
    if (path === "children_names" && snap.state.structured.has_children !== true) continue;
    const value = getPath(snap.state.structured, path);
    const status = (snap.state.fields[path] || snap.state.fields[path === "executor.name" ? "executor_name" : path === "executor.relationship" ? "executor_relationship" : path])?.status || "unknown";
    const li = document.createElement("li"); li.className = "editable-field";
    const labelEl=document.createElement("span"); labelEl.className="label"; labelEl.textContent=label;
    const input=document.createElement("input"); input.className="value-input";
    input.value=Array.isArray(value)?value.join(", "): (value ?? ""); input.disabled = false;
    const save=document.createElement("button"); save.type="button"; save.textContent="Save"; save.className="ghost small";
    save.onclick=async()=>{
      let v=input.value.trim();
      if (["covers_worldwide_assets","has_children"].includes(path)) v = v.toLowerCase()==="yes" || v.toLowerCase()==="true";
      else if (["children_names","specific_gifts","additional_wishes"].includes(path)) v=v? v.split(",").map(x=>x.trim()).filter(Boolean):[];
      try { const out=await api(`/v1/sessions/${sessionId}/fields/${encodeURIComponent(path)}`,{method:"PATCH",body:JSON.stringify({value:v,confirmed:true})}); lastSnap=out; render(out); showNotice(["Field updated."]); }
      catch(e){showBanner(e.message,true);}
    };
    const pill=document.createElement("span"); pill.className=`pill ${status}`; pill.textContent=status;
    li.append(labelEl,input,save,pill); fields.append(li);
  }
}

function render(snap, pending = null) {
  renderMessages(snap.messages, pending);
  renderPreview(snap);
}

let lastSnap = null;
async function send(text) {
  busy = true;
  $("#send").disabled = true;
  showBanner("");
  showNotice([]);
  renderMessages(lastSnap.messages, text);
  try {
    const out = await api(`/sessions/${sessionId}/messages`, { method: "POST", body: JSON.stringify({ message: text }) });
    lastSnap = out;
    render(out);
    showNotice(out.warnings);
    $("#input").value = "";
  } catch (err) {
    showBanner(`${err.message} Your message was not sent; you can try again.`);
    render(lastSnap);
    $("#input").value = text;
  } finally {
    busy = false;
    $("#send").disabled = false;
    $("#input").focus();
  }
}

async function init() {
  try {
    const health = await api("/health");
    $("#provider").textContent = `Model: ${health.llm_provider}`;
    if (!health.llm_ready) showBanner(`Model not configured: ${health.detail}`, true);
  } catch {
    showBanner("Cannot reach the server.");
  }
  const snap = await api("/sessions", { method: "POST" });
  sessionId = snap.session_id;
  lastSnap = snap;
  render(snap);
}

$("#composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = $("#input").value.trim();
  if (text && !busy) send(text);
});
$("#input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#composer").requestSubmit(); }
});
$("#new-session").addEventListener("click", async () => {
  if (!confirm("Start over? Your current draft will remain saved, but a new session will be created.")) return;
  const snap = await api("/sessions", { method: "POST" });
  sessionId = snap.session_id; lastSnap = snap; showBanner(""); showNotice([]); render(snap);
});
$("#undo").addEventListener("click", async()=>{ try { const snap=await api(`/v1/sessions/${sessionId}/undo`,{method:"POST"}); lastSnap={...snap,assistant_message:"",reply:"",warnings:[]}; render(lastSnap); } catch(e){showBanner(e.message,true);} });
$("#pdf").addEventListener("click",()=>window.open(`/api/v1/sessions/${sessionId}/export.pdf`,`_blank`));
$("#docx").addEventListener("click",()=>window.open(`/api/v1/sessions/${sessionId}/export.docx`,`_blank`));
document.querySelectorAll(".tabs button").forEach((btn) => btn.addEventListener("click", () => {
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b === btn)));
  $("#tab-doc").hidden = btn.dataset.tab !== "doc";
  $("#tab-state").hidden = btn.dataset.tab !== "state";
}));
document.querySelectorAll(".switch button").forEach((btn) => btn.addEventListener("click", () => {
  document.querySelectorAll(".switch button").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
  $("main").dataset.view = btn.dataset.view;
}));
init().catch((e) => showBanner(e.message));
