import { ShieldCheck, Trash2, UserPlus } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/common/PageHeader";
import {
  Avatar,
  Badge,
  Button,
  Card,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  ErrorState,
  Field,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  SkeletonRows,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  Tooltip,
  useToast,
} from "@/components/ui";
import { useAuth } from "@/context/AuthContext";
import {
  useCreateUser,
  useDeleteUser,
  useSetUserRole,
  useSetUserStatus,
  useUsers,
} from "@/hooks/queries";
import { errorMessage } from "@/lib/apiClient";
import { formatDateTime, formatRelative, fullName, initials } from "@/lib/format";

const ROLES = ["admin", "analyst"];
const STATUSES = ["Active", "Suspended"];

export function Users() {
  const { user: currentUser } = useAuth();
  const query = useUsers();
  const [createOpen, setCreateOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(null);

  return (
    <>
      <PageHeader
        eyebrow="Administration"
        title="Users"
        description="Roles decide what a user can reach. Analysts see only their own documents and reports; admins see everything."
        actions={
          <Button variant="primary" onClick={() => setCreateOpen(true)}>
            <UserPlus />
            Add user
          </Button>
        }
      />

      <Card className="overflow-hidden">
        {query.isError ? (
          <ErrorState error={query.error} title="Could not load users" onRetry={query.refetch} />
        ) : query.isPending ? (
          <SkeletonRows rows={5} columns={4} />
        ) : (
          <Table>
            <THead>
              <TR className="hover:bg-transparent">
                <TH>User</TH>
                <TH className="w-36">Role</TH>
                <TH className="w-36">Status</TH>
                <TH className="hidden w-40 lg:table-cell">Last login</TH>
                <TH className="w-12 text-right">
                  <span className="sr-only">Actions</span>
                </TH>
              </TR>
            </THead>
            <TBody>
              {query.data.map((user) => (
                <UserRow
                  key={user.user_id}
                  user={user}
                  isSelf={user.user_id === currentUser?.user_id}
                  onDelete={() => setPendingDelete(user)}
                />
              ))}
            </TBody>
          </Table>
        )}
      </Card>

      <CreateUserDialog open={createOpen} onOpenChange={setCreateOpen} />
      <DeleteUserDialog user={pendingDelete} onClose={() => setPendingDelete(null)} />
    </>
  );
}

function UserRow({ user, isSelf, onDelete }) {
  const setRole = useSetUserRole();
  const setStatus = useSetUserStatus();
  const { toast } = useToast();

  // The backend refuses these for your own account so the last admin cannot
  // lock everyone out. Disabling them here means the rule is visible rather
  // than only discoverable by triggering a 400.
  const selfLockNote = isSelf ? "You cannot change this on your own account" : null;

  const change = (mutation, label) => async (value) => {
    try {
      await mutation.mutateAsync(
        label === "role" ? { userId: user.user_id, role: value } : { userId: user.user_id, status: value },
      );
      toast({ variant: "success", title: `${label} updated`, description: fullName(user) });
    } catch (error) {
      toast({ variant: "error", title: `Could not update ${label}`, description: errorMessage(error) });
    }
  };

  return (
    <TR>
      <TD className="align-middle">
        <div className="flex items-center gap-3">
          <Avatar initials={initials(user)} size="sm" />
          <div className="min-w-0">
            <p className="flex items-center gap-1.5 font-medium text-ink">
              {fullName(user)}
              {isSelf && <Badge variant="outline">You</Badge>}
            </p>
            <p className="ident text-xs">{user.email}</p>
          </div>
        </div>
      </TD>

      <TD className="align-middle">
        <Tooltip content={selfLockNote}>
          <span className="block">
            <Select
              value={user.role.toLowerCase()}
              onValueChange={change(setRole, "role")}
              disabled={isSelf || setRole.isPending}
            >
              <SelectTrigger className="h-8 text-[0.8125rem]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ROLES.map((role) => (
                  <SelectItem key={role} value={role}>
                    {role === "admin" ? "Admin" : "Analyst"}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </span>
        </Tooltip>
      </TD>

      <TD className="align-middle">
        <Tooltip content={selfLockNote}>
          <span className="block">
            <Select
              value={STATUSES.find((s) => s.toLowerCase() === user.status.toLowerCase()) ?? user.status}
              onValueChange={change(setStatus, "status")}
              disabled={isSelf || setStatus.isPending}
            >
              <SelectTrigger className="h-8 text-[0.8125rem]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {STATUSES.map((status) => (
                  <SelectItem key={status} value={status}>
                    {status}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </span>
        </Tooltip>
      </TD>

      <TD className="hidden align-middle lg:table-cell">
        <Tooltip content={user.last_login_at ? formatDateTime(user.last_login_at) : null}>
          <span className="text-[0.8125rem]">
            {user.last_login_at ? formatRelative(user.last_login_at) : "Never"}
          </span>
        </Tooltip>
      </TD>

      <TD className="align-middle text-right">
        <Tooltip content={selfLockNote}>
          <span className="inline-block">
            <Button
              variant="ghost"
              size="icon-sm"
              disabled={isSelf}
              onClick={onDelete}
              aria-label={`Delete ${fullName(user)}`}
            >
              <Trash2 />
            </Button>
          </span>
        </Tooltip>
      </TD>
    </TR>
  );
}

function CreateUserDialog({ open, onOpenChange }) {
  const create = useCreateUser();
  const { toast } = useToast();

  const empty = {
    first_name: "",
    last_name: "",
    email: "",
    password: "",
    role: "analyst",
  };
  const [form, setForm] = useState(empty);
  const [error, setError] = useState(null);

  const update = (key) => (event) =>
    setForm((current) => ({ ...current, [key]: event.target.value }));

  async function handleSubmit(event) {
    event.preventDefault();
    setError(null);
    try {
      const created = await create.mutateAsync(form);
      toast({ variant: "success", title: "User created", description: created.email });
      setForm(empty);
      onOpenChange(false);
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>Add a user</DialogTitle>
            <DialogDescription>
              This is the only path that can set a role directly. Self-registration always
              creates an analyst.
            </DialogDescription>
          </DialogHeader>

          <DialogBody className="space-y-4">
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
                <Input {...props} type="email" value={form.email} onChange={update("email")} required />
              )}
            </Field>

            <Field label="Password" required hint="At least 8 characters." error={error}>
              {(props) => (
                <Input
                  {...props}
                  type="password"
                  minLength={8}
                  value={form.password}
                  onChange={update("password")}
                  required
                />
              )}
            </Field>

            <div className="space-y-1.5">
              <p className="eyebrow">Role</p>
              <Select
                value={form.role}
                onValueChange={(role) => setForm((current) => ({ ...current, role }))}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ROLES.map((role) => (
                    <SelectItem key={role} value={role}>
                      {role === "admin" ? "Admin — full access" : "Analyst — own data only"}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </DialogBody>

          <DialogFooter>
            <Button type="button" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" loading={create.isPending}>
              Create user
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function DeleteUserDialog({ user, onClose }) {
  const remove = useDeleteUser();
  const { toast } = useToast();

  async function confirm() {
    try {
      await remove.mutateAsync(user.user_id);
      toast({ variant: "success", title: "User deleted", description: user.email });
      onClose();
    } catch (error) {
      toast({ variant: "error", title: "Delete failed", description: errorMessage(error) });
    }
  }

  return (
    <Dialog open={Boolean(user)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Delete this user?</DialogTitle>
          <DialogDescription>
            {user?.email} loses access immediately. Their documents and reports are deleted with
            the account.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="danger" loading={remove.isPending} onClick={confirm}>
            <ShieldCheck />
            Delete user
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
