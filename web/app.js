const form = document.getElementById("job-form");
const urlInput = document.getElementById("url");
const outputInput = document.getElementById("output");
const startBtn = document.getElementById("start");
const cancelBtn = document.getElementById("cancel");
const statusEl = document.getElementById("status");
const errorEl = document.getElementById("error");
const resultsEl = document.getElementById("results");
const titleEl = document.getElementById("playlist-title");
const countsEl = document.getElementById("counts");
const tracksEl = document.getElementById("tracks");
const ffmpegWarning = document.getElementById("ffmpeg-warning");

const LABELS = {
  queued: "queued",
  downloading: "downloading",
  converting: "converting",
  done: "done",
  failed: "failed",
  cancelled: "cancelled",
};

let stream = null;
let jobId = null;
let rows = new Map();

fetch("/api/config")
  .then((r) => r.json())
  .then((cfg) => {
    if (!outputInput.value) outputInput.value = cfg.default_output;
    if (!cfg.ffmpeg) ffmpegWarning.classList.remove("hidden");
  })
  .catch(() => {});

function showError(message) {
  errorEl.textContent = message;
  errorEl.classList.remove("hidden");
}

function clearError() {
  errorEl.textContent = "";
  errorEl.classList.add("hidden");
}

function buildRow(track) {
  const li = document.createElement("li");
  li.className = "track";

  const num = document.createElement("span");
  num.className = "num";
  num.textContent = String(track.index).padStart(2, "0");

  const title = document.createElement("div");
  title.className = "title";
  const name = document.createElement("span");
  name.className = "name";
  name.textContent = track.title;
  name.title = track.title;
  const err = document.createElement("span");
  err.className = "err hidden";
  title.append(name, err);

  const bar = document.createElement("div");
  bar.className = "bar";
  const fill = document.createElement("i");
  bar.append(fill);

  const chip = document.createElement("span");
  chip.className = "chip queued";
  chip.textContent = LABELS.queued;

  li.append(num, title, bar, chip);
  rows.set(track.index, { li, fill, chip, err, name });
  return li;
}

function applyEvent(ev) {
  const row = rows.get(ev.index);
  if (!row) return;

  row.chip.className = "chip " + ev.status;
  row.fill.style.width = (ev.percent || 0) + "%";

  if (ev.status === "downloading" && ev.speed) {
    row.chip.textContent = ev.speed;
  } else if (ev.status === "downloading") {
    row.chip.textContent = Math.round(ev.percent || 0) + "%";
  } else {
    row.chip.textContent = LABELS[ev.status] || ev.status;
  }

  if (ev.status === "done") {
    row.fill.style.width = "100%";
    row.fill.style.background = "var(--ok)";
    if (ev.filename) row.name.title = ev.filename;
  } else if (ev.status === "failed") {
    row.fill.style.background = "var(--bad)";
    row.err.textContent = ev.error || "Download failed.";
    row.err.title = ev.error || "";
    row.err.classList.remove("hidden");
  }
}

function updateCounts() {
  let done = 0;
  let failed = 0;
  for (const [, row] of rows) {
    if (row.chip.classList.contains("done")) done++;
    if (row.chip.classList.contains("failed")) failed++;
  }
  const total = rows.size;
  countsEl.textContent =
    done + " of " + total + " done" + (failed ? " \u00b7 " + failed + " failed" : "");
}

function finish(ev) {
  if (stream) {
    stream.close();
    stream = null;
  }
  startBtn.disabled = false;
  cancelBtn.classList.add("hidden");
  updateCounts();

  if (ev.status === "cancelled") {
    statusEl.textContent = "Cancelled after " + ev.done + " of " + ev.total + ".";
  } else if (ev.failed) {
    statusEl.textContent = "Finished: " + ev.done + " downloaded, " + ev.failed + " failed.";
  } else {
    statusEl.textContent = "Finished: " + ev.done + " of " + ev.total + " downloaded.";
  }
}

function listen(id) {
  stream = new EventSource("/api/jobs/" + id + "/events");
  stream.onmessage = (msg) => {
    const ev = JSON.parse(msg.data);
    if (ev.event === "job_complete") {
      finish(ev);
      return;
    }
    applyEvent(ev);
    updateCounts();
  };
  stream.onerror = () => {
    if (stream && stream.readyState === EventSource.CLOSED) {
      statusEl.textContent = "Connection to the downloader was lost.";
      startBtn.disabled = false;
      cancelBtn.classList.add("hidden");
    }
  };
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearError();

  startBtn.disabled = true;
  statusEl.textContent = "Reading playlist\u2026";
  if (stream) {
    stream.close();
    stream = null;
  }

  let data;
  try {
    const response = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: urlInput.value,
        output_dir: outputInput.value.trim() || null,
      }),
    });
    data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Could not start the download.");
  } catch (err) {
    startBtn.disabled = false;
    statusEl.textContent = "";
    showError(err.message);
    return;
  }

  jobId = data.job_id;
  rows = new Map();
  tracksEl.replaceChildren();
  titleEl.textContent = data.playlist_title;
  for (const track of data.tracks) tracksEl.append(buildRow(track));

  resultsEl.classList.remove("hidden");
  cancelBtn.classList.remove("hidden");
  statusEl.textContent = "Saving to " + data.output_dir;
  updateCounts();
  listen(jobId);
});

cancelBtn.addEventListener("click", async () => {
  if (!jobId) return;
  cancelBtn.disabled = true;
  statusEl.textContent = "Cancelling\u2026";
  try {
    await fetch("/api/jobs/" + jobId + "/cancel", { method: "POST" });
  } finally {
    cancelBtn.disabled = false;
  }
});
