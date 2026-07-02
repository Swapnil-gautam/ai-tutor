/* ===== State ===== */
const state = {
  courses: [],
  currentCourseId: null,
  currentSessionId: null,
  mode: "rag", // "rag" | "raw"
  role: localStorage.getItem("scholera_role") || "student", // "student" | "professor"
  materials: [],
  sessions: [],
  quizzes: [],
  currentQuiz: null,
  sending: false,
};

/* ===== DOM refs ===== */
const $courseSelect   = document.getElementById("course-select");
const $chatMessages   = document.getElementById("chat-messages");
const $welcomeScreen  = document.getElementById("welcome-screen");
const $chatForm       = document.getElementById("chat-form");
const $chatInput      = document.getElementById("chat-input");
const $btnSend        = document.getElementById("btn-send");
const $btnNewChat     = document.getElementById("btn-new-chat");
const $btnUpload      = document.getElementById("btn-upload");
const $btnCreateCourse = document.getElementById("btn-create-course");
const $materialsList  = document.getElementById("materials-list");
const $chatHistory    = document.getElementById("chat-history");
const $courseStats     = document.getElementById("course-stats");
const $typingIndicator = document.getElementById("typing-indicator");
const $modeButtons    = document.querySelectorAll(".mode-btn");
const $roleButtons    = document.querySelectorAll(".role-btn");
const $quizzesList    = document.getElementById("quizzes-list");

/* ===== Init ===== */
document.addEventListener("DOMContentLoaded", async () => {
  await loadCourses();
  setupEventListeners();
  applyRole(state.role);
});

function setupEventListeners() {
  $courseSelect.addEventListener("change", onCourseChange);
  $chatForm.addEventListener("submit", onSendMessage);
  $chatInput.addEventListener("input", onInputChange);
  $chatInput.addEventListener("keydown", onInputKeydown);
  $btnNewChat.addEventListener("click", onNewChat);
  $btnUpload.addEventListener("click", () => openModal("upload-modal"));
  $btnCreateCourse.addEventListener("click", () => openModal("course-modal"));

  $modeButtons.forEach(btn => btn.addEventListener("click", () => setMode(btn.dataset.mode)));
  $roleButtons.forEach(btn => btn.addEventListener("click", () => {
    applyRole(btn.dataset.role);
  }));

  document.getElementById("course-form").addEventListener("submit", onCreateCourse);
  document.getElementById("upload-form").addEventListener("submit", onUploadMaterial);
  document.getElementById("btn-study-guide").addEventListener("click", () => {
    if (!state.currentCourseId) { alert("Please select a course first."); return; }
    openModal("study-modal");
  });
  document.getElementById("study-form").addEventListener("submit", onGenerateStudyGuide);

  document.getElementById("btn-audio-overview").addEventListener("click", () => {
    if (!state.currentCourseId) { alert("Please select a course first."); return; }
    openModal("audio-modal");
  });
  document.getElementById("audio-form").addEventListener("submit", onGenerateAudioOverview);

  document.getElementById("btn-create-quiz").addEventListener("click", () => {
    if (!state.currentCourseId) { alert("Please select a course first."); return; }
    openModal("quiz-modal");
  });
  document.getElementById("quiz-form").addEventListener("submit", onGenerateQuiz);

  setupModalDropPanels();

  // File drop zone
  const $fileDrop = document.getElementById("file-drop");
  const $fileInput = document.getElementById("file-input");
  $fileDrop.addEventListener("click", () => $fileInput.click());
  $fileDrop.addEventListener("dragover", e => { e.preventDefault(); $fileDrop.classList.add("dragover"); });
  $fileDrop.addEventListener("dragleave", () => $fileDrop.classList.remove("dragover"));
  $fileDrop.addEventListener("drop", e => {
    e.preventDefault();
    $fileDrop.classList.remove("dragover");
    if (e.dataTransfer.files.length) {
      $fileInput.files = e.dataTransfer.files;
      showFileName();
    }
  });
  $fileInput.addEventListener("change", showFileName);

  // Close modals on backdrop click
  document.querySelectorAll(".modal-backdrop").forEach(b =>
    b.addEventListener("click", () => b.parentElement.classList.add("hidden"))
  );
}

/* ===== Role Management ===== */
function applyRole(role) {
  state.role = role;
  localStorage.setItem("scholera_role", role);

  $roleButtons.forEach(b => b.classList.toggle("active", b.dataset.role === role));

  const professorEls = document.querySelectorAll(".professor-only");
  professorEls.forEach(el => {
    el.style.display = role === "professor" ? "" : "none";
  });

  // Re-render materials to show/hide delete buttons
  renderMaterials();
  renderQuizzes();
}

/* ===== API helpers ===== */
async function api(method, url, body = null) {
  const opts = { method, headers: {} };
  if (body && !(body instanceof FormData)) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  } else if (body instanceof FormData) {
    opts.body = body;
  }
  const res = await fetch(url, opts);
  if (res.status === 204) return null;
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
  return data;
}

/* ===== Courses ===== */
async function loadCourses() {
  state.courses = await api("GET", "/courses/");
  renderCourseSelect();
}

function renderCourseSelect() {
  const opts = state.courses.map(c =>
    `<option value="${c.id}">${c.title}</option>`
  ).join("");
  $courseSelect.innerHTML = `<option value="">-- Select a course --</option>${opts}`;
  if (state.currentCourseId) $courseSelect.value = state.currentCourseId;
}

async function onCourseChange() {
  state.currentCourseId = $courseSelect.value || null;
  state.currentSessionId = null;
  await Promise.all([loadMaterials(), loadChatHistory(), loadStats(), loadQuizzes()]);
  clearChatDisplay();
}

async function onCreateCourse(e) {
  e.preventDefault();
  const title = document.getElementById("course-title").value.trim();
  const desc = document.getElementById("course-desc").value.trim();
  if (!title) return;
  const course = await api("POST", "/courses/", { title, description: desc });
  closeModal("course-modal");
  document.getElementById("course-title").value = "";
  document.getElementById("course-desc").value = "";
  await loadCourses();
  $courseSelect.value = course.id;
  await onCourseChange();
}

/* ===== Materials ===== */
async function loadMaterials() {
  if (!state.currentCourseId) { $materialsList.innerHTML = ""; return; }
  state.materials = await api("GET", `/courses/${state.currentCourseId}/materials/`);
  renderMaterials();
}

function renderMaterials() {
  if (!state.materials.length) {
    $materialsList.innerHTML = `<p style="font-size:12px;color:var(--text-muted);padding:4px;">No materials uploaded yet.</p>`;
    return;
  }
  const isProfessor = state.role === "professor";
  $materialsList.innerHTML = state.materials.map(m => {
    const rawStatus = m.status || "pending";
    const parts = rawStatus.split("|");
    const mainStatus = parts[0];
    const step = parts[1] || "";
    const pct = parts[2] || "";
    const isProcessing = mainStatus === "processing";

    let statusHtml;
    if (isProcessing && step) {
      statusHtml = `<div class="material-progress">
        <div class="progress-text">${step}</div>
        ${pct ? `<div class="progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>` : ""}
      </div>`;
    } else {
      statusHtml = `<span class="status status-${mainStatus}">${mainStatus}</span>`;
    }

    const deleteBtn = isProfessor
      ? `<button class="btn-delete-material" onclick="deleteMaterial('${m.id}')" title="Delete material">&times;</button>`
      : "";

    return `<div class="material-item">
      <span class="material-name">${m.lecture_number ? `L${m.lecture_number}: ` : ""}${m.lecture_title || m.filename}</span>
      <div class="material-actions">
        ${statusHtml}
        ${deleteBtn}
      </div>
    </div>`;
  }).join("");
}

async function onUploadMaterial(e) {
  e.preventDefault();
  if (!state.currentCourseId) { alert("Please select a course first."); return; }
  const fileInput = document.getElementById("file-input");
  if (!fileInput.files.length) { alert("Please select a file."); return; }

  const num = document.getElementById("upload-lecture-num").value;
  if (!num || parseInt(num) < 1) {
    alert("Please enter a valid lecture number (must be a positive number).");
    return;
  }

  const form = new FormData();
  form.append("file", fileInput.files[0]);
  form.append("lecture_number", num);
  const title = document.getElementById("upload-lecture-title").value;
  if (title) form.append("lecture_title", title);

  const btn = document.getElementById("btn-upload-submit");
  btn.textContent = "Uploading...";
  btn.disabled = true;

  try {
    await api("POST", `/courses/${state.currentCourseId}/materials/`, form);
    closeModal("upload-modal");
    fileInput.value = "";
    document.getElementById("file-name").textContent = "";
    document.getElementById("upload-lecture-num").value = "";
    document.getElementById("upload-lecture-title").value = "";
    await loadMaterials();
    pollMaterials();
  } catch (err) {
    alert("Upload failed: " + err.message);
  } finally {
    btn.textContent = "Upload & Ingest";
    btn.disabled = false;
  }
}

function pollMaterials() {
  const interval = setInterval(async () => {
    await loadMaterials();
    await loadStats();
    const hasActive = state.materials.some(m => {
      const s = (m.status || "").split("|")[0];
      return s === "processing" || s === "pending";
    });
    if (!hasActive) clearInterval(interval);
  }, 10000);
}

async function deleteMaterial(materialId) {
  if (!confirm("Delete this material and all its chunks?")) return;
  try {
    await api("DELETE", `/courses/${state.currentCourseId}/materials/${materialId}`);
    await loadMaterials();
    await loadStats();
  } catch (err) {
    alert("Failed to delete: " + err.message);
  }
}

function showFileName() {
  const f = document.getElementById("file-input").files[0];
  document.getElementById("file-name").textContent = f ? f.name : "";
}

/* ===== Stats ===== */
async function loadStats() {
  if (!state.currentCourseId) { $courseStats.innerHTML = ""; return; }
  try {
    const s = await api("GET", `/courses/${state.currentCourseId}/stats`);
    $courseStats.innerHTML =
      `${s.materials} lectures &middot; ${s.total_pages} pages &middot; ${s.chunks} chunks`;
  } catch { $courseStats.innerHTML = ""; }
}

/* ===== Mode ===== */
function setMode(mode) {
  state.mode = mode;
  $modeButtons.forEach(b => b.classList.toggle("active", b.dataset.mode === mode));
  if (state.currentSessionId) {
    api("PATCH", `/chat/sessions/${state.currentSessionId}`, { mode }).catch(() => {});
  }
}

/* ===== Chat History ===== */
async function loadChatHistory() {
  const url = state.currentCourseId
    ? `/chat/sessions?course_id=${state.currentCourseId}`
    : "/chat/sessions";
  state.sessions = await api("GET", url);
  renderChatHistory();
}

function renderChatHistory() {
  if (!state.sessions.length) {
    $chatHistory.innerHTML = `<p style="font-size:12px;color:var(--text-muted);padding:4px;">No chats yet.</p>`;
    return;
  }
  $chatHistory.innerHTML = state.sessions.map(s => `
    <div class="chat-history-item ${s.id === state.currentSessionId ? 'active' : ''}"
         data-id="${s.id}" onclick="loadSession('${s.id}')">
      ${escapeHtml(s.title)}
    </div>
  `).join("");
}

async function loadSession(sessionId) {
  state.currentSessionId = sessionId;
  const session = await api("GET", `/chat/sessions/${sessionId}`);
  if (session.course_id && session.course_id !== state.currentCourseId) {
    state.currentCourseId = session.course_id;
    $courseSelect.value = session.course_id;
    await loadMaterials();
    await loadStats();
  }
  setMode(session.mode || "rag");

  const messages = await api("GET", `/chat/sessions/${sessionId}/messages`);
  renderMessages(messages);
  renderChatHistory();
}

/* ===== Chat ===== */
async function onNewChat() {
  state.currentSessionId = null;
  clearChatDisplay();
  $chatInput.focus();
}

function clearChatDisplay() {
  $chatMessages.innerHTML = "";
  $chatMessages.appendChild($welcomeScreen.cloneNode(true) || createWelcome());
  const ws = $chatMessages.querySelector(".welcome-screen");
  if (ws) ws.classList.remove("hidden");
  renderChatHistory();
}

async function onSendMessage(e) {
  e.preventDefault();
  const text = $chatInput.value.trim();
  if (!text || state.sending) return;

  const ws = $chatMessages.querySelector(".welcome-screen");
  if (ws) ws.remove();

  if (!state.currentSessionId) {
    const session = await api("POST", "/chat/sessions", {
      course_id: state.currentCourseId,
      mode: state.mode,
      title: "New Chat",
    });
    state.currentSessionId = session.id;
    state.sessions.unshift(session);
    renderChatHistory();
  }

  appendMessage("user", text);
  $chatInput.value = "";
  $chatInput.style.height = "auto";
  $btnSend.disabled = true;
  state.sending = true;
  $typingIndicator.classList.remove("hidden");
  scrollToBottom();

  try {
    const res = await api("POST", `/chat/sessions/${state.currentSessionId}/messages`, { content: text });
    $typingIndicator.classList.add("hidden");
    appendMessage("assistant", res.content, res.sources);
    await loadChatHistory();
  } catch (err) {
    $typingIndicator.classList.add("hidden");
    appendMessage("error", err.message);
  } finally {
    state.sending = false;
    scrollToBottom();
  }
}

function renderMessages(messages) {
  $chatMessages.innerHTML = "";
  if (!messages.length) {
    clearChatDisplay();
    return;
  }
  const ws = $chatMessages.querySelector(".welcome-screen");
  if (ws) ws.remove();

  messages.forEach(m => appendMessage(m.role, m.content, m.sources));
  scrollToBottom();
}

function appendMessage(role, content, sources = []) {
  const div = document.createElement("div");

  if (role === "user") {
    div.className = "message message-user";
    div.textContent = content;
  } else if (role === "error") {
    div.className = "message message-error";
    div.textContent = content;
  } else {
    div.className = "message message-assistant";
    div.innerHTML = renderMarkdown(content);

    if (sources && sources.length) {
      const srcDiv = document.createElement("div");
      srcDiv.className = "message-sources";
      srcDiv.innerHTML = "Sources: " + sources
        .filter(s => s.chunk_type === "slide")
        .map(s => `<span>L${s.lecture_number || "?"} Slide ${s.page_number || "?"}</span>`)
        .join("");
      div.appendChild(srcDiv);
    }
  }

  $chatMessages.appendChild(div);
  scrollToBottom();
}

/* ===== Input handling ===== */
function onInputChange() {
  $btnSend.disabled = !$chatInput.value.trim();
  $chatInput.style.height = "auto";
  $chatInput.style.height = Math.min($chatInput.scrollHeight, 150) + "px";
}

function onInputKeydown(e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    $chatForm.dispatchEvent(new Event("submit"));
  }
}

function setInput(text) {
  $chatInput.value = text;
  $chatInput.focus();
  onInputChange();
}

/* ===== Modals ===== */
function openModal(id) {
  document.getElementById(id).classList.remove("hidden");
}
function closeModal(id) {
  document.getElementById(id).classList.add("hidden");
}

/* ===== Utilities ===== */
function scrollToBottom() {
  requestAnimationFrame(() => {
    $chatMessages.scrollTop = $chatMessages.scrollHeight;
  });
}

function escapeHtml(text) {
  const d = document.createElement("div");
  d.textContent = text;
  return d.innerHTML;
}

/* ===== Study Guide ===== */
async function onGenerateStudyGuide(e) {
  e.preventDefault();
  const topic = document.getElementById("study-topic").value.trim();
  if (!topic || !state.currentCourseId) return;

  const btn = document.getElementById("btn-study-submit");
  btn.textContent = "Generating...";
  btn.disabled = true;

  try {
    const res = await api("POST", `/chat/study-guide?course_id=${state.currentCourseId}`, { topic });
    closeModal("study-modal");
    document.getElementById("study-topic").value = "";

    await onNewChat();
    const ws = $chatMessages.querySelector(".welcome-screen");
    if (ws) ws.remove();

    appendMessage("user", `Generate a study guide on: ${topic}`);
    appendMessage("assistant", res.guide, res.sources);
  } catch (err) {
    alert("Study guide failed: " + err.message);
  } finally {
    btn.textContent = "Generate";
    btn.disabled = false;
  }
}

/* ===== Audio Overview ===== */
async function onGenerateAudioOverview(e) {
  e.preventDefault();
  const topic = document.getElementById("audio-topic").value.trim();
  if (!topic || !state.currentCourseId) return;

  const btn = document.getElementById("btn-audio-submit");
  btn.textContent = "Generating...";
  btn.disabled = true;

  try {
    const res = await api("POST", `/courses/${state.currentCourseId}/audio/overview`, { topic });
    closeModal("audio-modal");
    document.getElementById("audio-topic").value = "";

    await onNewChat();
    const ws = $chatMessages.querySelector(".welcome-screen");
    if (ws) ws.remove();

    appendMessage("user", `Generate an audio explanation on: ${topic}`);
    appendAudioAssistant(res.script || "(No script returned.)", res.sources || [], res.audio_url);
  } catch (err) {
    alert("Audio generation failed: " + err.message);
  } finally {
    btn.textContent = "Generate audio";
    btn.disabled = false;
  }
}

function appendAudioAssistant(script, sources = [], audioUrl = null) {
  const div = document.createElement("div");
  div.className = "message message-assistant";
  div.innerHTML = renderMarkdown(script);

  if (audioUrl) {
    const block = document.createElement("div");
    block.className = "audio-block";

    const audio = document.createElement("audio");
    audio.controls = true;
    audio.src = audioUrl;

    const dl = document.createElement("a");
    dl.href = audioUrl;
    dl.download = "";
    dl.textContent = "Download audio";

    block.appendChild(audio);
    block.appendChild(dl);
    div.appendChild(block);
  }

  if (sources && sources.length) {
    const srcDiv = document.createElement("div");
    srcDiv.className = "message-sources";
    srcDiv.innerHTML = "Sources: " + sources
      .filter(s => s.chunk_type === "slide")
      .map(s => `<span>L${s.lecture_number || "?"} Slide ${s.page_number || "?"}</span>`)
      .join("");
    div.appendChild(srcDiv);
  }

  $chatMessages.appendChild(div);
  scrollToBottom();
}

/* ===== Quizzes ===== */
async function loadQuizzes() {
  if (!state.currentCourseId) { $quizzesList.innerHTML = ""; return; }
  try {
    state.quizzes = await api("GET", `/courses/${state.currentCourseId}/quizzes/`);
  } catch {
    state.quizzes = [];
  }
  renderQuizzes();
}

function formatQuizLectureMeta(q) {
  if (q.lecture_numbers && q.lecture_numbers.length) {
    return "L" + q.lecture_numbers.join(", L");
  }
  if (q.lecture_number) return `L${q.lecture_number}`;
  return "";
}

/** Parse "1, 3; 5" into sorted unique positive integers. */
function parseCommaSeparatedInts(raw) {
  if (!raw || !String(raw).trim()) return [];
  const parts = String(raw).split(/[,;\s]+/).map(s => s.trim()).filter(Boolean);
  const nums = [...new Set(parts.map(p => parseInt(p, 10)).filter(n => !Number.isNaN(n) && n >= 1))];
  return nums.sort((a, b) => a - b);
}

function renderQuizzes() {
  if (!state.quizzes.length) {
    $quizzesList.innerHTML = `<p style="font-size:12px;color:var(--text-muted);padding:4px;">No quizzes yet.</p>`;
    return;
  }
  const isProfessor = state.role === "professor";
  $quizzesList.innerHTML = state.quizzes.map(q => {
    const meta = formatQuizLectureMeta(q);
    const deleteBtn = isProfessor
      ? `<button class="btn-delete-material" onclick="event.stopPropagation(); deleteQuiz('${q.id}')" title="Delete quiz">&times;</button>`
      : "";
    return `<div class="quiz-item" onclick="openQuiz('${q.id}')">
      <div class="quiz-item-info">
        <span class="quiz-item-title">${escapeHtml(q.title)}</span>
        <span class="quiz-item-meta">${meta} ${q.num_questions} questions</span>
      </div>
      ${deleteBtn}
    </div>`;
  }).join("");
}

async function onGenerateQuiz(e) {
  e.preventDefault();
  if (!state.currentCourseId) return;

  const topic = document.getElementById("quiz-topic").value.trim();
  if (!topic) return;

  const lectureNumsRaw = document.getElementById("quiz-lecture-nums").value;
  const lecture_numbers = parseCommaSeparatedInts(lectureNumsRaw);
  const numQuestions = parseInt(document.getElementById("quiz-num-questions").value) || 5;

  const btn = document.getElementById("btn-quiz-submit");
  btn.textContent = "Generating...";
  btn.disabled = true;

  try {
    const payload = {
      topic,
      num_questions: numQuestions,
    };
    if (lecture_numbers.length) payload.lecture_numbers = lecture_numbers;

    await api("POST", `/courses/${state.currentCourseId}/quizzes/generate`, payload);
    closeModal("quiz-modal");
    document.getElementById("quiz-topic").value = "";
    document.getElementById("quiz-lecture-nums").value = "";
    document.getElementById("quiz-num-questions").value = "5";
    await loadQuizzes();
  } catch (err) {
    alert("Quiz generation failed: " + err.message);
  } finally {
    btn.textContent = "Generate quiz";
    btn.disabled = false;
  }
}

/** Click dashed panel (outside textarea) focuses topic field — same affordance as upload drop zone. */
function setupModalDropPanels() {
  [
    ["audio-topic-panel", "audio-topic"],
    ["quiz-topic-panel", "quiz-topic"],
  ].forEach(([panelId, fieldId]) => {
    const panel = document.getElementById(panelId);
    const field = document.getElementById(fieldId);
    if (!panel || !field) return;
    panel.addEventListener("click", (e) => {
      if (e.target === field) return;
      field.focus();
    });
  });
}

async function openQuiz(quizId) {
  try {
    const quiz = await api("GET", `/courses/${state.currentCourseId}/quizzes/${quizId}`);
    state.currentQuiz = quiz;

    document.getElementById("quiz-take-title").textContent = quiz.title;
    const meta = [];
    const lecMeta = formatQuizLectureMeta(quiz);
    if (lecMeta) meta.push(`Scope: ${lecMeta}`);
    if (quiz.topic) meta.push(quiz.topic);
    meta.push(`${quiz.questions.length} questions`);
    document.getElementById("quiz-take-meta").textContent = meta.join(" \u00B7 ");

    const body = document.getElementById("quiz-take-body");
    body.innerHTML = quiz.questions.map((q, i) => `
      <div class="quiz-question" data-idx="${i}" data-correct="${q.correct_option}">
        <div class="quiz-q-text"><strong>Q${i + 1}.</strong> ${renderMarkdown(q.question_text)}</div>
        <div class="quiz-options">
          ${["A", "B", "C", "D"].map(opt => `
            <label class="quiz-option" data-opt="${opt}">
              <input type="radio" name="quiz-q-${i}" value="${opt}">
              <span class="quiz-option-label">${opt}.</span>
              <span class="quiz-option-body">${renderMarkdown(q["option_" + opt.toLowerCase()])}</span>
            </label>
          `).join("")}
        </div>
        <div class="quiz-explanation hidden" id="quiz-exp-${i}">
          <div class="quiz-explanation-body">${renderMarkdown(q.explanation || "")}</div>
        </div>
      </div>
    `).join("");

    const checkBtn = document.getElementById("btn-quiz-check");
    checkBtn.textContent = "Check Answers";
    checkBtn.disabled = false;
    checkBtn.style.display = "";
    openModal("quiz-take-modal");
  } catch (err) {
    alert("Failed to load quiz: " + err.message);
  }
}

function checkQuizAnswers() {
  if (!state.currentQuiz) return;
  let correct = 0;
  const total = state.currentQuiz.questions.length;

  state.currentQuiz.questions.forEach((q, i) => {
    const questionDiv = document.querySelector(`.quiz-question[data-idx="${i}"]`);
    const selected = questionDiv.querySelector(`input[name="quiz-q-${i}"]:checked`);
    const correctOpt = q.correct_option;

    questionDiv.querySelectorAll(".quiz-option").forEach(opt => {
      opt.classList.remove("quiz-correct", "quiz-wrong");
      if (opt.dataset.opt === correctOpt) {
        opt.classList.add("quiz-correct");
      }
    });

    if (selected) {
      const userOpt = selected.value;
      if (userOpt === correctOpt) {
        correct++;
      } else {
        const wrongLabel = questionDiv.querySelector(`.quiz-option[data-opt="${userOpt}"]`);
        if (wrongLabel) wrongLabel.classList.add("quiz-wrong");
      }
    }

    const expDiv = document.getElementById(`quiz-exp-${i}`);
    if (expDiv) expDiv.classList.remove("hidden");
  });

  const checkBtn = document.getElementById("btn-quiz-check");
  checkBtn.textContent = `Score: ${correct}/${total}`;
  checkBtn.disabled = true;
}

async function deleteQuiz(quizId) {
  if (!confirm("Delete this quiz?")) return;
  try {
    await api("DELETE", `/courses/${state.currentCourseId}/quizzes/${quizId}`);
    await loadQuizzes();
  } catch (err) {
    alert("Failed to delete quiz: " + err.message);
  }
}

/* ===== Markdown renderer ===== */
function renderMarkdown(text) {
  const latexBlocks = [];
  let processed = text;

  processed = processed.replace(/\$\$([\s\S]*?)\$\$/g, (_, tex) => {
    latexBlocks.push({ tex: tex.trim(), display: true });
    return `%%LATEX_${latexBlocks.length - 1}%%`;
  });
  processed = processed.replace(/\\\[([\s\S]*?)\\\]/g, (_, tex) => {
    latexBlocks.push({ tex: tex.trim(), display: true });
    return `%%LATEX_${latexBlocks.length - 1}%%`;
  });

  processed = processed.replace(/\$([^\$\n]+?)\$/g, (_, tex) => {
    latexBlocks.push({ tex: tex.trim(), display: false });
    return `%%LATEX_${latexBlocks.length - 1}%%`;
  });
  processed = processed.replace(/\\\((.*?)\\\)/g, (_, tex) => {
    latexBlocks.push({ tex: tex.trim(), display: false });
    return `%%LATEX_${latexBlocks.length - 1}%%`;
  });

  let html = escapeHtml(processed);

  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) =>
    `<pre><code>${code.trim()}</code></pre>`
  );
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/^### (.+)$/gm, "<h4>$1</h4>");
  html = html.replace(/^## (.+)$/gm, "<h3>$1</h3>");
  html = html.replace(/^# (.+)$/gm, "<h2>$1</h2>");
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");
  html = html.replace(/^[\-\*] (.+)$/gm, "<li>$1</li>");
  html = html.replace(/((?:<li>.*<\/li>\s*)+)/g, m => `<ul>${m}</ul>`);
  html = html.replace(/^\d+\. (.+)$/gm, "<li>$1</li>");
  html = html.split(/\n{2,}/).map(p => {
    p = p.trim();
    if (!p) return "";
    if (/^<(pre|ul|ol|li|h[2-4])/.test(p)) return p;
    return `<p>${p.replace(/\n/g, "<br>")}</p>`;
  }).join("");

  html = html.replace(/%%LATEX_(\d+)%%/g, (_, idx) => {
    const block = latexBlocks[parseInt(idx)];
    if (!block) return "";
    try {
      if (typeof katex !== "undefined") {
        return katex.renderToString(block.tex, { displayMode: block.display, throwOnError: false });
      }
    } catch (e) { /* fall through */ }
    return block.display
      ? `<div class="math-block">${escapeHtml(block.tex)}</div>`
      : `<span class="math-inline">${escapeHtml(block.tex)}</span>`;
  });

  return html;
}
