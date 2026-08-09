import { useState } from "react";

import { PageHeader } from "@/components/common/PageHeader";
import {
  Avatar,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
  Field,
  Input,
  useToast,
} from "@/components/ui";
import { useAuth } from "@/context/AuthContext";
import { authApi } from "@/lib/api";
import { errorMessage } from "@/lib/apiClient";
import { formatDateTime, fullName, initials, orDash } from "@/lib/format";

export function Profile() {
  const { user } = useAuth();
  if (!user) return null;

  return (
    <>
      <PageHeader eyebrow="Account" title="Profile" />

      <div className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Details</CardTitle>
          </CardHeader>
          <CardBody>
            <div className="mb-6 flex items-center gap-4">
              <Avatar initials={initials(user)} size="lg" />
              <div>
                <p className="font-mono text-base font-medium text-ink">{fullName(user)}</p>
                <p className="ident text-[0.8125rem]">{user.email}</p>
              </div>
            </div>

            <dl className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
              <Row label="Role">
                <Badge>{user.role}</Badge>
              </Row>
              <Row label="Status">
                <Badge variant="outline">{user.status}</Badge>
              </Row>
              <Row label="Organization">{orDash(user.organization)}</Row>
              <Row label="Location">{orDash(user.location)}</Row>
              <Row label="Phone">{orDash(user.phone_number)}</Row>
              <Row label="Multi-factor">{user.mfa ? "Enabled" : "Not enabled"}</Row>
              <Row label="Last login">
                {user.last_login_at ? formatDateTime(user.last_login_at) : "Never"}
              </Row>
              <Row label="Member since">{formatDateTime(user.created_at)}</Row>
              <Row label="User id" className="sm:col-span-2">
                <span className="ident text-xs">{user.user_id}</span>
              </Row>
            </dl>

            <p className="mt-6 border-t border-line pt-4 text-[0.8125rem] text-ink-faint">
              Profile fields are set at account creation. There is no update endpoint yet, so this
              view is read-only rather than a form that silently discards changes.
            </p>
          </CardBody>
        </Card>

        <ChangePassword />
      </div>
    </>
  );
}

function Row({ label, children, className }) {
  return (
    <div className={className}>
      <dt className="eyebrow">{label}</dt>
      <dd className="mt-1 text-sm text-ink-dim">{children}</dd>
    </div>
  );
}

function ChangePassword() {
  const { toast } = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setError(null);

    if (next !== confirm) {
      setError("The new passwords do not match.");
      return;
    }

    setSubmitting(true);
    try {
      await authApi.changePassword({ currentPassword: current, newPassword: next });
      toast({ variant: "success", title: "Password changed" });
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card className="self-start">
      <CardHeader>
        <CardTitle>Change password</CardTitle>
      </CardHeader>
      <CardBody>
        <form onSubmit={handleSubmit} className="space-y-4">
          <Field label="Current password" required>
            {(props) => (
              <Input
                {...props}
                type="password"
                autoComplete="current-password"
                value={current}
                onChange={(event) => setCurrent(event.target.value)}
                required
              />
            )}
          </Field>

          <Field label="New password" required hint="At least 8 characters.">
            {(props) => (
              <Input
                {...props}
                type="password"
                autoComplete="new-password"
                minLength={8}
                value={next}
                onChange={(event) => setNext(event.target.value)}
                required
              />
            )}
          </Field>

          <Field label="Confirm new password" required error={error}>
            {(props) => (
              <Input
                {...props}
                type="password"
                autoComplete="new-password"
                minLength={8}
                value={confirm}
                onChange={(event) => setConfirm(event.target.value)}
                required
              />
            )}
          </Field>

          <Button type="submit" variant="primary" className="w-full" loading={submitting}>
            Change password
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}
