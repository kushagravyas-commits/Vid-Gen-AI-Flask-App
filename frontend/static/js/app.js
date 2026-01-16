(function(){
  const BACKEND = window.__BACKEND_URL__;
  const LANGS = window.__LANGUAGES__ || {};
  const STYLES = window.__STYLES__ || [];

  // Chips input
  const chips = window.createChipsInput({
    rootId: "langChips",
    inputId: "langInput",
    suggestionsId: "langSuggestions",
    optionsMap: LANGS
  });

  // Style dropdown
  const styleSelect = document.getElementById("styleSelect");
  styleSelect.innerHTML = "";

  if (!STYLES.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "No styles loaded (check backend)";
    styleSelect.appendChild(opt);
  } else {
    STYLES.forEach(s => {
      const opt = document.createElement("option");
      opt.value = s;
      opt.textContent = s;
      styleSelect.appendChild(opt);
    });
    styleSelect.value = STYLES[0];
  }

  // UI elements
  const promptEl = document.getElementById("prompt");
  const statusBadge = document.getElementById("statusBadge");
  const statusText = document.getElementById("statusText");
  const downloadBtn = document.getElementById("downloadBtn");
  const downloadHint = document.getElementById("downloadHint");
  const generateBtn = document.getElementById("generateBtn");
  const previewBox = document.getElementById("previewBox");
  const durationEl = document.getElementById("durationGuess");

  let currentJobId = null;
  let pollTimer = null;

  function formatDuration(totalSeconds){
    if (!isFinite(totalSeconds) || totalSeconds <= 0) return "—";
    const s = Math.round(totalSeconds);
    const m = Math.floor(s / 60);
    const r = s % 60;
    return m > 0 ? `${m}:${String(r).padStart(2, "0")}` : `${r}s`;
  }

  function setSimpleStatus(mode){
    // mode: "IDLE" | "GENERATING" | "COMPLETED"
    statusBadge.classList.remove("good", "bad", "warn");

    if(mode === "COMPLETED"){
      statusBadge.textContent = "COMPLETED";
      statusBadge.classList.add("good");
      statusText.textContent = "Completed";
      return;
    }

    if(mode === "GENERATING"){
      statusBadge.textContent = "GENERATING";
      statusBadge.classList.add("warn");
      statusText.textContent = "Generating";
      return;
    }

    statusBadge.textContent = "IDLE";
    statusText.textContent = "—";
  }

  function resetPreview(){
    if(previewBox){
      previewBox.innerHTML = `
        <div class="placeholder">
          <div class="ph-title">Your video will appear here</div>
          <div class="ph-sub">Create a job on the left to start rendering.</div>
        </div>
      `;
    }
    if(durationEl) durationEl.textContent = "—";
  }

  function showPreviewForLanguage(lang){
    if(!previewBox || !currentJobId) return;

    const src = `${BACKEND}/api/v1/jobs/${currentJobId}/preview?language=${encodeURIComponent(lang)}&t=${Date.now()}`;

    previewBox.innerHTML = `
      <video class="preview-video" controls playsinline preload="metadata">
        <source src="${src}" type="video/mp4" />
        Your browser does not support the video tag.
      </video>
    `;

    const v = previewBox.querySelector("video");
    if(v){
      v.addEventListener("loadedmetadata", () => {
        if(durationEl) durationEl.textContent = formatDuration(v.duration);
      });

      v.addEventListener("error", () => {
        console.error("Preview video failed:", v.error);
      });
    }
  }

  async function createJob(){
    const query = (promptEl.value || "").trim();
    const langs = chips.getSelectedCodes();
    const style = styleSelect.value;

    if(!query){
      alert("Please enter a prompt.");
      return;
    }
    if(!langs.length){
      alert("Please select at least one language.");
      return;
    }

    resetPreview();

    generateBtn.disabled = true;
    setSimpleStatus("GENERATING");

    const res = await fetch(`${BACKEND}/api/v1/jobs`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ query, languages: langs, style })
    });

    if(!res.ok){
      const t = await res.text();
      generateBtn.disabled = false;
      setSimpleStatus("IDLE");
      alert(t);
      return;
    }

    const data = await res.json();
    currentJobId = data.job_id;

    // start polling
    if(pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(pollStatus, 2000);
    await pollStatus();
  }

  async function pollStatus(){
    if(!currentJobId) return;

    const res = await fetch(`${BACKEND}/api/v1/jobs/${currentJobId}?log_lines=0`);
    if(!res.ok) return;

    const job = await res.json();

    // Only show Generating / Completed in UI
    if(job.status === "COMPLETED"){
      clearInterval(pollTimer);
      pollTimer = null;
      generateBtn.disabled = false;

      setSimpleStatus("COMPLETED");

      downloadBtn.disabled = false;
      downloadHint.textContent = "Download ZIP (multi-language) or use backend API for single-language output.";

      // Show preview for first output (or you can change this)
      if(job.outputs && job.outputs.length){
        showPreviewForLanguage(job.outputs[0].language);
      }

    } else if(job.status === "FAILED"){
      // Still keep UI minimal: show Generating, but stop polling and show error via hint + alert
      clearInterval(pollTimer);
      pollTimer = null;
      generateBtn.disabled = false;

      setSimpleStatus("GENERATING"); // as requested (only Generating/Completed)
      downloadBtn.disabled = true;

      const err = job.error || "Unknown error";
      downloadHint.textContent = `Failed: ${err}`;
      alert(err);

    } else {
      setSimpleStatus("GENERATING");
    }
  }

  downloadBtn.addEventListener("click", () => {
    if(!currentJobId) return;
    window.open(`${BACKEND}/api/v1/jobs/${currentJobId}/download?format=zip`, "_blank");
  });

  generateBtn.addEventListener("click", createJob);

  // Chips styling (your existing)
  const style = document.createElement("style");
  style.textContent = `
    .chips-input{ position:relative; min-height:44px; display:flex; gap:8px; flex-wrap:wrap; align-items:center; padding:8px; border:1px solid var(--border); border-radius:12px; background:rgba(10,10,20,.6); }
    .chips-input input{ flex:1; min-width:160px; border:none; outline:none; background:transparent; color:var(--text); font-size:14px; padding:6px; }
    .chip{ display:flex; align-items:center; gap:8px; background:rgba(124,58,237,.18); border:1px solid rgba(124,58,237,.35); color:var(--text); border-radius:999px; padding:6px 10px; }
    .chip-code{ color:var(--muted); font-size:12px; }
    .chip-x{ border:none; background:transparent; color:var(--text); cursor:pointer; font-size:16px; line-height:1; }
    .suggestions{ position:absolute; left:8px; right:8px; top:calc(100% + 6px); background:rgba(18,18,38,.98); border:1px solid var(--border); border-radius:12px; display:none; max-height:240px; overflow:auto; z-index:20; }
    .suggestion-item{ padding:10px 12px; cursor:pointer; font-size:13px; color:var(--text); border-bottom:1px solid rgba(255,255,255,.06); }
    .suggestion-item:hover{ background:rgba(124,58,237,.18); }
    .suggestion-item:last-child{ border-bottom:none; }
  `;
  document.head.appendChild(style);

  // initial state
  resetPreview();
  setSimpleStatus("IDLE");
})();
