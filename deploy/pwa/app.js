// Mobile authenticated application review PWA logic (read-only Firestore)
const hostingProjectId = window.location.hostname.endsWith(".web.app")
  ? window.location.hostname.slice(0, -".web.app".length)
  : "";
const firebaseConfig = window.JAA_FIREBASE_CONFIG || (
  hostingProjectId ? { projectId: hostingProjectId } : {}
);

let currentDraft = null;
let currentAppId = null;
let currentUserId = null;
let topApplications = [];
let activeDraftUnsubscribe = null;
let activeAppUnsubscribe = null;
let firestoreDb = null;

// Initialize Firebase
if (typeof firebase !== "undefined" && firebaseConfig.projectId) {
  try {
    firebase.initializeApp(firebaseConfig);
    firestoreDb = firebase.firestore();
    if (!firebase.auth) throw new Error("Firebase Authentication SDK is missing");
    firebase.auth().onAuthStateChanged((user) => {
      if (!user) {
        currentUserId = null;
        setSignInVisibility(true);
        setConnectionStatus("🔒 Sign-in required", "amber");
        return;
      }
      currentUserId = user.uid;
      setSignInVisibility(false);
      setConnectionStatus("● Realtime Live", "emerald");
      initApplicationsListener(firestoreDb);
    });
  } catch (err) {
    console.error("Firebase init error:", err);
    setConnectionStatus("⚠️ Connection Error", "rose");
  }
} else if (typeof firebase === "undefined") {
  setConnectionStatus("⚠️ Firebase SDK Missing", "rose");
} else {
  setConnectionStatus("⚠️ Firebase project not configured", "rose");
}

function setConnectionStatus(text, color) {
  const el = document.getElementById("connectionStatus");
  if (!el) return;
  el.innerText = text;
  if (color === "emerald") {
    el.className = "text-xs px-2.5 py-0.5 rounded-full bg-emerald-950/80 text-emerald-400 border border-emerald-800 font-mono";
  } else if (color === "rose") {
    el.className = "text-xs px-2.5 py-0.5 rounded-full bg-rose-950/80 text-rose-400 border border-rose-800 font-mono";
  } else {
    el.className = "text-xs px-2.5 py-0.5 rounded-full bg-amber-950/80 text-amber-400 border border-amber-800 font-mono";
  }
}

function escapeHtml(value) {
  const element = document.createElement("span");
  element.textContent = String(value ?? "");
  return element.innerHTML;
}

function setSignInVisibility(visible) {
  const button = document.getElementById("signInBtn");
  if (button) button.hidden = !visible;
}

const signInButton = document.getElementById("signInBtn");
if (signInButton) {
  signInButton.addEventListener("click", () => {
    firebase.auth().signInWithPopup(new firebase.auth.GoogleAuthProvider())
      .catch((error) => {
        console.error("Firebase sign-in error:", error);
        alert(`Sign-in failed: ${error.message}`);
      });
  });
}

// 1. Subscribe to /users/{userId}/applications in Firestore
function initApplicationsListener(db) {
  renderQueueLoading();

  db.collection("users")
    .doc(currentUserId)
    .collection("applications")
    .onSnapshot(
      (snapshot) => {
        const apps = [];
        snapshot.forEach((doc) => {
          const d = doc.data();
          d.id = doc.id;
          apps.push(d);
        });

        // Strictly filter to TO_APPLY status only
        const toApply = apps.filter((a) => a.status === "TO_APPLY");
        toApply.sort((a, b) => (b.match_score || 0) - (a.match_score || 0));

        topApplications = toApply.slice(0, 5);
        renderTopQueue(topApplications);

        if (topApplications.length === 0) {
          renderEmptyQueue();
          return;
        }

        // If no target selected, or selected target is no longer in TO_APPLY, select top job
        if (!currentAppId || !topApplications.some((a) => a.id === currentAppId)) {
          selectTargetJob(topApplications[0].id, topApplications[0]);
        }
      },
      (err) => {
        console.error("Firestore applications listener error:", err);
        setConnectionStatus("⚠️ Firestore Error", "rose");
      }
    );
}

function renderQueueLoading() {
  const container = document.getElementById("top5QueueContainer");
  if (!container) return;
  container.innerHTML = `
    <div class="animate-pulse flex space-x-2 w-full">
      <div class="h-16 bg-slate-900 rounded-xl w-44 border border-slate-800 shrink-0"></div>
      <div class="h-16 bg-slate-900 rounded-xl w-44 border border-slate-800 shrink-0"></div>
    </div>
  `;
}

function renderEmptyQueue() {
  const container = document.getElementById("top5QueueContainer");
  if (container) {
    container.innerHTML = `<div class="text-xs text-slate-500 italic px-2 py-3">No pending TO_APPLY applications in Firestore.</div>`;
  }
  const fields = document.getElementById("fieldsContainer");
  if (fields) {
    fields.innerHTML = `<div class="text-xs text-slate-500 italic p-4 text-center">All applications processed.</div>`;
  }
}

// 2. Render Top Queue Cards from Firestore
function renderTopQueue(apps) {
  const container = document.getElementById("top5QueueContainer");
  if (!container) return;
  container.innerHTML = "";

  apps.forEach((app, idx) => {
    const isSelected = app.id === currentAppId;
    const rank = `#${idx + 1}`;
    const score = app.match_score || 0;
    const company = escapeHtml(app.company || "Target");
    const role = escapeHtml(app.role || "Software Engineer");

    const card = document.createElement("button");
    card.className = `shrink-0 w-48 text-left p-2.5 rounded-xl border transition-all duration-200 cursor-pointer flex flex-col justify-between ${
      isSelected
        ? "bg-slate-900 border-sky-500 ring-2 ring-sky-500/50 shadow-lg shadow-sky-950/60 scale-[1.02]"
        : "bg-slate-900/80 border-slate-800 hover:border-slate-700 hover:bg-slate-900"
    }`;

    const scoreColor =
      score >= 80
        ? "text-emerald-400 bg-emerald-950/80 border-emerald-800/80"
        : score >= 65
        ? "text-amber-400 bg-amber-950/80 border-amber-800/80"
        : "text-slate-400 bg-slate-800 border-slate-700";

    card.innerHTML = `
      <div class="flex items-center justify-between w-full mb-1">
        <span class="text-[10px] font-mono font-bold ${isSelected ? 'text-sky-400' : 'text-slate-500'}">${rank}</span>
        <span class="text-[10px] font-bold px-1.5 py-0.2 rounded-full border ${scoreColor}">
          🎯 ${score}%
        </span>
      </div>
      <div class="font-bold text-xs text-slate-100 truncate w-full">${company}</div>
      <div class="text-[11px] text-slate-400 truncate w-full">${role}</div>
    `;

    card.addEventListener("click", () => {
      selectTargetJob(app.id, app);
    });

    container.appendChild(card);
  });
}

// 3. Select Target Job & Subscribe to its Firestore Draft
function selectTargetJob(appId, appMeta) {
  currentAppId = appId;
  renderTopQueue(topApplications);

  if (!firestoreDb) return;

  if (activeAppUnsubscribe) activeAppUnsubscribe();
  if (activeDraftUnsubscribe) activeDraftUnsubscribe();

  // Reset button state
  const btn = document.getElementById("approveBtn");
  if (btn) {
    btn.disabled = false;
    btn.innerHTML = `<span>✓</span><span>Review only</span>`;
    btn.className = "w-2/3 py-3 px-4 rounded-xl font-semibold text-sm bg-emerald-600 hover:bg-emerald-500 text-white shadow-lg shadow-emerald-950 transition flex items-center justify-center space-x-2 active:scale-[0.98]";
  }

  // Subscribe to the application doc in Firestore
  activeAppUnsubscribe = firestoreDb
    .collection("users")
    .doc(currentUserId)
    .collection("applications")
    .doc(appId)
    .onSnapshot((doc) => {
      if (doc.exists) {
        const appData = doc.data();
        const activeRev = appData.active_draft_revision || 1;

        if (activeDraftUnsubscribe) activeDraftUnsubscribe();

        // Subscribe to the active draft subcollection in Firestore
        activeDraftUnsubscribe = firestoreDb
          .collection("users")
          .doc(currentUserId)
          .collection("applications")
          .doc(appId)
          .collection("drafts")
          .doc(String(activeRev))
          .onSnapshot((draftDoc) => {
            if (draftDoc.exists) {
              const draftData = draftDoc.data();
              draftData.application_id = appId;
              renderDraft(draftData);
            } else {
              console.warn(`Draft document not found in Firestore for ${appId}/drafts/${activeRev}`);
            }
          });
      }
    });
}

// 4. Render Live Draft from Firestore
function renderDraft(draft) {
  currentDraft = draft;
  const companyBadge = document.getElementById("companyBadge");
  if (companyBadge) {
    companyBadge.innerText = draft.company || "Company";
    companyBadge.classList.remove("animate-pulse");
  }

  const jobTitle = document.getElementById("jobTitle");
  if (jobTitle) jobTitle.innerText = draft.job_title || "Software Engineer";

  const revBadge = document.getElementById("revisionBadge");
  if (revBadge) revBadge.innerText = `Rev ${draft.revision || 1}`;

  const hashEl = document.getElementById("draftHash");
  if (hashEl) hashEl.innerText = draft.draft_hash ? `Hash: ${draft.draft_hash}` : "";

  const score = draft.match_score || 0;
  const bd = draft.match_breakdown || {
    skills_score: Math.round(score * 0.3),
    experience_score: Math.round(score * 0.25),
    role_score: Math.round(score * 0.2),
    location_score: Math.round(score * 0.15),
  };

  const scoreBadge = document.getElementById("matchScoreBadge");
  if (scoreBadge) {
    scoreBadge.innerText = `🎯 ${score}% Match`;
    scoreBadge.className =
      score >= 80
        ? "text-xs bg-emerald-950/80 text-emerald-400 border border-emerald-800/80 px-2 py-0.5 rounded-full font-bold"
        : score >= 65
        ? "text-xs bg-amber-950/80 text-amber-400 border border-amber-800/80 px-2 py-0.5 rounded-full font-bold"
        : "text-xs bg-rose-950/80 text-rose-400 border border-rose-800/80 px-2 py-0.5 rounded-full font-bold";
  }

  const sEl = document.getElementById("skillsScore");
  if (sEl) sEl.innerText = `${bd.skills_score || 0}/30`;
  const eEl = document.getElementById("expScore");
  if (eEl) eEl.innerText = `${bd.experience_score || 0}/25`;
  const rEl = document.getElementById("roleScore");
  if (rEl) rEl.innerText = `${bd.role_score || 0}/20`;
  const lEl = document.getElementById("locScore");
  if (lEl) lEl.innerText = `${bd.location_score || 0}/15`;

  // Render fields directly from Firestore document
  const container = document.getElementById("fieldsContainer");
  if (!container) return;
  container.innerHTML = "";

  (draft.fields || []).forEach((f) => {
    const badgeColors = {
      profile: "bg-emerald-950/80 text-emerald-400 border-emerald-800",
      resume: "bg-sky-950/80 text-sky-400 border-sky-800",
      ai: "bg-amber-950/80 text-amber-400 border-amber-800",
      user: "bg-purple-950/80 text-purple-400 border-purple-800",
    };

    const icons = {
      profile: "✓ Known",
      resume: "✎ Derived",
      ai: "⚠ AI Generated",
      user: "✏ User Edited",
    };

    const badgeClass = badgeColors[f.source] || badgeColors.profile;
    const badgeText = icons[f.source] || "Field";
    const safeLabel = escapeHtml(f.label);
    const safeId = escapeHtml(f.id);
    const safeValue = escapeHtml(f.value || "");

    const fieldEl = document.createElement("div");
    fieldEl.className = "bg-slate-900 border border-slate-800 rounded-xl p-3 shadow-sm";
    fieldEl.innerHTML = `
      <div class="flex justify-between items-center mb-1.5">
        <label class="text-xs font-semibold text-slate-300 truncate pr-2">${safeLabel}</label>
        <span class="text-[10px] font-mono px-2 py-0.5 rounded border ${badgeClass}">${badgeText}</span>
      </div>
      <input type="text" data-field-id="${safeId}" value="${safeValue}"
        class="w-full bg-slate-950 border border-slate-800 focus:border-sky-500 rounded-lg px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:outline-none transition font-sans" />
    `;

    const input = fieldEl.querySelector("input");
    input.addEventListener("input", (e) => {
      f.value = e.target.value;
      f.source = "user";
    });

    container.appendChild(fieldEl);
  });
}

// 5. Review-only handler. Submission is intentionally not available in the
// client: /submissionJobs is server-only and the worker has a separate,
// explicitly opted-in deployment gate.
document.getElementById("approveBtn").addEventListener("click", () => {
  if (!currentDraft) return;

  const btn = document.getElementById("approveBtn");
  btn.disabled = true;
  btn.innerHTML = `<span>✓</span><span>Review recorded locally</span>`;
  btn.classList.remove("bg-emerald-600");
  btn.classList.add("bg-slate-700");
  alert("Review completed. No application was submitted and no submission job was queued.");
});
