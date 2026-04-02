import Editor from "@monaco-editor/react";
import { useEffect, useState } from "react";
import { getAnswerKey, getHints, getProblems, getSession, login, logout, register, resetProgress, runCode, submitCode, uploadProblem } from "./api";

const starterUploadTemplate = `{
  "problem_id": "multiply_two_numbers",
  "title": "Multiply Two Numbers",
  "prompt": "Write a function named multiply_numbers(a, b) that returns the product of two numbers.",
  "difficulty": "Easy",
  "function_name": "multiply_numbers",
  "starter_code": "def multiply_numbers(a, b):\\n    pass\\n",
  "example_cases": [
    { "input": [2, 3], "expected": 6 }
  ],
  "test_cases": [
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

const DIFFICULTIES = ["Easy", "Medium", "Hard"];
const HINT_TYPE_LABELS = {
  0: "None",
  1: "Conceptual",
  2: "Strategic",
  3: "Syntactic",
};

function AuthPanel({ onLogin, onRegister, loading, error }) {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("student@codesocrat.dev");
  const [password, setPassword] = useState("studentpass");
  const [confirmPassword, setConfirmPassword] = useState("");

  function handleSubmit(event) {
    event.preventDefault();
    if (mode === "register") {
      onRegister({ email, password, confirm_password: confirmPassword });
      return;
    }
    onLogin({ email, password });
  }

  return (
    <section className="auth-card">
      <h1 className="eyebrow">CodeSoCrat</h1>
      <p>Practice Python with guided feedback</p>
      <p className="lede">
        Log in to keep working, or create a new student account to start fresh.
      </p>
      <div className="auth-toggle">
        <button
          type="button"
          className={mode === "login" ? "toggle-button active" : "toggle-button"}
          onClick={() => setMode("login")}
        >
          Sign in
        </button>
        <button
          type="button"
          className={mode === "register" ? "toggle-button active" : "toggle-button"}
          onClick={() => setMode("register")}
        >
          Create account
        </button>
      </div>
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
        {mode === "register" ? (
          <label>
            Confirm Password
            <input
              type="password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
            />
          </label>
        ) : null}
        <button type="submit" disabled={loading}>
          {loading ? (mode === "register" ? "Creating..." : "Signing in...") : (mode === "register" ? "Create account" : "Sign in")}
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

function ProblemList({ problems, selectedDifficulty, selectedProblemId, onDifficultyChange, onSelect }) {
  return (
    <aside className="panel problem-list">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Problem Set</p>
          <h2>Choose a challenge</h2>
        </div>
      </div>
      <div className="difficulty-picker" role="tablist" aria-label="Difficulty levels">
        {DIFFICULTIES.map((difficulty) => (
          <button
            key={difficulty}
            type="button"
            className={selectedDifficulty === difficulty ? "difficulty-chip active" : "difficulty-chip"}
            onClick={() => onDifficultyChange(difficulty)}
            role="tab"
            aria-selected={selectedDifficulty === difficulty}
            tabIndex={selectedDifficulty === difficulty ? 0 : -1}
          >
            {difficulty}
          </button>
        ))}
      </div>
      <div className="problem-items">
        {problems.length === 0 ? <p className="meta-copy">No problems available in this difficulty yet.</p> : null}
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
  onRun,
  onSubmit,
  onResetProgress,
  submissionState,
  hintState,
  answerKeyState,
  onViewAnswerKey,
  onUnlockHint,
}) {
  const editorOptions = {
    automaticLayout: true,
    fontSize: 15,
    glyphMargin: false,
    lineNumbers: "on",
    minimap: { enabled: false },
    padding: { top: 16, bottom: 16 },
    renderLineHighlight: "all",
    roundedSelection: false,
    scrollBeyondLastLine: false,
    tabSize: 4,
    wordWrap: "on",
  };

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
          <div className="panel-actions">
            <button type="button" className="secondary-button" onClick={() => setCode(problem.starter_code || "")}>
              Reset to Starter
            </button>
            <button type="button" className="danger-button" onClick={onResetProgress}>
              Reset Progress
            </button>
          </div>
        </div>
        <p className="prompt-copy">{problem.prompt}</p>
        <p className="meta-copy">Required function: <code>{problem.function_name}</code></p>
        {problem.example_cases?.length ? (
          <div className="examples-panel">
            <p className="meta-copy"><strong>Sample Cases</strong></p>
            <div className="example-list">
              {problem.example_cases.map((exampleCase, index) => (
                <div key={`${problem.problem_id}-example-${index}`} className="example-card">
                  <p className="meta-copy">Example {index + 1}</p>
                  <p className="meta-copy">
                    Input: <code>{JSON.stringify(exampleCase.input)}</code>
                  </p>
                  <p className="meta-copy">
                    Expected: <code>{JSON.stringify(exampleCase.expected)}</code>
                  </p>
                </div>
              ))}
            </div>
            <p className="meta-copy">Additional grading cases are hidden and used only during evaluation.</p>
          </div>
        ) : null}
        <div className="editor-frame">
          <Editor
            defaultLanguage="python"
            language="python"
            value={code}
            onChange={(value) => setCode(value || "")}
            options={editorOptions}
            theme="vs"
            height="420px"
          />
        </div>
        <div className="editor-actions">
          <button
            type="button"
            className="secondary-button"
            onClick={onRun}
            disabled={Boolean(submissionState.loadingAction)}
          >
            {submissionState.loadingAction === "Run" ? "Running..." : "Run"}
          </button>
          <button type="button" onClick={onSubmit} disabled={Boolean(submissionState.loadingAction)}>
            {submissionState.loadingAction === "Submit" ? "Submitting..." : "Submit"}
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
              <span>Last Action: {submissionState.result.execution_type}</span>
              <span>Failure Category: {submissionState.result.failure_category || "None"}</span>
              <span>Runtime: {submissionState.result.runtime_ms} ms</span>
              <span>Highest Hint Type: {HINT_TYPE_LABELS[submissionState.result.hint_stage_unlocked] || "None"}</span>
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
        </div>
        {hintState.error ? <p className="error-text">{hintState.error}</p> : null}
        <HintCard
          title="Conceptual"
          stage={1}
          hintState={hintState}
          onUnlockHint={onUnlockHint}
        />
        <HintCard
          title="Strategic"
          stage={2}
          hintState={hintState}
          onUnlockHint={onUnlockHint}
        />
        <HintCard
          title="Syntactic"
          stage={3}
          hintState={hintState}
          onUnlockHint={onUnlockHint}
        />
        <AnswerKeyCard answerKeyState={answerKeyState} onViewAnswerKey={onViewAnswerKey} />
      </div>
    </section>
  );
}

function HintCard({ title, stage, hintState, onUnlockHint }) {
  const hints = hintState.hints || {};
  const stageKey = stage === 1 ? "conceptual" : stage === 2 ? "strategic" : "syntactic";
  const content = hints[stageKey];
  const unlockedStages = hints.unlocked_stages || [];
  const isUnlocked = unlockedStages.includes(stage);
  const isHighlighted = isUnlocked && hints.highlight_stage === stage;
  const isLoading = hintState.loadingStage === stage;

  return (
    <article
      className={[
        "hint-card",
        content ? "unlocked" : "locked",
        isHighlighted ? "highlighted" : "",
      ].join(" ").trim()}
    >
      <h3>{title}</h3>
      <p>
        {content
          ? content
          : isUnlocked
            ? "This hint is unlocked and ready. Reveal it when you want more guidance."
            : "Locked until you earn this hint type."}
      </p>
      {isUnlocked && !content ? (
        <button type="button" className="secondary-button" onClick={() => onUnlockHint(stage)} disabled={isLoading}>
          {isLoading ? "Unlocking..." : "Unlock Hint"}
        </button>
      ) : null}
    </article>
  );
}

function AnswerKeyCard({ answerKeyState, onViewAnswerKey }) {
  const isUnlocked = answerKeyState.unlocked;
  const hasContent = Boolean(answerKeyState.content);

  return (
    <article
      className={[
        "hint-card",
        hasContent ? "unlocked" : "locked",
        isUnlocked ? "highlighted" : "",
      ].join(" ").trim()}
    >
      <h3>Answer Key</h3>
      {hasContent ? (
        <>
          <p>{answerKeyState.content.explanation}</p>
          <div className="editor-frame answer-key-frame">
            <Editor
              defaultLanguage="python"
              language="python"
              value={answerKeyState.content.solution_code}
              options={{
                automaticLayout: true,
                fontSize: 14,
                lineNumbers: "on",
                minimap: { enabled: false },
                readOnly: true,
                renderLineHighlight: "none",
                scrollBeyondLastLine: false,
                wordWrap: "on",
              }}
              theme="vs"
              height="200px"
            />
          </div>
        </>
      ) : (
        <p>
          {isUnlocked
            ? "You have earned the answer key for this problem. Reveal it when you are ready to compare your work."
            : "Locked until you reach four valid failed Submit attempts on this problem."}
        </p>
      )}
      {answerKeyState.error ? <p className="error-text">{answerKeyState.error}</p> : null}
      {isUnlocked && !hasContent ? (
        <button type="button" className="secondary-button" onClick={onViewAnswerKey} disabled={answerKeyState.loading}>
          {answerKeyState.loading ? "Loading..." : "View Answer Key"}
        </button>
      ) : null}
    </article>
  );
}

function AuthorPanel() {
  const [jsonText, setJsonText] = useState(starterUploadTemplate);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const authorEditorOptions = {
    automaticLayout: true,
    fontSize: 14,
    formatOnPaste: true,
    lineNumbers: "on",
    minimap: { enabled: false },
    padding: { top: 16, bottom: 16 },
    renderLineHighlight: "all",
    scrollBeyondLastLine: false,
    tabSize: 2,
    wordWrap: "on",
  };

  async function handleUpload() {
    setLoading(true);
    setMessage("");
    setError("");

    try {
      const payload = JSON.parse(jsonText);
      const response = await uploadProblem(payload);
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
      <div className="editor-frame author-editor-frame">
        <Editor
          defaultLanguage="json"
          language="json"
          value={jsonText}
          onChange={(value) => setJsonText(value || "")}
          options={authorEditorOptions}
          theme="vs"
          height="320px"
        />
      </div>
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
  const [session, setSession] = useState(null);
  const [sessionLoading, setSessionLoading] = useState(true);
  const [authLoading, setAuthLoading] = useState(false);
  const [authError, setAuthError] = useState("");
  const [problems, setProblems] = useState([]);
  const [selectedDifficulty, setSelectedDifficulty] = useState("Easy");
  const [selectedProblemId, setSelectedProblemId] = useState("");
  const [codeByProblem, setCodeByProblem] = useState({});
  const [submissionState, setSubmissionState] = useState({ loadingAction: null, result: null, error: "" });
  const [hintState, setHintState] = useState({ loadingStage: null, hints: null, error: "" });
  const [answerKeyState, setAnswerKeyState] = useState({ unlocked: false, loading: false, content: null, error: "" });

  useEffect(() => {
    let isActive = true;

    async function restoreSession() {
      try {
        const response = await getSession();
        if (isActive) {
          setSession(response);
        }
      } catch (_error) {
        if (isActive) {
          setSession(null);
        }
      } finally {
        if (isActive) {
          setSessionLoading(false);
        }
      }
    }

    restoreSession();
    return () => {
      isActive = false;
    };
  }, []);

  useEffect(() => {
    if (!session) {
      return;
    }

    let isActive = true;

    async function loadProblems() {
      try {
        const response = await getProblems(selectedDifficulty);
        if (!isActive) {
          return;
        }
        setAuthError("");
        setProblems(response.problems);
        if (response.problems.length > 0) {
          const firstProblem = response.problems[0];
          setSelectedProblemId((current) => {
            const stillExists = response.problems.some((problem) => problem.problem_id === current);
            return stillExists ? current : firstProblem.problem_id;
          });
          setCodeByProblem((current) => {
            const next = { ...current };
            response.problems.forEach((problem) => {
              if (next[problem.problem_id] === undefined) {
                next[problem.problem_id] = problem.starter_code || "";
              }
            });
            return next;
          });
        } else {
          setSelectedProblemId("");
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
  }, [session, selectedDifficulty]);

  const selectedProblem = problems.find((problem) => problem.problem_id === selectedProblemId) || null;
  const currentCode = selectedProblem ? codeByProblem[selectedProblem.problem_id] || "" : "";

  useEffect(() => {
    if (!selectedProblem || !session) {
      return;
    }

    refreshHintState(selectedProblem.problem_id);
    refreshAnswerKeyState(selectedProblem.problem_id);
  }, [selectedProblemId, session]);

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

  async function handleRegister(credentials) {
    setAuthLoading(true);
    setAuthError("");

    try {
      const response = await register(credentials);
      setSession(response);
    } catch (registerError) {
      setAuthError(registerError.message);
    } finally {
      setAuthLoading(false);
    }
  }

  async function refreshHintState(problemId) {
    try {
      const response = await getHints(problemId);
      setHintState({ loadingStage: null, hints: response, error: "" });
    } catch (hintError) {
      if (String(hintError.message).includes("No hints unlocked yet")) {
        setHintState({
          loadingStage: null,
          hints: {
            problem_id: problemId,
            unlocked_stage: 0,
            unlocked_stages: [],
            highlight_stage: null,
            conceptual: null,
            strategic: null,
            syntactic: null,
          },
          error: "",
        });
        return;
      }
      setHintState({ loadingStage: null, hints: null, error: hintError.message });
    }
  }

  async function refreshAnswerKeyState(problemId) {
    try {
      const response = await getAnswerKey(problemId);
      setAnswerKeyState({
        unlocked: response.unlocked,
        loading: false,
        content: response.unlocked ? response : null,
        error: "",
      });
    } catch (answerKeyError) {
      setAnswerKeyState({ unlocked: false, loading: false, content: null, error: answerKeyError.message });
    }
  }

  async function executeCode(action) {
    if (!selectedProblem || !session) {
      return;
    }

    setSubmissionState({ loadingAction: action, result: null, error: "" });
    if (action === "Submit") {
      // A new official submission can change hint availability, so we clear and refetch.
      setHintState({ loadingStage: null, hints: null, error: "" });
      setAnswerKeyState((current) => ({ ...current, error: "" }));
    }

    try {
      const response = await (action === "Run" ? runCode({
        problem_id: selectedProblem.problem_id,
        code: currentCode,
        timed_mode: false,
      }) : submitCode({
        problem_id: selectedProblem.problem_id,
        code: currentCode,
        timed_mode: false,
      }));
      setSubmissionState({ loadingAction: null, result: response, error: "" });
      if (action === "Submit") {
        await refreshHintState(selectedProblem.problem_id);
        await refreshAnswerKeyState(selectedProblem.problem_id);
      }
    } catch (submitError) {
      setSubmissionState({ loadingAction: null, result: null, error: submitError.message });
    }
  }

  async function handleRun() {
    await executeCode("Run");
  }

  async function handleSubmit() {
    await executeCode("Submit");
  }

  async function handleUnlockHint(stage) {
    if (!selectedProblem || !session) {
      return;
    }

    setHintState((current) => ({
      loadingStage: stage,
      hints: current.hints,
      error: "",
    }));

    try {
      const response = await getHints(selectedProblem.problem_id, stage);
      setHintState({ loadingStage: null, hints: response, error: "" });
    } catch (hintError) {
      setHintState((current) => ({
        loadingStage: null,
        hints: current.hints,
        error: hintError.message,
      }));
    }
  }

  async function handleResetProgress() {
    if (!selectedProblem || !session) {
      return;
    }

    try {
      await resetProgress(selectedProblem.problem_id);
      setCodeByProblem((current) => ({
        ...current,
        [selectedProblem.problem_id]: selectedProblem.starter_code || "",
      }));
      setSubmissionState({ loadingAction: null, result: null, error: "" });
      setHintState({
        loadingStage: null,
        hints: {
          problem_id: selectedProblem.problem_id,
          unlocked_stage: 0,
          unlocked_stages: [],
          highlight_stage: null,
          conceptual: null,
          strategic: null,
          syntactic: null,
        },
        error: "",
      });
      setAnswerKeyState({ unlocked: false, loading: false, content: null, error: "" });
    } catch (resetError) {
      setHintState((current) => ({
        loadingStage: null,
        hints: current.hints,
        error: resetError.message,
      }));
    }
  }

  async function handleViewAnswerKey() {
    if (!selectedProblem || !session) {
      return;
    }

    setAnswerKeyState((current) => ({
      ...current,
      loading: true,
      error: "",
    }));

    try {
      const response = await getAnswerKey(selectedProblem.problem_id);
      setAnswerKeyState({
        unlocked: response.unlocked,
        loading: false,
        content: response.unlocked ? response : null,
        error: "",
      });
    } catch (answerKeyError) {
      setAnswerKeyState((current) => ({
        ...current,
        loading: false,
        error: answerKeyError.message,
      }));
    }
  }

  function handleSelectProblem(problemId) {
    setSelectedProblemId(problemId);
    setSubmissionState({ loadingAction: null, result: null, error: "" });
    setHintState({ loadingStage: null, hints: null, error: "" });
    setAnswerKeyState({ unlocked: false, loading: false, content: null, error: "" });
  }

  function handleDifficultyChange(difficulty) {
    setSelectedDifficulty(difficulty);
    setSubmissionState({ loadingAction: null, result: null, error: "" });
    setHintState({ loadingStage: null, hints: null, error: "" });
    setAnswerKeyState({ unlocked: false, loading: false, content: null, error: "" });
  }

  async function handleLogout() {
    try {
      await logout();
    } catch (_error) {
      // Clearing client state is still correct even if the cookie is already gone.
    }
    setSession(null);
    setProblems([]);
    setSelectedProblemId("");
    setCodeByProblem({});
    setSubmissionState({ loadingAction: null, result: null, error: "" });
    setHintState({ loadingStage: null, hints: null, error: "" });
    setAnswerKeyState({ unlocked: false, loading: false, content: null, error: "" });
    setAuthError("");
  }

  if (sessionLoading) {
    return (
      <main className="app-shell auth-shell">
        <section className="auth-card">
          <p className="eyebrow">CodeSoCrat</p>
          <h1>Restoring session</h1>
          <p className="lede">Checking your secure session cookie.</p>
        </section>
      </main>
    );
  }

  if (!session) {
    return (
      <main className="app-shell auth-shell">
        <AuthPanel onLogin={handleLogin} onRegister={handleRegister} loading={authLoading} error={authError} />
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
        <ProblemList
          problems={problems}
          selectedDifficulty={selectedDifficulty}
          selectedProblemId={selectedProblemId}
          onDifficultyChange={handleDifficultyChange}
          onSelect={handleSelectProblem}
        />
        <SubmissionPanel
          problem={selectedProblem}
          code={currentCode}
          setCode={updateCode}
          onRun={handleRun}
          onSubmit={handleSubmit}
          onResetProgress={handleResetProgress}
          submissionState={submissionState}
          hintState={hintState}
          answerKeyState={answerKeyState}
          onViewAnswerKey={handleViewAnswerKey}
          onUnlockHint={handleUnlockHint}
        />
      </section>

      {session.role === "Author" ? <AuthorPanel /> : null}
    </main>
  );
}
