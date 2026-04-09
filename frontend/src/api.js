const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || `${window.location.protocol}//${window.location.hostname}:8000`;
const CSRF_COOKIE_NAME = "codesocrat_csrf";

// Read the CSRF token from the browser cookie so state-changing requests can
// include it automatically.
function getCookie(name) {
  const cookies = document.cookie ? document.cookie.split("; ") : [];
  for (const cookie of cookies) {
    const [cookieName, ...rest] = cookie.split("=");
    if (cookieName === name) {
      return decodeURIComponent(rest.join("="));
    }
  }
  return "";
}

// Translate FastAPI validation payloads into user-facing messages that match
// the terminology shown in the UI.
function formatValidationError(item) {
  const location = Array.isArray(item.loc) ? item.loc.join(".") : "";
  const prettyField = location
    .replace(/^body\./, "")
    .replace(/confirm_password/g, "confirm password")
    .replace(/password/g, "password")
    .replace(/email/g, "email")
    .replace(/_/g, " ");

  if (item.msg.includes("at least 8 characters")) {
    if (prettyField.includes("confirm password")) {
      return "Confirm password must be at least 8 characters.";
    }
    if (prettyField.includes("password")) {
      return "Password must be at least 8 characters.";
    }
  }

  if (prettyField) {
    return `${prettyField.charAt(0).toUpperCase()}${prettyField.slice(1)}: ${item.msg}`;
  }

  return item.msg;
}

// Shared fetch wrapper for every frontend request. This keeps cookie auth,
// CSRF handling, and backend error parsing consistent across the app.
async function request(path, options = {}) {
  const { headers: customHeaders = {}, ...restOptions } = options;
  const method = (restOptions.method || "GET").toUpperCase();
  const isFormData = typeof FormData !== "undefined" && restOptions.body instanceof FormData;
  const csrfHeaders = {};
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const csrfToken = getCookie(CSRF_COOKIE_NAME);
    if (csrfToken) {
      csrfHeaders["X-CSRF-Token"] = csrfToken;
    }
  }
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...restOptions,
    credentials: "include",
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...csrfHeaders,
      ...customHeaders,
    },
  });

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const payload = await response.json();
      if (Array.isArray(payload.detail)) {
        message = payload.detail.map((item) => formatValidationError(item)).join(" ");
      } else {
        message = payload.detail || payload.message || message;
      }
    } catch (_error) {
      message = await response.text() || message;
    }
    throw new Error(message);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

// Authentication endpoints.
export async function login(credentials) {
  // Exchange email/password credentials for a logged-in browser session.
  return request("/auth/login", {
    method: "POST",
    body: JSON.stringify(credentials),
  });
}

export async function register(credentials) {
  // Create a new student account and receive the same session payload as login.
  return request("/auth/register", {
    method: "POST",
    body: JSON.stringify(credentials),
  });
}

export async function getSession() {
  // Ask the backend whether the current browser cookies still map to a user.
  return request("/auth/session");
}

export async function logout() {
  // Clear the backend session and CSRF cookies.
  return request("/auth/logout", {
    method: "POST",
  });
}

export async function getGoogleConfig() {
  // The frontend checks this first so the Google button only renders when the
  // backend has a client ID configured.
  return request("/auth/google/config");
}

export async function googleAuth(credential) {
  // Google Identity Services returns a credential token, which the backend
  // verifies before creating or linking an account.
  return request("/auth/google", {
    method: "POST",
    body: JSON.stringify({ credential }),
  });
}

// Problem browsing and author dashboard endpoints.
export async function getProblems(difficulty) {
  // Fetch the learner-facing problem list for one difficulty tab.
  const difficultyQuery = difficulty ? `?difficulty=${encodeURIComponent(difficulty)}` : "";
  return request(`/problems${difficultyQuery}`);
}

export async function getAuthorProblems(source = "all", includeDeleted = false) {
  // Fetch the author dashboard inventory with the requested source filter.
  const query = new URLSearchParams({
    source,
    include_deleted: String(includeDeleted),
  });
  return request(`/author/problems?${query.toString()}`);
}

export async function getAuthorProblem(problemId) {
  // Load a single editable custom problem back into the JSON workspace.
  return request(`/author/problems/${encodeURIComponent(problemId)}`);
}

// Evaluation and progress endpoints.
export async function runCode(payload) {
  // Execute code in practice mode without consuming a formal submission.
  return request("/run", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function submitCode(payload) {
  // Execute code as a full submission that affects hint/answer-key progress.
  return request("/submit", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// Hint, answer-key, and author problem management endpoints.
export async function getHints(problemId, stage) {
  // Get the currently available hints, or generate one specific unlocked stage.
  const encodedProblemId = encodeURIComponent(problemId);
  const stageQuery = stage ? `&stage=${encodeURIComponent(stage)}` : "";
  return request(`/hints?problem_id=${encodedProblemId}${stageQuery}`);
}

export async function getAnswerKey(problemId) {
  // Retrieve the answer key payload when the learner has unlocked it.
  const encodedProblemId = encodeURIComponent(problemId);
  return request(`/answer-key?problem_id=${encodedProblemId}`);
}

export async function uploadProblem(payload) {
  // Create a custom author problem from the JSON editor contents.
  return request("/author/problems/upload", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function uploadProblemFile(file) {
  // File uploads use multipart/form-data so authors can import a problem JSON
  // directly instead of pasting it into the editor first.
  const formData = new FormData();
  formData.append("file", file);
  return request("/author/problems/upload-file", {
    method: "POST",
    body: formData,
  });
}

export async function updateProblem(problemId, payload) {
  // Save edited JSON back onto an existing custom problem.
  return request(`/author/problems/${encodeURIComponent(problemId)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function disableProblem(problemId) {
  // Mark a custom problem inactive without deleting its row.
  return request(`/author/problems/${encodeURIComponent(problemId)}/disable`, {
    method: "POST",
  });
}

export async function enableProblem(problemId) {
  // Re-enable a previously disabled custom problem.
  return request(`/author/problems/${encodeURIComponent(problemId)}/enable`, {
    method: "POST",
  });
}

export async function deleteProblem(problemId) {
  // Soft-delete a custom problem from the author dashboard.
  return request(`/author/problems/${encodeURIComponent(problemId)}`, {
    method: "DELETE",
  });
}

export async function resetProgress(problemId) {
  // Clear one learner's stored attempts, hints, and unlock state for a problem.
  const encodedProblemId = encodeURIComponent(problemId);
  return request(`/progress/${encodedProblemId}`, {
    method: "DELETE",
  });
}
