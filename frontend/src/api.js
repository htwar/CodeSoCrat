const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || `${window.location.protocol}//${window.location.hostname}:8000`;
const CSRF_COOKIE_NAME = "codesocrat_csrf";

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

export async function login(credentials) {
  return request("/auth/login", {
    method: "POST",
    body: JSON.stringify(credentials),
  });
}

export async function register(credentials) {
  return request("/auth/register", {
    method: "POST",
    body: JSON.stringify(credentials),
  });
}

export async function getSession() {
  return request("/auth/session");
}

export async function logout() {
  return request("/auth/logout", {
    method: "POST",
  });
}

export async function getGoogleConfig() {
  return request("/auth/google/config");
}

export async function googleAuth(credential) {
  return request("/auth/google", {
    method: "POST",
    body: JSON.stringify({ credential }),
  });
}

export async function getProblems(difficulty) {
  const difficultyQuery = difficulty ? `?difficulty=${encodeURIComponent(difficulty)}` : "";
  return request(`/problems${difficultyQuery}`);
}

export async function getAuthorProblems(source = "all", includeDeleted = false) {
  const query = new URLSearchParams({
    source,
    include_deleted: String(includeDeleted),
  });
  return request(`/author/problems?${query.toString()}`);
}

export async function getAuthorProblem(problemId) {
  return request(`/author/problems/${encodeURIComponent(problemId)}`);
}

export async function runCode(payload) {
  return request("/run", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function submitCode(payload) {
  return request("/submit", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getHints(problemId, stage) {
  const encodedProblemId = encodeURIComponent(problemId);
  const stageQuery = stage ? `&stage=${encodeURIComponent(stage)}` : "";
  return request(`/hints?problem_id=${encodedProblemId}${stageQuery}`);
}

export async function getAnswerKey(problemId) {
  const encodedProblemId = encodeURIComponent(problemId);
  return request(`/answer-key?problem_id=${encodedProblemId}`);
}

export async function uploadProblem(payload) {
  return request("/author/problems/upload", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function uploadProblemFile(file) {
  const formData = new FormData();
  formData.append("file", file);
  return request("/author/problems/upload-file", {
    method: "POST",
    body: formData,
  });
}

export async function updateProblem(problemId, payload) {
  return request(`/author/problems/${encodeURIComponent(problemId)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function disableProblem(problemId) {
  return request(`/author/problems/${encodeURIComponent(problemId)}/disable`, {
    method: "POST",
  });
}

export async function enableProblem(problemId) {
  return request(`/author/problems/${encodeURIComponent(problemId)}/enable`, {
    method: "POST",
  });
}

export async function deleteProblem(problemId) {
  return request(`/author/problems/${encodeURIComponent(problemId)}`, {
    method: "DELETE",
  });
}

export async function resetProgress(problemId) {
  const encodedProblemId = encodeURIComponent(problemId);
  return request(`/progress/${encodedProblemId}`, {
    method: "DELETE",
  });
}
