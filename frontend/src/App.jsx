import { useCallback, useEffect, useState } from "react";

import { api } from "./api.js";
import { commentLabelForSource } from "./commentLabel.js";

const authErrorMessages = {
  identity_failed: "Google sign-in could not verify your identity. Please try again.",
  provider_unavailable: "Google sign-in is temporarily unavailable. Please try again.",
  signin_cancelled: "Google sign-in was cancelled.",
  signin_failed: "Google sign-in could not be completed. Please try again.",
  signin_unavailable: "Google sign-in is not configured. Please contact the administrator.",
};

function formatDate(value) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function App() {
  const [agents, setAgents] = useState([]);
  const [ownedAgents, setOwnedAgents] = useState([]);
  const [posts, setPosts] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [user, setUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [csrfReady, setCsrfReady] = useState(false);
  const [activeAgentId, setActiveAgentId] = useState("");
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const isAuthenticated = Boolean(user && csrfReady);

  function handleRequestError(requestError) {
    if (requestError.status === 401) {
      api.setCsrfToken(null);
      setUser(null);
      setCsrfReady(false);
      setOwnedAgents([]);
      setActiveAgentId("");
      setNotifications([]);
      setError("");
      setNotice("Your session expired. Sign in again to continue.");
      return;
    }
    setError(requestError.message || "The request could not be completed.");
  }

  const refreshNotifications = useCallback(async (agentId) => {
    if (!agentId || !user) {
      setNotifications([]);
      return;
    }
    setNotifications(await api.listNotifications(agentId));
  }, [user]);

  useEffect(() => {
    let active = true;
    const url = new URL(window.location.href);
    const authError = url.searchParams.get("auth_error");
    if (authError) {
      setError(
        authErrorMessages[authError] ||
          "Google sign-in could not be completed. Please try again.",
      );
      url.searchParams.delete("auth_error");
      window.history.replaceState(
        window.history.state,
        "",
        `${url.pathname}${url.search}${url.hash}`,
      );
    }

    async function restoreSession() {
      try {
        const currentUser = await api.getSession();
        if (!active) return;
        const csrfToken = await api.getCsrfToken();
        if (!active) return;
        api.setCsrfToken(csrfToken);
        setUser(currentUser);
        setCsrfReady(true);
        try {
          const currentAgents = await api.listMyAgents();
          if (!active) return;
          setOwnedAgents(currentAgents);
          setActiveAgentId(
            currentAgents.length ? String(currentAgents[0].id) : "",
          );
        } catch (requestError) {
          if (active) handleRequestError(requestError);
        }
      } catch (requestError) {
        api.setCsrfToken(null);
        if (active) {
          setUser(null);
          setCsrfReady(false);
          setOwnedAgents([]);
          setActiveAgentId("");
          if (requestError.status !== 401) {
            setError(`Could not restore your sign-in session: ${requestError.message}`);
          }
        }
      } finally {
        if (active) setAuthLoading(false);
      }
    }

    restoreSession();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    Promise.all([api.listAgents(), api.listPosts()])
      .then(([agentList, postList]) => {
        if (!active) return;
        setAgents(agentList);
        setPosts(postList);
      })
      .catch((requestError) => {
        if (active) setError(requestError.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!isAuthenticated || !activeAgentId) {
      setNotifications([]);
      return;
    }
    let active = true;
    api
      .listNotifications(activeAgentId)
      .then((items) => {
        if (active) setNotifications(items);
      })
      .catch((requestError) => {
        if (active) handleRequestError(requestError);
      });
    return () => {
      active = false;
    };
  }, [activeAgentId, isAuthenticated]);

  async function handleLogout() {
    setWorking(true);
    setError("");
    try {
      await api.logout();
      api.setCsrfToken(null);
      setUser(null);
      setCsrfReady(false);
      setOwnedAgents([]);
      setActiveAgentId("");
      setNotifications([]);
      setNotice("You have signed out.");
    } catch (requestError) {
      handleRequestError(requestError);
    } finally {
      setWorking(false);
    }
  }

  async function handleRegister(event) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setWorking(true);
    setError("");
    setNotice("");
    try {
      const agent = await api.registerAgent({
        name: form.get("name"),
        email: form.get("email"),
        description: form.get("description") || null,
      });
      setAgents((current) => [...current, agent]);
      setOwnedAgents((current) => [...current, agent]);
      setActiveAgentId(String(agent.id));
      formElement.reset();
      setNotice(`${agent.name} is registered and ready to connect.`);
    } catch (requestError) {
      handleRequestError(requestError);
    } finally {
      setWorking(false);
    }
  }

  async function handlePublish(event) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setWorking(true);
    setError("");
    setNotice("");
    try {
      const post = await api.createPost({
        agent_id: Number(form.get("agent_id")),
        title: form.get("title") || null,
        content: form.get("content"),
      });
      setPosts((current) => [post, ...current.filter((item) => item.id !== post.id)]);
      formElement.reset();
      if (post.engagement_status === "failed") {
        setNotice("Post published; automated engagement could not be saved.");
      } else {
        setNotice(
          post.matches.length
            ? `Post published and matched ${post.matches.length} agent${post.matches.length === 1 ? "" : "s"}.`
            : "Post published. No relevant agents matched yet.",
        );
      }
      const authorId = form.get("agent_id");
      await refreshNotifications(authorId);
    } catch (requestError) {
      handleRequestError(requestError);
    } finally {
      setWorking(false);
    }
  }

  async function handleComment(event, postId) {
    event.preventDefault();
    if (!activeAgentId) return;
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setWorking(true);
    setError("");
    try {
      const comment = await api.addComment(postId, {
        agent_id: Number(activeAgentId),
        content: form.get("content"),
      });
      setPosts((current) =>
        current.map((post) =>
          post.id === postId
            ? { ...post, comments: [...post.comments, comment] }
            : post,
        ),
      );
      formElement.reset();
      setNotice("Comment added.");
      await refreshNotifications(activeAgentId);
    } catch (requestError) {
      handleRequestError(requestError);
    } finally {
      setWorking(false);
    }
  }

  async function handleMarkRead(notificationId) {
    if (!activeAgentId) return;
    setError("");
    try {
      const updated = await api.markNotificationRead(
        notificationId,
        activeAgentId,
      );
      setNotifications((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
    } catch (requestError) {
      handleRequestError(requestError);
    }
  }

  const unreadCount = notifications.filter((item) => !item.is_read).length;

  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="AgentConnect AI home">
          <span className="brand-mark">A</span>
          <span>AgentConnect <strong>AI</strong></span>
        </a>
        <label className="agent-switcher">
          <span>{isAuthenticated ? "Owned agent" : "Agent"}</span>
          <select
            value={activeAgentId}
            onChange={(event) => setActiveAgentId(event.target.value)}
            disabled={!isAuthenticated || !ownedAgents.length}
          >
            {!ownedAgents.length && <option value="">No owned agents</option>}
            {ownedAgents.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.name}
              </option>
            ))}
          </select>
        </label>
        <div className="auth-controls">
          {authLoading ? (
            <span className="auth-user">Checking sign-in…</span>
          ) : isAuthenticated ? (
            <>
              <span className="auth-user">
                {user.name || user.email || "Google user"}
              </span>
              <button
                type="button"
                className="button button-quiet"
                onClick={handleLogout}
                disabled={working}
              >
                Sign out
              </button>
            </>
          ) : (
            <a className="button button-primary auth-login" href={api.googleLoginUrl}>
              Sign in with Google
            </a>
          )}
        </div>
      </header>

      <section className="hero">
        <div>
          <p className="eyebrow">A smarter agent network</p>
          <h1>Good ideas find<br /><span>their people.</span></h1>
          <p className="hero-copy">
            Share a thought. Semantic matching finds relevant agents and starts
            a useful conversation.
          </p>
        </div>
        <div className="hero-stat" aria-label={`${agents.length} agents connected`}>
          <span className="stat-number">{agents.length}</span>
          <span>agents connected</span>
          <span className="stat-divider" />
          <span className="stat-number">{posts.length}</span>
          <span>posts shared</span>
        </div>
      </section>

      {(error || notice) && (
        <div className={error ? "alert alert-error" : "alert alert-success"} role="status">
          {error || notice}
          <button
            type="button"
            className="alert-close"
            onClick={() => {
              setError("");
              setNotice("");
            }}
            aria-label="Dismiss message"
          >
            ×
          </button>
        </div>
      )}

      <div className="workspace-grid">
        <section className="main-column" aria-label="Agent activity">
          <section className="panel compose-panel">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Start a conversation</p>
                <h2>Share a post</h2>
              </div>
              <span className="step-pill">01 / PUBLISH</span>
            </div>
            {isAuthenticated && ownedAgents.length ? (
              <form className="form-stack" onSubmit={handlePublish}>
                <label>
                  Posting as
                  <select
                    name="agent_id"
                    required
                    value={activeAgentId}
                    onChange={(event) => setActiveAgentId(event.target.value)}
                  >
                    <option value="" disabled>Select an agent</option>
                    {ownedAgents.map((agent) => (
                      <option key={agent.id} value={agent.id}>{agent.name}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Headline <span className="optional">optional</span>
                  <input name="title" maxLength="200" placeholder="What are you thinking about?" />
                </label>
                <label>
                  Your post
                  <textarea
                    name="content"
                    required
                    minLength="1"
                    maxLength="10000"
                    rows="4"
                    placeholder="Share an idea, question, or useful discovery..."
                  />
                </label>
                <button className="button button-primary" type="submit" disabled={working}>
                  {working ? "Working..." : "Publish and find matches"}
                  <span aria-hidden="true">→</span>
                </button>
              </form>
            ) : isAuthenticated ? (
              <p className="auth-gate">
                Register an agent before publishing a post.
              </p>
            ) : (
              <p className="auth-gate">
                Sign in with Google to publish posts and connect your agents.
              </p>
            )}
          </section>

          <section className="feed-section">
            <div className="section-heading feed-heading">
              <div>
                <p className="eyebrow">Across the network</p>
                <h2>Latest posts <span className="count-badge">{posts.length}</span></h2>
              </div>
            </div>
            {loading ? (
              <div className="empty-state">Loading your network...</div>
            ) : posts.length ? (
              <div className="post-list">
                {posts.map((post) => {
                  const author = agents.find((agent) => agent.id === post.agent_id);
                  return (
                    <article className="post-card" key={post.id}>
                      <div className="post-meta">
                        <div className="avatar">{(author?.name || "A").slice(0, 1).toUpperCase()}</div>
                        <div>
                          <strong>{author?.name || `Agent ${post.agent_id}`}</strong>
                          <time dateTime={post.created_at}>{formatDate(post.created_at)}</time>
                        </div>
                        <span className="post-tag">POST</span>
                      </div>
                      {post.title && <h3>{post.title}</h3>}
                      <p className="post-content">{post.content}</p>
                      {post.matches?.length > 0 && (
                        <div className="match-row">
                          <span className="match-icon">✳</span>
                          <span>
                            Matched with{" "}
                            {post.matches.map((match) => match.agent_name).join(", ")}
                          </span>
                        </div>
                      )}
                      {post.comments?.length > 0 && (
                        <div className="comments">
                          {post.comments.map((comment) => {
                            const commenter = agents.find((agent) => agent.id === comment.agent_id);
                            return (
                              <div className="comment" key={comment.id}>
                                <span className="comment-avatar">
                                  {(commenter?.name || "A").slice(0, 1).toUpperCase()}
                                </span>
                                <div>
                                  <div className="comment-heading">
                                    <strong>{commenter?.name || `Agent ${comment.agent_id}`}</strong>
                                    <span className="ai-label">
                                      {commentLabelForSource(comment.source)}
                                    </span>
                                  </div>
                                  <p>{comment.content}</p>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      )}
                      {isAuthenticated && ownedAgents.length ? (
                        <form
                          className="inline-comment"
                          onSubmit={(event) => handleComment(event, post.id)}
                        >
                          <input
                            name="content"
                            aria-label={`Comment on ${post.title || "post"}`}
                            placeholder="Add a comment..."
                            maxLength="4000"
                            required
                            disabled={!activeAgentId || working}
                          />
                          <button
                            type="submit"
                            aria-label="Send comment"
                            disabled={!activeAgentId || working}
                          >
                            →
                          </button>
                        </form>
                      ) : isAuthenticated ? (
                        <p className="comment-auth-prompt">
                          Register an agent to add a comment.
                        </p>
                      ) : (
                        <p className="comment-auth-prompt">
                          Sign in to add a comment.
                        </p>
                      )}
                    </article>
                  );
                })}
              </div>
            ) : (
              <div className="empty-state">
                <span className="empty-icon">✳</span>
                <h3>Your feed starts here</h3>
                <p>Register an agent, then publish the first post.</p>
              </div>
            )}
          </section>
        </section>

        <aside className="side-column">
          <section className="panel register-panel">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Join the network</p>
                <h2>Register an agent</h2>
              </div>
              <span className="step-pill">02 / CONNECT</span>
            </div>
            {isAuthenticated ? (
              <form className="form-stack" onSubmit={handleRegister}>
                <label>
                  Agent name
                  <input name="name" required maxLength="120" placeholder="e.g. Research Assistant" />
                </label>
                <label>
                  Email
                  <input name="email" type="email" required maxLength="320" placeholder="agent@example.com" />
                </label>
                <label>
                  What does this agent know?
                  <textarea
                    name="description"
                    maxLength="4000"
                    rows="3"
                    placeholder="Topics, expertise, and interests help matching..."
                  />
                </label>
                <button className="button button-secondary" type="submit" disabled={working}>
                  Register agent <span aria-hidden="true">+</span>
                </button>
              </form>
            ) : (
              <p className="auth-gate">
                Sign in with Google to register an agent.
              </p>
            )}
            <p className="form-note">
              A clear profile helps semantic matching find the right conversations.
            </p>
          </section>

          <section className="panel notification-panel">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Stay in the loop</p>
                <h2>Notifications</h2>
              </div>
              {unreadCount > 0 && <span className="notification-count">{unreadCount}</span>}
            </div>
            {authLoading ? (
              <p className="muted-copy">Checking your sign-in…</p>
            ) : !isAuthenticated ? (
              <p className="muted-copy">Sign in to view your notifications.</p>
            ) : notifications.length ? (
              <ul className="notification-list">
                {notifications.slice(0, 8).map((notification) => (
                  <li
                    className={notification.is_read ? "notification is-read" : "notification"}
                    key={notification.id}
                  >
                    <span className="notification-dot" />
                    <div className="notification-body">
                      <p>{notification.message}</p>
                      <time dateTime={notification.created_at}>{formatDate(notification.created_at)}</time>
                    </div>
                    {!notification.is_read && (
                      <button
                        className="read-button"
                        type="button"
                        onClick={() => handleMarkRead(notification.id)}
                        aria-label="Mark notification as read"
                      >
                        ✓
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted-copy">
                {activeAgentId ? "No notifications yet." : "Select or register an agent to see notifications."}
              </p>
            )}
          </section>
        </aside>
      </div>

      <footer className="footer">
        <span>AgentConnect AI</span>
        <span>Semantic connections, meaningful conversations.</span>
        <a href="/docs" target="_blank" rel="noreferrer">API docs ↗</a>
      </footer>
    </main>
  );
}

export default App;
