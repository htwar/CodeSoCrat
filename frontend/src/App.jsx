import { useEffect, useState } from "react";
import { getHints, getProblems, login, submitCode, uploadProblem } from "./api";

const starterUploadTemplate = `{
  "problem_id": "multiply_two_numbers",
  "title": "Multiply Two Numbers",
  "prompt": "Write a function named multiply_numbers(a, b) that returns the product of two numbers.",
  "difficulty": "Easy",
  "function_name": "multiply_numbers",
  "starter_code": "def multiply_numbers(a, b):\\n    pass\\n",
  "test_cases": [
    { "input": [2, 3], "expected": 6 },
    { "input": [-1, 4], "expected": -4 }
  ],
  "hints": {
    "1": "Think about the arithmetic operation used to combine repeated groups.",
    "2": "Return the result of multiplying the two parameters.",
    "3": "Use: return a * b"
  },
  "answer_key": {
    "solution_code": "def multiply_numbers(a, b):\\n    return a * b\\n",
    "explanation": "The function returns the product of the two numbers using the * operator."
  }
}`;

const demoSolution = "def add_numbers(a, b):\n    return a + b\n";

const SESSION_STORAGE_KEY = "codesocrat-session";

function AuthPanel({ onLogin, loading, error }) {
  const [email, setEmail] = useState("student@codesocrat.dev");
  const [password, setPassword] = useState("studentpass");

  function handleSubmit(event) {
    event.preventDefault();
    onLogin({ email, password });
  }

  return (
    <section className="auth-card">
      <p className="eyebrow">CodeSoCrat</p>
      <h1>Practice Python with guided feedback</h1>
      <p className="lede">
        Log in as a student to solve problems or as an author to upload new ones.
      </p>
      <form className="auth-form" onSubmit={handleSubmit}>
        <label>
          Email
          <input value={email} onChange={(event) => setEmail(event.target.value)} />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        <button type="submit" disabled={loading}>
          {loading ? "Signing in..." : "Sign in"}
        </button>
      </form>
      {error ? <p className="error-text">{error}</p> : null}
      <div className="account-hints">
        <span>Student: student@codesocrat.dev / studentpass</span>
        <span>Author: author@codesocrat.dev / authorpass</span>
      </div>
    </section>
  );
}

function ProblemList({ problems, selectedProblemId, onSelect }) {
  return (
    <aside className="panel problem-list">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Problem Set</p>
          <h2>Choose a challenge</h2>
        </div>
      </div>
      <div className="problem-items">
        {problems.map((problem) => (
          <button
            key={problem.problem_id}
            className={selectedProblemId === problem.problem_id ? "problem-item active" : "problem-item"}
            onClick={() => onSelect(problem.problem_id)}
            type="button"
          >
            <strong>{problem.title}</strong>
            <span>{problem.difficulty}</span>
          </button>
        ))}
      </div>
    </aside>
  );
}

function SubmissionPanel({
  problem,
  code,
  setCode,
  onSubmit,
  submissionState,
  hintState,
  onLoadHints,
}) {
  if (!problem) {
    return (
      <section className="panel workspace-panel empty-panel">
        <h2>Pick a problem to begin</h2>
        <p>Your prompt, editor, results, and hints will appear here.</p>
      </section>
    );
  }

  return (
    <section className="workspace-grid">
      <div className="panel workspace-panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">{problem.difficulty}</p>
            <h2>{problem.title}</h2>
          </div>
          <button type="button" className="secondary-button" onClick={() => setCode(problem.starter_code || "")}>
            Reset to Starter
          </button>
        </div>
        <p className="prompt-copy">{problem.prompt}</p>
        <p className="meta-copy">Required function: <code>{problem.function_name}</code></p>
        <textarea
          className="editor"
          value={code}
          onChange={(event) => setCode(event.target.value)}
          spellCheck="false"
        />
        <div className="editor-actions">
          <button type="button" onClick={onSubmit} disabled={submissionState.loading}>
            {submissionState.loading ? "Running..." : "Run Submission"}
          </button>
          <button type="button" className="ghost-button" onClick={() => setCode(demoSolution)}>
            Load Demo Pass
          </button>
        </div>
        {submissionState.error ? <p className="error-text">{submissionState.error}</p> : null}
        {submissionState.result ? (
          <div className={submissionState.result.result === "Pass" ? "result-card pass" : "result-card fail"}>
            <h3>{submissionState.result.result}</h3>
            <p>{submissionState.result.feedback}</p>
            <div className="result-grid">
              <span>Failure Category: {submissionState.result.failure_category || "None"}</span>
              <span>Runtime: {submissionState.result.runtime_ms} ms</span>
              <span>Hint Stage: {submissionState.result.hint_stage_unlocked}</span>
              <span>Valid Failed Attempts: {submissionState.result.valid_failed_attempts}</span>
            </div>
          </div>
        ) : null}
      </div>

      <div className="panel hints-panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Feedback</p>
            <h2>Hints</h2>
          </div>
          <button type="button" className="secondary-button" onClick={onLoadHints} disabled={hintState.loading}>
            {hintState.loading ? "Loading..." : "Load Hints"}
          </button>
        </div>
        {hintState.error ? <p className="error-text">{hintState.error}</p> : null}
        <HintCard title="Conceptual" content={hintState.hints?.conceptual} />
        <HintCard title="Strategic" content={hintState.hints?.strategic} />
        <HintCard title="Syntactic" content={hintState.hints?.syntactic} />
      </div>
    </section>
  );
}

function HintCard({ title, content }) {
  return (
    <article className={content ? "hint-card unlocked" : "hint-card locked"}>
      <h3>{title}</h3>
      <p>{content || "Locked until you earn this hint stage."}</p>
    </article>
  );
}

function AuthorPanel({ token }) {
  const [jsonText, setJsonText] = useState(starterUploadTemplate);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function handleUpload() {
    setLoading(true);
    setMessage("");
    setError("");

    try {
      const payload = JSON.parse(jsonText);
      const response = await uploadProblem(token, payload);
      setMessage(`Uploaded ${response.problem_id} successfully.`);
    } catch (uploadError) {
      setError(uploadError.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="panel author-panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Author Tools</p>
          <h2>Upload a problem definition</h2>
        </div>
      </div>
      <p className="prompt-copy">
        Paste a single JSON problem payload here and send it to the backend upload endpoint.
      </p>
      <textarea className="editor author-editor" value={jsonText} onChange={(event) => setJsonText(event.target.value)} />
      <div className="editor-actions">
        <button type="button" onClick={handleUpload} disabled={loading}>
          {loading ? "Uploading..." : "Upload Problem"}
        </button>
      </div>
      {message ? <p className="success-text">{message}</p> : null}
      {error ? <p className="error-text">{error}</p> : null}
    </section>
  );
}

export default function App() {
  const [session, setSession] = useState(() => {
    try {
      const storedSession = window.localStorage.getItem(SESSION_STORAGE_KEY);
      return storedSession ? JSON.parse(storedSession) : null;
    } catch (_error) {
      return null;
    }
  });
  const [authLoading, setAuthLoading] = useState(false);
  const [authError, setAuthError] = useState("");
  const [problems, setProblems] = useState([]);
  const [selectedProblemId, setSelectedProblemId] = useState("");
  const [codeByProblem, setCodeByProblem] = useState({});
  const [submissionState, setSubmissionState] = useState({ loading: false, result: null, error: "" });
  const [hintState, setHintState] = useState({ loading: false, hints: null, error: "" });

  useEffect(() => {
    if (session) {
      window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
      return;
    }
    window.localStorage.removeItem(SESSION_STORAGE_KEY);
  }, [session]);

  useEffect(() => {
    if (!session?.token) {
      return;
    }

    let isActive = true;

    async function loadProblems() {
      try {
        const response = await getProblems(session.token);
        if (!isActive) {
          return;
        }
        setProblems(response.problems);
        if (response.problems.length > 0) {
          const firstProblem = response.problems[0];
          setSelectedProblemId((current) => current || firstProblem.problem_id);
          setCodeByProblem((current) => {
            const next = { ...current };
            response.problems.forEach((problem) => {
              if (next[problem.problem_id] === undefined) {
                next[problem.problem_id] = problem.starter_code || "";
              }
            });
            return next;
          });
        }
      } catch (loadError) {
        if (isActive) {
          setAuthError(loadError.message);
        }
      }
    }

    loadProblems();
    return () => {
      isActive = false;
    };
  }, [session]);

  const selectedProblem = problems.find((problem) => problem.problem_id === selectedProblemId) || null;
  const currentCode = selectedProblem ? codeByProblem[selectedProblem.problem_id] || "" : "";

  function updateCode(nextCode) {
    if (!selectedProblem) {
      return;
    }
    setCodeByProblem((current) => ({
      ...current,
      [selectedProblem.problem_id]: nextCode,
    }));
  }

  async function handleLogin(credentials) {
    setAuthLoading(true);
    setAuthError("");

    try {
      const response = await login(credentials);
      setSession(response);
    } catch (loginError) {
      setAuthError(loginError.message);
    } finally {
      setAuthLoading(false);
    }
  }

  async function handleSubmit() {
    if (!selectedProblem || !session?.token) {
      return;
    }

    setSubmissionState({ loading: true, result: null, error: "" });

    try {
      const response = await submitCode(session.token, {
        problem_id: selectedProblem.problem_id,
        code: currentCode,
        timed_mode: false,
      });
      setSubmissionState({ loading: false, result: response, error: "" });
    } catch (submitError) {
      setSubmissionState({ loading: false, result: null, error: submitError.message });
    }
  }

  async function handleLoadHints() {
    if (!selectedProblem || !session?.token) {
      return;
    }

    setHintState({ loading: true, hints: null, error: "" });

    try {
      const response = await getHints(session.token, selectedProblem.problem_id);
      setHintState({ loading: false, hints: response, error: "" });
    } catch (hintError) {
      setHintState({ loading: false, hints: null, error: hintError.message });
    }
  }

  function handleSelectProblem(problemId) {
    setSelectedProblemId(problemId);
    setSubmissionState({ loading: false, result: null, error: "" });
    setHintState({ loading: false, hints: null, error: "" });
  }

  function handleLogout() {
    setSession(null);
    setProblems([]);
    setSelectedProblemId("");
    setCodeByProblem({});
    setSubmissionState({ loading: false, result: null, error: "" });
    setHintState({ loading: false, hints: null, error: "" });
    setAuthError("");
  }

  if (!session) {
    return (
      <main className="app-shell auth-shell">
        <AuthPanel onLogin={handleLogin} loading={authLoading} error={authError} />
      </main>
    );
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Logged In</p>
          <h1>CodeSoCrat Workspace</h1>
        </div>
        <div className="topbar-actions">
          <span>{session.role}</span>
          <button type="button" className="secondary-button" onClick={handleLogout}>
            Sign out
          </button>
        </div>
      </header>

      <section className="dashboard">
        <ProblemList problems={problems} selectedProblemId={selectedProblemId} onSelect={handleSelectProblem} />
        <SubmissionPanel
          problem={selectedProblem}
          code={currentCode}
          setCode={updateCode}
          onSubmit={handleSubmit}
          submissionState={submissionState}
          hintState={hintState}
          onLoadHints={handleLoadHints}
        />
      </section>

      {session.role === "Author" ? <AuthorPanel token={session.token} /> : null}
    </main>
  );
}
