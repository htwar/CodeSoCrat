const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const payload = await response.json();
      message = payload.detail || payload.message || message;
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

export async function getProblems(token) {
  return request("/problems", {
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

export async function getHints(token, problemId) {
  const encodedProblemId = encodeURIComponent(problemId);
  return request(`/hints?problem_id=${encodedProblemId}`, {
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
