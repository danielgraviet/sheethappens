import { useEffect, useState } from 'react';

const OAUTH_ERRORS = {
  oauth_denied: 'Google sign-in was cancelled.',
  invalid_state: 'Security check failed. Please try again.',
  token_exchange: 'Could not complete Google sign-in.',
  userinfo: 'Could not read your Google profile.',
};

function sheetUrl(spreadsheetId) {
  return spreadsheetId
    ? `https://docs.google.com/spreadsheets/d/${spreadsheetId}`
    : '#';
}

async function getJson(url, options = {}) {
  const response = await fetch(url, {
    credentials: 'include',
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  return { response, data };
}

function StepNumber({ done, value }) {
  return <div className={`step-num${done ? ' done' : ''}`}>{done ? '✓' : value}</div>;
}

function Card({ children, id }) {
  return (
    <section className="card" id={id}>
      {children}
    </section>
  );
}

export function App() {
  const [me, setMe] = useState({ authenticated: false });
  const [loading, setLoading] = useState(true);
  const [canvasForm, setCanvasForm] = useState({ canvas_domain: '', canvas_token: '' });
  const [canvasError, setCanvasError] = useState('');
  const [isSavingCanvas, setIsSavingCanvas] = useState(false);
  const [isEditingCanvas, setIsEditingCanvas] = useState(false);
  const [tools, setTools] = useState({ gas: 'Loading...', ls: '' });
  const [copyState, setCopyState] = useState('idle');
  const [lsCopyState, setLsCopyState] = useState('idle');

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const oauthError = params.get('error');
    if (oauthError) {
      window.alert(OAUTH_ERRORS[oauthError] || 'Something went wrong. Please try again.');
      window.history.replaceState({}, '', '/setup');
    }
  }, []);

  useEffect(() => {
    let active = true;

    async function loadMe() {
      setLoading(true);
      try {
        const { data } = await getJson('/api/me');
        if (!active) {
          return;
        }
        setMe(data);
        setCanvasForm((current) => ({
          ...current,
          canvas_domain: data.canvas_domain || current.canvas_domain,
        }));
      } catch {
        if (!active) {
          return;
        }
        setMe({ authenticated: false });
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    loadMe();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;

    async function loadTools() {
      if (!me.google_connected || !me.canvas_connected) {
        return;
      }

      try {
        const [gasResult, lsResult] = await Promise.all([
          getJson('/api/bookmarklet/gas'),
          getJson('/api/bookmarklet/ls'),
        ]);

        if (!active) {
          return;
        }

        setTools({
          gas: gasResult.data.script || '',
          ls: lsResult.data.js || '',
        });
      } catch {
        if (active) {
          setTools({
            gas: 'Unable to load your setup tools right now.',
            ls: '',
          });
        }
      }
    }

    loadTools();
    return () => {
      active = false;
    };
  }, [me.google_connected, me.canvas_connected]);

  async function saveCanvas(event) {
    event.preventDefault();
    setCanvasError('');

    const domain = canvasForm.canvas_domain.trim();
    const token = canvasForm.canvas_token.trim();

    if (!domain || !token) {
      setCanvasError('Please enter both domain and token.');
      return;
    }

    setIsSavingCanvas(true);
    try {
      const { response, data } = await getJson('/api/setup/canvas', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          canvas_domain: domain,
          canvas_token: token,
        }),
      });

      if (!response.ok) {
        setCanvasError(data.detail || 'Failed to save. Check your token.');
        return;
      }

      setMe((current) => ({
        ...current,
        canvas_connected: true,
        canvas_domain: domain,
      }));
      setCanvasForm((current) => ({ ...current, canvas_token: '' }));
      setIsEditingCanvas(false);
    } catch {
      setCanvasError('Network error. Try again.');
    } finally {
      setIsSavingCanvas(false);
    }
  }

  async function copyGas() {
    try {
      await navigator.clipboard.writeText(tools.gas);
      setCopyState('copied');
      window.setTimeout(() => setCopyState('idle'), 2000);
    } catch {
      setCopyState('error');
      window.setTimeout(() => setCopyState('idle'), 2000);
    }
  }

  async function copyLs() {
    try {
      await navigator.clipboard.writeText(tools.ls);
      setLsCopyState('copied');
      window.setTimeout(() => setLsCopyState('idle'), 2000);
    } catch {
      setLsCopyState('error');
      window.setTimeout(() => setLsCopyState('idle'), 2000);
    }
  }

  const googleDone = Boolean(me.google_connected);
  const canvasDone = Boolean(me.canvas_connected);
  const showCanvasForm = !canvasDone || isEditingCanvas;
  const setupReady = googleDone && canvasDone;

  return (
    <div className="setup-page">
      <header className="hero">
        <div className="hero-shell">
          <p className="eyebrow">Setup</p>
          <h1>Connect OhSheet to the tools your workflow already uses.</h1>
          <p className="lede">
            Sign in with Google, store your Canvas token securely, then install the sync tools
            that keep your spreadsheet current.
          </p>
        </div>
      </header>

      <main className="main-shell">
        {loading ? <div className="loading">Loading your setup...</div> : null}

        <Card id="step1">
          <div className="step-header">
            <StepNumber done={googleDone} value="1" />
            <div>
              <h2>Connect Google Sheets</h2>
              <p>We&apos;ll create a sheet and store your assignments there.</p>
            </div>
          </div>

          {!googleDone ? (
            <a href="/auth/google/start" className="btn btn-google">
              <span className="google-mark" aria-hidden="true">
                G
              </span>
              Connect with Google
            </a>
          ) : (
            <div className="connected-row">
              <span className="connected-badge">
                Connected as {me.google_email || me.email || 'your Google account'}
              </span>
              {me.spreadsheet_id ? (
                <a
                  className="text-link"
                  href={sheetUrl(me.spreadsheet_id)}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open your sheet
                </a>
              ) : null}
            </div>
          )}
        </Card>

        <Card id="step2">
          <div className="step-header">
            <StepNumber done={canvasDone} value="2" />
            <div>
              <h2>Enter Canvas API Token</h2>
              <p>Your token is stored encrypted and only used to fetch assignments.</p>
            </div>
          </div>

          {showCanvasForm ? (
            <form className="stack" onSubmit={saveCanvas}>
              <label className="field">
                <span>Canvas Domain</span>
                <input
                  type="text"
                  value={canvasForm.canvas_domain}
                  onChange={(event) =>
                    setCanvasForm((current) => ({
                      ...current,
                      canvas_domain: event.target.value,
                    }))
                  }
                  placeholder="byu.instructure.com"
                />
                <small>Your school&apos;s Canvas URL, for example `byu.instructure.com`.</small>
              </label>

              <label className="field">
                <span>Canvas API Token</span>
                <input
                  type="password"
                  value={canvasForm.canvas_token}
                  onChange={(event) =>
                    setCanvasForm((current) => ({
                      ...current,
                      canvas_token: event.target.value,
                    }))
                  }
                  placeholder="Paste your token here"
                />
                <small>Canvas path: Account {'>'} Settings {'>'} Approved Integrations {'>'} New Access Token.</small>
              </label>

              <div className="actions">
                <button className="btn btn-primary" type="submit" disabled={isSavingCanvas}>
                  {isSavingCanvas ? 'Saving...' : 'Save Canvas Settings'}
                </button>
                {canvasDone ? (
                  <button
                    className="btn btn-secondary"
                    type="button"
                    onClick={() => setIsEditingCanvas(false)}
                  >
                    Cancel
                  </button>
                ) : null}
              </div>

              {canvasError ? <p className="error">{canvasError}</p> : null}
            </form>
          ) : (
            <div className="connected-row">
              <div className="connected-copy">
                <span className="connected-badge">Canvas connected</span>
                <span className="muted">{me.canvas_domain}</span>
              </div>
              <button className="btn btn-secondary" type="button" onClick={() => setIsEditingCanvas(true)}>
                Change
              </button>
            </div>
          )}
        </Card>

        <Card id="step3">
          <div className="step-header">
            <StepNumber done={setupReady} value="3" />
            <div>
              <h2>Install Your Sync Tools</h2>
              <p>Paste one script into Google Sheets and drag one bookmarklet into your browser.</p>
            </div>
          </div>

          {!setupReady ? (
            <p className="muted">Complete steps 1 and 2 first.</p>
          ) : (
            <div className="tool-grid">
              <article className="tool-card">
                <h3>Canvas Sync</h3>
                <p>Install this Apps Script to add an OhSheet menu directly inside your spreadsheet.</p>
                <pre className="code-block">{tools.gas}</pre>
                <div className="actions">
                  <button className="btn btn-primary" type="button" onClick={copyGas}>
                    {copyState === 'copied'
                      ? 'Copied'
                      : copyState === 'error'
                        ? 'Copy failed'
                        : 'Copy Script'}
                  </button>
                </div>
                <div className="info-panel">
                  <p>Open your sheet, go to Extensions {'>'} Apps Script, replace the code, save, then reload the sheet.</p>
                  {me.spreadsheet_id ? (
                    <a
                      className="text-link"
                      href={sheetUrl(me.spreadsheet_id)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open your OhSheet spreadsheet
                    </a>
                  ) : null}
                </div>
              </article>

              <article className="tool-card">
                <h3>Learning Suite Sync</h3>
                <p>Copy this bookmarklet code and save it as a browser bookmark, then click it from a Learning Suite course page.</p>
                <pre className="code-block">{tools.ls || 'Loading...'}</pre>
                <div className="actions">
                  <button className="btn btn-primary" type="button" onClick={copyLs} disabled={!tools.ls}>
                    {lsCopyState === 'copied'
                      ? 'Copied'
                      : lsCopyState === 'error'
                        ? 'Copy failed'
                        : 'Copy Bookmarklet'}
                  </button>
                </div>
                <div className="info-panel">
                  <ol>
                    <li>Click <strong>Copy Bookmarklet</strong> above.</li>
                    <li>Right-click your bookmarks bar and choose <strong>Add page</strong> or <strong>Add bookmark</strong>.</li>
                    <li>Set the name to <strong>OhSheet LS</strong> and paste the copied code as the URL.</li>
                    <li>Visit a Learning Suite course page and click the bookmark to sync.</li>
                  </ol>
                </div>
              </article>
            </div>
          )}
        </Card>
      </main>
    </div>
  );
}
