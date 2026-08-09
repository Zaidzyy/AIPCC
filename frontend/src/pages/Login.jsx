import { ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { AmbientVideo } from "@/components/common/AmbientVideo";
import {
  Button,
  Field,
  Input,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";
import { useAuth } from "@/context/AuthContext";
import { authApi } from "@/lib/api";
import { errorMessage } from "@/lib/apiClient";

export function Login() {
  const { isAuthenticated, isResolving } = useAuth();
  const location = useLocation();

  if (isResolving) return null;
  if (isAuthenticated) {
    return <Navigate to={location.state?.from?.pathname ?? "/dashboard"} replace />;
  }

  return (
    <div className="relative flex min-h-dvh items-center justify-center overflow-hidden px-4 py-12">
      {/* The only motion on this screen — manifest rule 1. The mobile cut is
          vertical and carries a dark top third, so the panel sits below it. */}
      <AmbientVideo clip="hero-desktop" className="hidden md:block" opacity="opacity-45" />
      <AmbientVideo clip="hero-mobile" className="md:hidden" opacity="opacity-45" />

      <div className="relative w-full max-w-sm animate-rise">
        <div className="mb-8 flex flex-col items-center text-center">
          <ShieldCheck className="mb-4 size-7 text-ink" aria-hidden="true" />
          <h1 className="font-mono text-xl font-bold tracking-[-0.03em] text-ink">AIPCC</h1>
          <p className="eyebrow mt-2">AI-Powered Cybersecurity Co-Pilot</p>
        </div>

        <div className="rounded-lg border border-line-strong bg-surface/85 shadow-pop backdrop-blur-md">
          <Tabs defaultValue="signin">
            <TabsList className="px-2">
              <TabsTrigger value="signin">Sign in</TabsTrigger>
              <TabsTrigger value="register">Create account</TabsTrigger>
            </TabsList>
            <TabsContent value="signin">
              <SignInForm />
            </TabsContent>
            <TabsContent value="register">
              <RegisterForm />
            </TabsContent>
          </Tabs>
        </div>

        <p className="mt-5 text-center text-[0.8125rem] text-ink-faint">
          Seeded demo account:{" "}
          <span className="ident text-ink-dim">admin@aipcc.io / admin</span>
        </p>
      </div>
    </div>
  );
}

function SignInForm() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login({ email, password });
      navigate(location.state?.from?.pathname ?? "/dashboard", { replace: true });
    } catch (caught) {
      // The backend answers identically for an unknown email and a wrong
      // password, on purpose. Do not embellish it into something more specific.
      setError(errorMessage(caught, "Could not sign in."));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4 p-5">
      <Field label="Email" required>
        {(props) => (
          <Input
            {...props}
            type="email"
            autoComplete="email"
            placeholder="analyst@aipcc.io"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
        )}
      </Field>

      <Field label="Password" required error={error}>
        {(props) => (
          <Input
            {...props}
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        )}
      </Field>

      <Button type="submit" variant="primary" className="w-full" loading={submitting}>
        Sign in
      </Button>
    </form>
  );
}

function RegisterForm() {
  const { login } = useAuth();
  const navigate = useNavigate();

  const [form, setForm] = useState({
    first_name: "",
    last_name: "",
    email: "",
    password: "",
  });
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const update = (key) => (event) =>
    setForm((current) => ({ ...current, [key]: event.target.value }));

  async function handleSubmit(event) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await authApi.register(form);
      // Registration always creates an analyst; sign straight in so the new
      // account lands on the dashboard rather than back at an empty form.
      await login({ email: form.email, password: form.password });
      navigate("/dashboard", { replace: true });
    } catch (caught) {
      setError(errorMessage(caught, "Could not create the account."));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4 p-5">
      <div className="grid grid-cols-2 gap-3">
        <Field label="First name" required>
          {(props) => (
            <Input {...props} value={form.first_name} onChange={update("first_name")} required />
          )}
        </Field>
        <Field label="Last name" required>
          {(props) => (
            <Input {...props} value={form.last_name} onChange={update("last_name")} required />
          )}
        </Field>
      </div>

      <Field label="Email" required>
        {(props) => (
          <Input
            {...props}
            type="email"
            autoComplete="email"
            value={form.email}
            onChange={update("email")}
            required
          />
        )}
      </Field>

      <Field
        label="Password"
        required
        hint="At least 8 characters."
        error={error}
      >
        {(props) => (
          <Input
            {...props}
            type="password"
            autoComplete="new-password"
            minLength={8}
            value={form.password}
            onChange={update("password")}
            required
          />
        )}
      </Field>

      <Button type="submit" variant="primary" className="w-full" loading={submitting}>
        Create account
      </Button>
      <p className="text-center text-xs text-ink-faint">
        New accounts are created as analysts.
      </p>
    </form>
  );
}
