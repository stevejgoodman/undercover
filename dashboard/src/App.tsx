import { Link, NavLink, Route, Routes, useMatch } from "react-router";
import { ClaimPage } from "./pages/ClaimPage";
import { EvaluationPage } from "./pages/EvaluationPage";
import { ImprovementPage } from "./pages/ImprovementPage";
import { ConfigurationPage } from "./pages/ConfigurationPage";
import { QueuePage } from "./pages/QueuePage";
import { ScoreboardPage } from "./pages/ScoreboardPage";
import { SettingsPage } from "./pages/SettingsPage";
import {
  CLAIM_PAGE,
  CONFIGURATION,
  EVALUATION_PAGE,
  IMPROVEMENT,
  QUEUE,
  SCOREBOARD,
  SETTINGS,
} from "./paths";
import { SessionGate } from "./components/SessionGate";
import { useHandler } from "./session";
import { signOut } from "./supabase";

function SignedIn() {
  const handler = useHandler();
  return (
    <div className="signed-in">
      <span>
        <span className="signed-in-name">{handler.name}</span>
        <span className="muted small"> {handler.role}</span>
      </span>
      <button
        type="button"
        className="button secondary"
        onClick={() => {
          void signOut();
        }}
      >
        Sign out
      </button>
    </div>
  );
}

export function App() {
  // A claim's page sits under the queue, as an evaluation's copy's does too.
  const onAClaim = useMatch(CLAIM_PAGE) !== null;
  return (
    <SessionGate>
      <header className="header">
        <Link to={QUEUE} className="brand">
          UnderCover <span className="tagline">claims platform</span>
        </Link>
        <nav className="nav" aria-label="Main">
          <NavLink
            to={QUEUE}
            className={({ isActive }) => (isActive || onAClaim ? "active" : "")}
            end
          >
            Queue
          </NavLink>
          <NavLink to={SCOREBOARD}>Scoreboard</NavLink>
          <NavLink to={CONFIGURATION}>Configuration</NavLink>
          <NavLink to={IMPROVEMENT}>Improvement</NavLink>
          <NavLink to={SETTINGS}>Settings</NavLink>
        </nav>
        <SignedIn />
      </header>
      <main className="page">
        <Routes>
          <Route path={QUEUE} element={<QueuePage />} />
          <Route path={CLAIM_PAGE} element={<ClaimPage />} />
          <Route path={SCOREBOARD} element={<ScoreboardPage />} />
          <Route path={EVALUATION_PAGE} element={<EvaluationPage />} />
          <Route path={CONFIGURATION} element={<ConfigurationPage />} />
          <Route path={IMPROVEMENT} element={<ImprovementPage />} />
          <Route path={SETTINGS} element={<SettingsPage />} />
          <Route path="*" element={<p className="message">Page not found</p>} />
        </Routes>
      </main>
    </SessionGate>
  );
}
