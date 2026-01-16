// Minimal autocomplete + chips input (no external libraries)
// Exposes: window.createChipsInput({rootId, inputId, suggestionsId, optionsMap})

(function(){
  function createChipsInput(cfg){
    const root = document.getElementById(cfg.rootId);
    const input = document.getElementById(cfg.inputId);
    const sug = document.getElementById(cfg.suggestionsId);
    const optionsMap = cfg.optionsMap || {}; // code -> name

    const selected = new Map(); // code -> name

    function renderChips(){
      // remove existing chips (everything except input + suggestions)
      const existing = root.querySelectorAll(".chip");
      existing.forEach(el => el.remove());

      for(const [code, name] of selected.entries()){
        const chip = document.createElement("div");
        chip.className = "chip";
        chip.innerHTML = `<span class="chip-text">${name} <span class="chip-code">(${code})</span></span><button class="chip-x" title="Remove">×</button>`;
        chip.querySelector(".chip-x").addEventListener("click", () => {
          selected.delete(code);
          renderChips();
        });
        root.insertBefore(chip, input);
      }
    }

    function showSuggestions(q){
      const query = (q || "").trim().toLowerCase();
      sug.innerHTML = "";
      if(!query){ sug.style.display="none"; return; }

      const items = Object.entries(optionsMap)
        .filter(([code, name]) => {
          const hay = (code + " " + name).toLowerCase();
          return hay.includes(query) && !selected.has(code);
        })
        .slice(0, 12);

      if(items.length === 0){ sug.style.display="none"; return; }

      for(const [code, name] of items){
        const item = document.createElement("div");
        item.className = "suggestion-item";
        item.textContent = `${name} (${code})`;
        item.addEventListener("click", () => {
          selected.set(code, name);
          input.value = "";
          sug.style.display="none";
          renderChips();
        });
        sug.appendChild(item);
      }
      sug.style.display="block";
    }

    function addFromText(text){
      const q = (text || "").trim().toLowerCase();
      if(!q) return;

      // Try exact code first
      if(optionsMap[q] && !selected.has(q)){
        selected.set(q, optionsMap[q]);
        renderChips();
        return;
      }

      // Try exact display match
      const match = Object.entries(optionsMap).find(([c, n]) => n.toLowerCase() === q);
      if(match && !selected.has(match[0])){
        selected.set(match[0], match[1]);
        renderChips();
        return;
      }
    }

    input.addEventListener("input", (e) => showSuggestions(e.target.value));
    input.addEventListener("keydown", (e) => {
      if(e.key === "Enter" || e.key === ","){
        e.preventDefault();
        addFromText(input.value);
        input.value = "";
        sug.style.display="none";
      } else if(e.key === "Escape"){
        sug.style.display="none";
      }
    });

    document.addEventListener("click", (e) => {
      if(!root.contains(e.target)) sug.style.display="none";
    });

    // public API
    return {
      getSelectedCodes: () => Array.from(selected.keys()),
      setSelectedCodes: (codes) => {
        selected.clear();
        (codes || []).forEach(c => { if(optionsMap[c]) selected.set(c, optionsMap[c]); });
        renderChips();
      },
      clear: () => { selected.clear(); renderChips(); },
    };
  }

  window.createChipsInput = createChipsInput;
})();
