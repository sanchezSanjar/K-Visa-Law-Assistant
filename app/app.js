const chat = document.getElementById("chat");
const form = document.getElementById("form");
const input = document.getElementById("input");
const send = document.getElementById("send");
const statusBox = document.getElementById("status");
const statusText = document.getElementById("status-text");
let ready = false;
let busy = false;

function escapeHtml(text) {
  return text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function isKorean(text) {
  return (text.match(/[가-힣]/g) || []).length >= (text.match(/[A-Za-z]/g) || []).length;
}

// Answer text -> HTML: paragraphs, **bold**, and [n] citations as buttons.
// Citations of sources that do not exist (the model sometimes writes [8] with 4 sources) are dropped.
function renderAnswer(text, sourceCount) {
  return escapeHtml(text.trim())
    .split(/\n{1,}/)
    .filter((line) => line.trim())
    .map((line) => "<p>" + line
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\s?\[(\d+)\]/g, (match, n) => (Number(n) >= 1 && Number(n) <= sourceCount
        ? ` <button class="cite" data-n="${n}">${n}</button>` : "")) + "</p>")
    .join("");
}

function setReady(isReady, error) {
  ready = isReady;
  statusBox.className = "status " + (error ? "error" : isReady ? "ready" : "loading");
  statusText.textContent = error ? "오류: " + error : isReady ? "준비됨 · GPU" : "모델 불러오는 중…";
  updateControls();
}

function updateControls() {
  const enabled = ready && !busy;
  input.disabled = !enabled;
  send.disabled = !enabled || !input.value.trim();
  document.querySelectorAll(".example").forEach((b) => (b.disabled = !enabled));
}

async function pollHealth() {
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    setReady(data.ready, data.error);
    if (data.ready) { input.focus(); return; }
    if (data.error) return;
  } catch (e) { /* server is starting */ }
  setTimeout(pollHealth, 1500);
}

function addUserMessage(text) {
  const el = document.createElement("div");
  el.className = "msg user";
  el.innerHTML = `<div class="bubble">${escapeHtml(text)}</div>`;
  chat.appendChild(el);
}

function sourceCard(source, n, korean) {
  const el = document.createElement("div");
  el.className = "source";
  el.dataset.n = n;
  const guide = source.kind === "guide";
  const name = guide ? `${korean ? source.law_ko : source.law_en} ${source.label} · ${source.title}`
             : korean ? `${source.law_ko} ${source.label}(${source.title})`
             : `${source.law_en} · ${source.law_ko} ${source.label}(${source.title})`;
  const tag = source.kind === "table" ? '<span class="source-tag">별표</span>'
            : guide ? `<span class="source-tag guide">${korean ? "안내서" : "Guide"}</span>` : "";
  const day = source.effective ? `${source.effective.slice(0, 4)}.${source.effective.slice(4, 6)}.${source.effective.slice(6)}` : "";
  const date = !day ? "" : guide ? (korean ? `${day} 기준 · 최신 지침과 다를 수 있음` : `as of ${day}, may be outdated`) : `${day} 시행`;
  const sourceLink = source.url
    ? `<a href="${encodeURI(source.url)}" target="_blank" rel="noopener">${guide ? (korean ? "출처" : "Source") : "law.go.kr"}</a>` : "";
  const english = source.text_en ? `<span class="en">English (KLRI translation, for reference): ${escapeHtml(source.text_en)}</span>` : "";
  el.innerHTML = `
    <div class="source-head">
      <div class="source-name"><span class="source-num">[${n}]</span>${escapeHtml(name)}${tag}</div>
      <div class="source-links">
        <button type="button" class="toggle">${korean ? "조문 보기" : "Show text"}</button>
        <a href="/pdf/${encodeURIComponent(source.file)}#page=${source.page}" target="_blank" rel="noopener">PDF p.${source.page}</a>
        ${sourceLink}
      </div>
    </div>
    <div class="meta">${date}</div>
    <div class="source-text">${escapeHtml(source.text)}${english}</div>`;
  el.querySelector(".toggle").addEventListener("click", () => el.classList.toggle("open"));
  return el;
}

async function ask(question) {
  if (!ready || busy || !question.trim()) return;
  busy = true;
  updateControls();
  document.getElementById("welcome")?.remove();
  addUserMessage(question);
  const korean = isKorean(question);

  const msg = document.createElement("div");
  msg.className = "msg bot";
  msg.innerHTML = `<div class="bubble">
      <div class="thinking">${korean ? "관련 조문을 찾는 중…" : "Searching the laws…"}</div>
      <div class="answer"></div><div class="meta"></div><div class="sources"></div></div>`;
  chat.appendChild(msg);
  const answerEl = msg.querySelector(".answer");
  const sourcesEl = msg.querySelector(".sources");
  const thinking = msg.querySelector(".thinking");
  chat.scrollTop = chat.scrollHeight;

  let text = "";
  let sources = [];
  try {
    const res = await fetch("/api/ask", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        if (event.type === "sources") {
          sources = event.sources;
          thinking.textContent = korean ? "답변 작성 중…" : "Writing the answer…";
          answerEl.classList.add("typing");
        } else if (event.type === "token") {
          thinking.remove();
          text += event.text;
          answerEl.innerHTML = renderAnswer(text, sources.length);
        } else if (event.type === "done") {
          answerEl.classList.remove("typing");
          answerEl.innerHTML = renderAnswer(text, sources.length);
          showSources(sourcesEl, sources, event.cited, korean);
          msg.querySelector(".meta").textContent = `${event.seconds}s`;
        }
        chat.scrollTop = chat.scrollHeight;
      }
    }
  } catch (error) {
    thinking.remove();
    answerEl.classList.remove("typing");
    answerEl.innerHTML = `<p class="muted">${korean ? "오류가 발생했습니다" : "Something went wrong"}: ${escapeHtml(String(error.message || error))}</p>`;
  }
  busy = false;
  updateControls();
  input.focus();
}

function showSources(container, sources, cited, korean) {
  if (!sources.length) return;
  container.innerHTML = `<div class="sources-title">${korean ? "근거 법령" : "Sources"}</div>`;
  // Cited pieces first, then the other pieces the model read.
  const order = sources.map((s, i) => i + 1).sort((a, b) => cited.includes(b) - cited.includes(a));
  for (const n of order) {
    const card = sourceCard(sources[n - 1], n, korean);
    if (cited.includes(n)) card.classList.add("cited");
    container.appendChild(card);
  }
  container.closest(".bubble").querySelectorAll(".cite").forEach((button) => {
    button.addEventListener("click", () => {
      const card = container.querySelector(`.source[data-n="${button.dataset.n}"]`);
      if (!card) return;
      card.classList.add("open", "flash");
      card.scrollIntoView({ behavior: "smooth", block: "nearest" });
      setTimeout(() => card.classList.remove("flash"), 1200);
    });
  });
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const question = input.value;
  input.value = "";
  input.style.height = "auto";
  ask(question);
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    form.requestSubmit();
  }
});

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 160) + "px";
  updateControls();
});

document.querySelectorAll(".example").forEach((button) =>
  button.addEventListener("click", () => ask(button.textContent)));

document.getElementById("quit").addEventListener("click", async () => {
  if (!confirm("K-Visa Law Assistant를 종료할까요? / Stop the app?")) return;
  try { await fetch("/api/quit", { method: "POST" }); } catch (e) { /* already stopped */ }
  document.body.innerHTML = '<p style="padding:40px;text-align:center">종료되었습니다. 이 탭을 닫아도 됩니다. / The app has stopped.</p>';
});

pollHealth();
