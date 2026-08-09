import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { authApi } from "@/lib/api";
import { UNAUTHORIZED_EVENT, clearToken, getToken, setToken } from "@/lib/token";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const queryClient = useQueryClient();
  const [token, setTokenState] = useState(() => getToken());

  /**
   * The current user is server state like anything else, so it goes through
   * TanStack Query rather than being fetched by hand in an effect. The token
   * is the query key: signing in as someone else refetches automatically.
   */
  const {
    data: user,
    isPending,
    isError,
  } = useQuery({
    queryKey: ["auth", "me", token],
    queryFn: authApi.me,
    enabled: Boolean(token),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  const logout = useCallback(() => {
    clearToken();
    setTokenState(null);
    // Drop every cached response — the next user must not see the last one's
    // reports sitting in the cache while their own request is in flight.
    queryClient.clear();
  }, [queryClient]);

  const login = useCallback(async ({ email, password }) => {
    const { access_token } = await authApi.login({ email, password });
    setToken(access_token);
    setTokenState(access_token);
    return access_token;
  }, []);

  // A 401 on any request means the session is over. apiClient has already
  // cleared the token; this drops the user so ProtectedRoute can redirect.
  useEffect(() => {
    const handle = () => {
      setTokenState(null);
      queryClient.clear();
    };
    window.addEventListener(UNAUTHORIZED_EVENT, handle);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, handle);
  }, [queryClient]);

  const value = useMemo(
    () => ({
      user: user ?? null,
      token,
      // Only "resolving" while a token is actually being exchanged for a user.
      // Without the token check this stays true forever on the login page,
      // because a disabled query never leaves the pending state.
      isResolving: Boolean(token) && isPending,
      isAuthenticated: Boolean(token) && Boolean(user) && !isError,
      isAdmin: user?.role?.toLowerCase() === "admin",
      login,
      logout,
    }),
    [user, token, isPending, isError, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>");
  return context;
}
