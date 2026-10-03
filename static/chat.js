const $ = (id) => document.getElementById(id);

let sessionId = localStorage.getItem("sl-session") || Math.random().toString(36).substring(2);
localStorage.setItem("sl-session", sessionId);

const savedLang = localStorage.getItem("sl-language");
if (savedLang && Array.from($("language").options).some(o => o.value === savedLang || o.text === savedLang)) {
    $("language").value = savedLang;
}
$("language").addEventListener("change", (e) => localStorage.setItem("sl-language", e.target.value));

const chat = $("chat");
const input = $("input-text");
const fileInput = $("file-input");
const sendBtn = $("send-btn");

const VERDICT_LABEL = {
  scam: "🚨 SCAM",
  suspicious: "⚠️ BE CAREFUL",
  safe: "✅ Looks OK",
  info: "ℹ️ Info"
};

input.addEventListener("input", function() {
    this.style.height = "auto";
    this.style.height = (this.scrollHeight) + "px";
    if(this.value.trim() === "" && !fileInput.files[0]) {
        this.style.height = "auto";
    }
});

$("upload-btn").addEventListener("click", () => fileInput.click());

fileInput.addEventListener("change", () => {
    if (fileInput.files[0]) {
        $("preview").src = URL.createObjectURL(fileInput.files[0]);
        $("preview-box").style.display = "block";
    }
});

$("clear-img").addEventListener("click", () => {
    fileInput.value = "";
    $("preview-box").style.display = "none";
});

function addMessage(html, type = 'bot', classes = '') {
    const div = document.createElement("div");
    div.className = `msg ${type} ${classes}`;
    div.innerHTML = html;
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
    return div;
}

async function send() {
    const text = input.value.trim();
    const file = fileInput.files[0];
    if (!text && !file) return;

    let userHtml = text.replace(/\n/g, "<br>");
    if (file) {
        userHtml += `<img src="${URL.createObjectURL(file)}">`;
    }
    addMessage(userHtml, "user");

    input.value = "";
    input.style.height = "auto";
    fileInput.value = "";
    $("preview-box").style.display = "none";
    
    sendBtn.disabled = true;
    const typing = addMessage(`<div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>`, "bot", "typing");

    const form = new FormData();
    form.append("text", text);
    form.append("language", $("language").value);
    form.append("session_id", sessionId);
    if (file) form.append("image", file);

    try {
        const res = await fetch("/api/check", { method: "POST", body: form });
        const data = await res.json();
        typing.remove();
        
        if (!res.ok) throw new Error(data.detail || "Error");
        
        let html = `<div class="bot-title">${VERDICT_LABEL[data.verdict] || ""} ${data.headline}</div>`;
        if (data.red_flags && data.red_flags.length > 0) {
            html += `<div class="bot-section"><strong>Why:</strong><ul>${data.red_flags.map(f => `<li>${f}</li>`).join('')}</ul></div>`;
        }
        if (data.what_to_do && data.what_to_do.length > 0) {
            html += `<div class="bot-section"><strong>What to do:</strong><ol>${data.what_to_do.map(f => `<li>${f}</li>`).join('')}</ol></div>`;
        }
        addMessage(html, "bot", data.verdict);

    } catch (err) {
        typing.remove();
        addMessage(`😟 ${err.message}`, "bot");
    } finally {
        sendBtn.disabled = false;
        input.focus();
    }
}

sendBtn.addEventListener("click", send);
input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        send();
    }
});
