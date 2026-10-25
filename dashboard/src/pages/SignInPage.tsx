import { useState } from "react";
import { ActionForm } from "../components/ActionForm";
import { signIn } from "../supabase";

export function SignInPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  return (
    <main className="sign-in">
      <section className="panel sign-in-panel" aria-labelledby="sign-in-title">
        <p className="brand">
          UnderCover <span className="tagline">claims platform</span>
        </p>
        <h1 id="sign-in-title">Sign in</h1>
        <p className="muted">
          For UnderCover's claims handlers. Ask a senior handler if you need an
          account.
        </p>
        <ActionForm
          label="Sign in"
          className="stacked-form"
          ready={email !== "" && password !== ""}
          action={() => signIn(email, password)}
        >
          <label>
            Email address
            <input
              type="email"
              autoComplete="username"
              value={email}
              onChange={(event) => {
                setEmail(event.target.value);
              }}
            />
          </label>
          <label>
            Password
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => {
                setPassword(event.target.value);
              }}
            />
          </label>
        </ActionForm>
      </section>
    </main>
  );
}
