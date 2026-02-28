// ---- State ----
let currentMeetingId = null;
let mediaRecorder = null;
let ws = null;

// ---- DOM refs ----
const viewList = document.getElementById("view-list");
const viewLive = document.getElementById("view-live");
const viewDetail = document.getElementById("view-detail");

// ---- Navigation ----
function showView(view) {
  [viewList, viewLive, viewDetail].forEach((v) => v.classList.remove("active"));
  view.classList.add("active");
}

// ---- API helpers ----
async function api(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(`/api${path}`, opts);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

// ---- Meeting list ----
async function loadMeetings() {
  const meetings = await api("GET", "/meetings");
  const list = document.getElementById("meeting-list");
  const empty = document.getElementById("list-empty");

  if (meetings.length === 0) {
    list.innerHTML = "";
    empty.style.display = "block";
    return;
  }
  empty.style.display = "none";

  list.innerHTML = meetings
    .map(
      (m) => `
    <li data-id="${m.id}">
      <div class="meeting-info">
        <h3>${esc(m.title)}</h3>
        <span>${new Date(m.created_at + "Z").toLocaleString()}</span>
      </div>
      <span class="badge badge-${m.status}">${m.status}</span>
    </li>`
    )
    .join("");

  list.querySelectorAll("li").forEach((li) => {
    li.addEventListener("click", () => {
      const id = parseInt(li.dataset.id);
      openMeetingDetail(id);
    });
  });
}

// ---- New meeting ----
document.getElementById("btn-new-meeting").addEventListener("click", async () => {
  const input = document.getElementById("meeting-title");
  const title = input.value.trim();
  if (!title) return;
  input.value = "";

  const meeting = await api("POST", "/meetings", { title });
  currentMeetingId = meeting.id;
  startLiveTranscription(meeting.id, title);
});

// ---- Live transcription ----
function startLiveTranscription(meetingId, title) {
  document.getElementById("live-title").textContent = title;
  document.getElementById("live-segments").innerHTML = "";
  document.getElementById("live-status").textContent = "Starting microphone...";
  document.getElementById("rec-indicator").style.display = "inline-flex";
  showView(viewLive);

  // WebSocket
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${proto}//${location.host}/ws/transcribe/${meetingId}`);

  ws.onopen = () => {
    document.getElementById("live-status").textContent = "Connected. Speak now.";
    startMicCapture();
  };

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.error) {
      appendStatus(msg.error);
      return;
    }
    appendSegment(document.getElementById("live-segments"), msg);
  };

  ws.onclose = () => {
    document.getElementById("live-status").textContent = "Connection closed.";
  };
}

async function startMicCapture() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  mediaRecorder = new MediaRecorder(stream, { mimeType: "audio/webm;codecs=opus" });

  mediaRecorder.ondataavailable = (e) => {
    if (e.data.size > 0 && ws && ws.readyState === WebSocket.OPEN) {
      ws.send(e.data);
    }
  };

  mediaRecorder.start(5000); // chunk every 5 seconds
  document.getElementById("live-status").textContent = "Recording...";
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();
    mediaRecorder.stream.getTracks().forEach((t) => t.stop());
    mediaRecorder = null;
  }
  if (ws) {
    ws.close();
    ws = null;
  }
}

document.getElementById("btn-end-meeting").addEventListener("click", async () => {
  stopRecording();
  document.getElementById("rec-indicator").style.display = "none";
  document.getElementById("live-status").textContent = "Meeting ended.";

  if (currentMeetingId) {
    await api("POST", `/meetings/${currentMeetingId}/end`);
  }
});

document.getElementById("btn-back-live").addEventListener("click", () => {
  stopRecording();
  showView(viewList);
  loadMeetings();
});

// ---- Meeting detail ----
async function openMeetingDetail(id) {
  const meeting = await api("GET", `/meetings/${id}`);
  currentMeetingId = id;

  document.getElementById("detail-title").textContent = meeting.title;
  const badge = document.getElementById("detail-badge");
  badge.textContent = meeting.status;
  badge.className = `badge badge-${meeting.status}`;

  const container = document.getElementById("detail-segments");
  container.innerHTML = "";

  if (meeting.segments.length === 0) {
    container.innerHTML = '<div class="empty-state">No transcript segments.</div>';
  } else {
    meeting.segments.forEach((seg) => appendSegment(container, seg));
  }

  // Actions
  const actions = document.getElementById("detail-actions");
  actions.innerHTML = "";

  if (meeting.status === "completed") {
    const btn = document.createElement("button");
    btn.textContent = "Run Diarization";
    btn.addEventListener("click", () => diarizeMeeting(id));
    actions.appendChild(btn);
  }

  const delBtn = document.createElement("button");
  delBtn.textContent = "Delete";
  delBtn.className = "btn-danger";
  delBtn.addEventListener("click", async () => {
    if (confirm("Delete this meeting?")) {
      await api("DELETE", `/meetings/${id}`);
      showView(viewList);
      loadMeetings();
    }
  });
  actions.appendChild(delBtn);

  showView(viewDetail);
}

async function diarizeMeeting(id) {
  const actions = document.getElementById("detail-actions");
  const btn = actions.querySelector("button");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Diarizing...";
  }

  try {
    await api("POST", `/meetings/${id}/diarize`);
    openMeetingDetail(id); // reload
  } catch (e) {
    alert("Diarization failed: " + e.message);
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Run Diarization";
    }
  }
}

document.getElementById("btn-back-detail").addEventListener("click", () => {
  showView(viewList);
  loadMeetings();
});

// ---- Helpers ----
function appendSegment(container, seg) {
  const div = document.createElement("div");
  div.className = "segment";

  const meta = document.createElement("div");
  meta.className = "segment-meta";

  if (seg.speaker) {
    const spk = document.createElement("span");
    spk.className = "segment-speaker";
    spk.textContent = seg.speaker;
    meta.appendChild(spk);
  }

  if (seg.start_time != null) {
    meta.appendChild(
      document.createTextNode(formatTime(seg.start_time) + " - " + formatTime(seg.end_time))
    );
  }

  const text = document.createElement("div");
  text.className = "segment-text";
  text.textContent = seg.text;

  div.appendChild(meta);
  div.appendChild(text);
  container.appendChild(div);

  // Auto-scroll
  container.scrollTop = container.scrollHeight;
}

function appendStatus(msg) {
  const status = document.getElementById("live-status");
  status.textContent = msg;
}

function formatTime(seconds) {
  if (seconds == null) return "--:--";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function esc(str) {
  const el = document.createElement("span");
  el.textContent = str;
  return el.innerHTML;
}

// ---- Init ----
loadMeetings();
