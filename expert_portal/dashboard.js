/**
 * Expert Review & Agronomist Escalation Portal
 */

let allCases = [];
let selectedCaseId = null;
let diseaseClasses = [];

window.addEventListener("DOMContentLoaded", async () => {
  await loadLabels();
  await loadCases();

  document.getElementById("filter-status").addEventListener("change", loadCases);
  document.getElementById("filter-urgency").addEventListener("change", loadCases);
  document.getElementById("btn-refresh-queue").addEventListener("click", loadCases);
  document.getElementById("expert-review-form").addEventListener("submit", submitReview);
  document.getElementById("btn-export-retrain").addEventListener("click", exportRetrainingData);
});

async function loadLabels() {
  try {
    const res = await fetch("/api/labels");
    const data = await res.json();
    diseaseClasses = data.classes || [];

    const select = document.getElementById("select-verified-class");
    select.innerHTML = '<option value="">-- Select Verified Diagnosis --</option>';
    
    diseaseClasses.forEach(c => {
      const opt = document.createElement("option");
      opt.value = c.id;
      opt.innerText = `[${c.crop}] ${c.condition}`;
      select.appendChild(opt);
    });
  } catch (err) {
    console.warn("Failed to load disease labels:", err);
  }
}

async function loadCases() {
  const status = document.getElementById("filter-status").value;
  const urgency = document.getElementById("filter-urgency").value;

  let url = "/api/cases?";
  if (status) url += `status=${encodeURIComponent(status)}&`;
  if (urgency) url += `urgency=${encodeURIComponent(urgency)}&`;

  try {
    const res = await fetch(url);
    allCases = await res.json();
    renderQueue(allCases);

    // Bug Fix 4: Fetch unfiltered totals for the stat badges so they never
    // zero-out when filters are active.
    await updateDashboardStats();

    // Re-select the active case if it still exists in the filtered queue
    if (selectedCaseId) {
      const match = allCases.find(c => c.id === selectedCaseId);
      if (match) {
        selectCase(match);
      } else {
        // Bug Fix 4: If the case was moved out of the filtered view (e.g. after review),
        // clear the inspector rather than leaving it frozen on stale data.
        selectedCaseId = null;
        document.getElementById("no-case-selected").style.display = "flex";
        document.getElementById("case-inspector").style.display = "none";
        if (allCases.length > 0) selectCase(allCases[0]);
      }
    } else if (allCases.length > 0) {
      selectCase(allCases[0]);
    }
  } catch (err) {
    console.error("Error loading cases:", err);
    document.getElementById("case-list-container").innerHTML = `
      <div class="loading-state" style="color: #c62828;">
        Failed to connect to backend server. Make sure FastAPI server is running.
      </div>`;
  }
}

async function updateDashboardStats() {
  // Bug Fix 4: Always fetch ALL cases (unfiltered) for stat badges so that
  // filtering the queue by Status/Urgency never zeros-out the counters.
  let allUnfiltered = [];
  try {
    const res = await fetch("/api/cases?limit=500");
    allUnfiltered = await res.json();
  } catch (_) {
    allUnfiltered = allCases; // fallback to currently loaded slice
  }

  let urgent = 0;
  let pending = 0;
  let reviewed = 0;

  allUnfiltered.forEach(c => {
    if (c.urgency === "urgent_review" && c.status === "pending_review") urgent++;
    if (c.status === "pending_review") pending++;
    if (c.status === "reviewed") reviewed++;
  });

  document.getElementById("count-urgent").innerText = urgent;
  document.getElementById("count-pending").innerText = pending;
  document.getElementById("count-reviewed").innerText = reviewed;
}

function renderQueue(cases) {
  const container = document.getElementById("case-list-container");
  container.innerHTML = "";

  if (cases.length === 0) {
    container.innerHTML = '<div class="loading-state">No cases match the selected filters.</div>';
    return;
  }

  cases.forEach(c => {
    const card = document.createElement("div");
    card.className = `queue-card ${selectedCaseId === c.id ? "active" : ""}`;
    card.onclick = () => selectCase(c);

    let urgencyClass = "badge-optional";
    let urgencyText = "Optional";
    if (c.urgency === "urgent_review") {
      urgencyClass = "badge-urgent";
      urgencyText = "Urgent / OOD";
    } else if (c.urgency === "standard_review") {
      urgencyClass = "badge-standard";
      urgencyText = "Medium Conf";
    } else if (c.urgency === "farmer_requested") {
      urgencyClass = "badge-standard";
      urgencyText = "Farmer Req";
    }

    const confPct = Math.round(c.confidence * 100);
    const thumbUrl = c.image_compressed_path || c.image_path || "placeholder.png";

    // Format clean timestamp
    const dateObj = new Date(c.created_at);
    const timeStr = isNaN(dateObj) ? "Just now" : dateObj.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    card.innerHTML = `
      <img src="${thumbUrl}" class="queue-thumb" alt="Leaf Thumb" onerror="this.src='data:image/svg+xml,<svg xmlns=\'http://www.w3.org/2000/svg\' width=\'50\' height=\'50\'><rect width=\'50\' height=\'50\' fill=\'%23e0e0e0\'/><text x=\'50%25\' y=\'50%25\' dominant-baseline=\'middle\' text-anchor=\'middle\' fill=\'%23666\'>Leaf</text></svg>'">
      <div class="queue-info">
        <div class="queue-info-top">
          <span class="queue-id">${c.id}</span>
          <span class="queue-time">${timeStr}</span>
        </div>
        <div class="queue-title">${c.crop}: ${c.predicted_class.replace('___', ' ')}</div>
        <div class="queue-badges">
          <span class="badge-pill ${urgencyClass}">${urgencyText}</span>
          <span class="badge-pill badge-conf">${confPct}%</span>
        </div>
      </div>
    `;

    container.appendChild(card);
  });
}

function selectCase(c) {
  selectedCaseId = c.id;

  // Highlight active card
  document.querySelectorAll(".queue-card").forEach(el => el.classList.remove("active"));
  const cards = document.querySelectorAll(".queue-card");
  const targetIndex = allCases.findIndex(item => item.id === c.id);
  if (cards[targetIndex]) cards[targetIndex].classList.add("active");

  document.getElementById("no-case-selected").style.display = "none";
  const inspector = document.getElementById("case-inspector");
  inspector.style.display = "block";

  // Bind values
  document.getElementById("disp-case-id").innerText = c.id;
  document.getElementById("disp-headline").innerText = `${c.crop} - ${c.predicted_class.replace('___', ' ')}`;
  document.getElementById("disp-timestamp").innerText = new Date(c.created_at).toLocaleString();
  document.getElementById("disp-image").src = c.image_path || c.image_compressed_path || "";
  document.getElementById("disp-location").innerText = c.location_coords || "Field Coordinates N/A";
  document.getElementById("disp-notes").innerText = c.farmer_notes || "None provided";

  // AI metrics
  document.getElementById("disp-pred-class").innerText = c.predicted_class.replace('___', ' ');
  document.getElementById("disp-confidence").innerText = `${Math.round(c.confidence * 100)}%`;
  document.getElementById("disp-second-class").innerText = c.second_class ? `${c.second_class.replace('___', ' ')} (${Math.round((c.second_confidence || 0) * 100)}%)` : "None";
  document.getElementById("disp-entropy").innerText = c.entropy ? c.entropy.toFixed(3) : "N/A";
  document.getElementById("disp-model-version").innerText = c.model_version || "v1.0.0-mobilenetv3-quantized";

  // Urgency badge
  const urgBadge = document.getElementById("disp-urgency-badge");
  urgBadge.innerText = c.urgency.replace('_', ' ').toUpperCase();
  if (c.urgency === "urgent_review") {
    urgBadge.className = "badge-urgency";
    urgBadge.style.background = "#ffebee";
    urgBadge.style.color = "#d32f2f";
  } else {
    urgBadge.className = "badge-urgency";
    urgBadge.style.background = "#fff3e0";
    urgBadge.style.color = "#f57c00";
  }

  // Status badge
  const statusBadge = document.getElementById("disp-status-badge");
  statusBadge.innerText = c.status === "reviewed" ? "REVIEWED" : "PENDING";
  statusBadge.style.background = c.status === "reviewed" ? "#e8f5e9" : "#fff8e1";
  statusBadge.style.color = c.status === "reviewed" ? "#2e7d32" : "#f57f17";

  // Form pre-fill if case was already reviewed
  const form = document.getElementById("expert-review-form");
  if (c.expert_review) {
    document.getElementById("select-verified-class").value = c.expert_review.verified_class || "";
    document.getElementById("input-prescribed-actions").value = c.expert_review.prescribed_actions || "";
    document.getElementById("input-expert-notes").value = c.expert_review.expert_notes || "";
    const rad = form.querySelector(`input[name="severity"][value="${c.expert_review.severity_rating}"]`);
    if (rad) rad.checked = true;
  } else {
    // Default selection to model's predicted class if in taxonomy
    const select = document.getElementById("select-verified-class");
    select.value = c.predicted_class || "";
    document.getElementById("input-prescribed-actions").value = "";
    document.getElementById("input-expert-notes").value = "";
  }
}

async function submitReview(e) {
  e.preventDefault();
  if (!selectedCaseId) return;

  const verifiedClass = document.getElementById("select-verified-class").value;
  if (!verifiedClass) {
    alert("Please select a verified diagnosis from the list.");
    return;
  }

  const severity = document.querySelector('input[name="severity"]:checked').value;
  const actions = document.getElementById("input-prescribed-actions").value;
  const notes = document.getElementById("input-expert-notes").value;

  const payload = {
    expert_id: "Extension_Agronomist_01",
    verified_class: verifiedClass,
    severity_rating: severity,
    prescribed_actions: actions,
    expert_notes: notes
  };

  try {
    const res = await fetch(`/api/cases/${selectedCaseId}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (res.ok) {
      alert("✅ Expert verification submitted and synced to active learning pool!");
      await loadCases();
    } else {
      alert("Failed to submit review. Check server status.");
    }
  } catch (err) {
    console.error("Error submitting review:", err);
    alert("Network error submitting review.");
  }
}

async function exportRetrainingData() {
  try {
    const res = await fetch("/api/export/retraining");
    const data = await res.json();
    
    // Download as JSON file
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `active_learning_retrain_${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    alert(`Successfully exported ${data.total_verified_samples} verified expert cases for model retraining.`);
  } catch (err) {
    alert("Failed to export active learning dataset.");
  }
}
