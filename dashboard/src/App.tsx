import { Link, NavLink, Route, Routes } from "react-router";
import { ClaimPage } from "./pages/ClaimPage";
import { EvaluationPage } from "./pages/EvaluationPage";
import { InstructionsPage } from "./pages/InstructionsPage";
import { QueuePage } from "./pages/QueuePage";
import { ScoreboardPage } from "./pages/ScoreboardPage";
import {
  CLAIM_PAGE,
  EVALUATION_PAGE,
  INSTRUCTIONS,
  QUEUE,
  SCOREBOARD,
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
  return (
    <SessionGate>
      <header className="header">
        <Link to={QUEUE} className="brand">
          UnderCover <span className="tagline">claims pilot</span>
        </Link>
        <nav className="nav" aria-label="Main">
          <NavLink to={QUEUE} end>
            Queue
          </NavLink>
          <NavLink to={SCOREBOARD}>Scoreboard</NavLink>
          <NavLink to={INSTRUCTIONS}>Instructions</NavLink>
        </nav>
        <SignedIn />
      </header>
      <main className="page">
        <Routes>
          <Route path={QUEUE} element={<QueuePage />} />
          <Route path={CLAIM_PAGE} element={<ClaimPage />} />
          <Route path={SCOREBOARD} element={<ScoreboardPage />} />
          <Route path={EVALUATION_PAGE} element={<EvaluationPage />} />
          <Route path={INSTRUCTIONS} element={<InstructionsPage />} />
          <Route path="*" element={<p className="message">Page not found</p>} />
        </Routes>
      </main>
    </SessionGate>
  );
}
