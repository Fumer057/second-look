const $ = (id) => document.getElementById(id);

const VERDICT_LABEL = {
  scam: "🚨 SCAM — Do not reply",
  suspicious: "⚠️ BE CAREFUL",
  safe: "✅ Looks OK",
};

// BCP-47 codes for the browser's built-in (free, offline-capable) speech engine.
const SPEECH_LANG = {
  English: "en-IN", Hindi: "hi-IN", Bengali: "bn-IN", Marathi: "mr-IN", Tamil: "ta-IN",
  Telugu: "te-IN", Kannada: "kn-IN", Malayalam: "ml-IN", Gujarati: "gu-IN",
  Punjabi: "pa-IN", Urdu: "ur-IN", Spanish: "es-ES",
};

let lastResult = null;

// Remember the language so Mom doesn't have to pick it every time.
const savedLang = localStorage.getItem("sl-language");
if (savedLang) $("language").value = savedLang;
$("language").addEventListener("change", (e) => localStorage.setItem("sl-language", e.target.value));

$("image").addEventListener("change", () => {
  const file = $("image").files[0];
  if (!file) return;
  $("upload-text").textContent = "📷 " + file.name;
  $("preview").src = URL.createObjectURL(file);
  $("preview").hidden = false;
});

// Pasting a screenshot directly (Ctrl+V / long-press paste) also works.
document.addEventListener("paste", (e) => {
  const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"));
  if (!item) return;
  const dt = new DataTransfer();
  dt.items.add(item.getAsFile());
  $("image").files = dt.files;
  $("image").dispatchEvent(new Event("change"));
});

function show(id, visible) { $(id).hidden = !visible; }

function fillList(el, items) {
  el.innerHTML = "";
  items.forEach((t) => {
    const li = document.createElement("li");
    li.textContent = t;
    el.appendChild(li);
  });
}

async function check() {
  const text = $("text").value.trim();
  const file = $("image").files[0];
  if (!text && !file) {
    showError("Please paste the message or add a screenshot first.");
    return;
  }

  const form = new FormData();
  form.append("text", text);
  form.append("language", $("language").value);
  if (file) form.append("image", file);

  show("error", false);
  show("result", false);
  show("loading", true);
  $("check").disabled = true;

  try {
    const res = await fetch("/api/check", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Something went wrong.");
    render(data);
    loadHistory();
  } catch (err) {
    showError("😟 " + err.message + " Please try again in a minute.");
  } finally {
    show("loading", false);
    $("check").disabled = false;
  }
}

function render(r) {
  lastResult = r;
  const card = $("result");
  card.className = "card result " + r.verdict;
  $("verdict").textContent = VERDICT_LABEL[r.verdict];
  $("headline").textContent = r.headline;
  fillList($("flags"), r.red_flags);
  fillList($("todo"), r.what_to_do);
  $("model").textContent = "Checked by " + r.model + " (open model)";
  show("result", true);
  card.scrollIntoView({ behavior: "smooth", block: "start" });
}

function showError(msg) {
  $("error").textContent = msg;
  show("error", true);
}

function speak() {
  if (!lastResult || !("speechSynthesis" in window)) return;
  speechSynthesis.cancel();
  const r = lastResult;
  const text = [r.headline, ...r.red_flags, ...r.what_to_do].join(". ");
  const u = new SpeechSynthesisUtterance(text);
  u.lang = SPEECH_LANG[$("language").value] || "en-IN";
  u.rate = 0.9;
  speechSynthesis.speak(u);
}

function share() {
  if (!lastResult) return;
  const r = lastResult;
  const msg =
    `${VERDICT_LABEL[r.verdict]}\n\n${r.note_for_family || r.headline}\n\n` +
    `Original message: "${$("text").value.trim().slice(0, 300) || "(screenshot)"}"\n\n— sent from Second Look`;
  if (navigator.share) {
    navigator.share({ text: msg }).catch(() => {});
  } else {
    window.open("https://wa.me/?text=" + encodeURIComponent(msg), "_blank");
  }
}

function reset() {
  $("text").value = "";
  $("image").value = "";
  $("preview").hidden = true;
  $("upload-text").textContent = "📷 Choose screenshot";
  show("result", false);
  speechSynthesis?.cancel();
  window.scrollTo({ top: 0, behavior: "smooth" });
  $("text").focus();
}

async function loadHistory() {
  try {
    const res = await fetch("/api/history");
    const data = await res.json();
    if (!data.enabled || !data.items.length) return;
    const list = $("history-list");
    list.innerHTML = "";
    data.items.slice(0, 8).forEach((it) => {
      const li = document.createElement("li");
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = { scam: "🚨", suspicious: "⚠️", safe: "✅" }[it.verdict] || "•";
      li.append(tag, `${new Date(it.at).toLocaleString()} — ${it.headline}`);
      list.appendChild(li);
    });
    show("history", true);
  } catch { /* history is optional */ }
}

async function loadConfig() {
  try {
    const res = await fetch("/api/config");
    const data = await res.json();
    if (data.whatsapp_link) {
      $("wa-link").href = data.whatsapp_link;
      show("wa-link-container", true);
    }
  } catch {}
}

$("check").addEventListener("click", check);
$("speak").addEventListener("click", speak);
$("share").addEventListener("click", share);
$("again").addEventListener("click", reset);
loadHistory();
loadConfig();
