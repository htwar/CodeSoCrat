const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

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
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...restOptions,
    headers: {
      "Content-Type": "application/json",
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

export async function getProblems(token, difficulty) {
  const difficultyQuery = difficulty ? `?difficulty=${encodeURIComponent(difficulty)}` : "";
  return request(`/problems${difficultyQuery}`, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });
}

export async function submitCode(token, payload) {
  return request("/submissions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(payload),
  });
}

export async function getHints(token, problemId, stage) {
  const encodedProblemId = encodeURIComponent(problemId);
  const stageQuery = stage ? `&stage=${encodeURIComponent(stage)}` : "";
  return request(`/hints?problem_id=${encodedProblemId}${stageQuery}`, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });
}

export async function uploadProblem(token, payload) {
  return request("/author/problems/upload", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(payload),
  });
}

export async function resetProgress(token, problemId) {
  const encodedProblemId = encodeURIComponent(problemId);
  return request(`/progress/${encodedProblemId}`, {
    method: "DELETE",
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });
}
