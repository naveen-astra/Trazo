import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, type ReactNode } from "react";

import { getAuthSession, signOut as apiSignOut, UNAUTHORIZED_EVENT } from "../api/runApi";
import LoginPage from "../pages/LoginPage";

const SESSION_KEY = ["auth-session"] as const;

interface AuthContextValue {
  /** True when this deployment requires sign-in (production). */
  authRequired: boolean;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue>({
  authRequired: false,
  signOut: async () => {},
});

export function useAuth(): AuthContextValue {
  return useContext(AuthContext);
}

/** Renders the sign-in page instead of the app until the control plane
 * accepts this browser's session. A development stack with no password
 * configured reports `auth_required: false` and passes straight through. */
export function AuthGate({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const session = useQuery({
    queryKey: SESSION_KEY,
    queryFn: getAuthSession,
    staleTime: 60_000,
    retry: 1,
  });

  // A 401 from any panel means the session ended underneath us (expiry,
  // secret rotation, password change): re-ask rather than show N errors.
  useEffect(() => {
    const onUnauthorized = () => {
      void queryClient.invalidateQueries({ queryKey: SESSION_KEY });
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, [queryClient]);

  // Everything cached except the session itself. Not queryClient.clear():
  // that also removes the session query out from under this component's own
  // observer, which is then never told the session changed and leaves the
  // gate stuck on whichever screen it was showing.
  const dropCachedData = useCallback(() => {
    queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== SESSION_KEY[0] });
  }, [queryClient]);

  const signOut = useCallback(async () => {
    await apiSignOut();
    // Switch to the sign-in page first, then drop every cached response so
    // nothing from the signed-in session remains for the next person.
    await queryClient.invalidateQueries({ queryKey: SESSION_KEY });
    dropCachedData();
  }, [queryClient, dropCachedData]);

  const onSignedIn = useCallback(async () => {
    dropCachedData();
    await queryClient.invalidateQueries({ queryKey: SESSION_KEY });
  }, [queryClient, dropCachedData]);

  if (session.isPending) {
    return <div className="auth-splash" aria-busy="true" />;
  }

  // Control plane unreachable: render the app, whose panels already report
  // their own connection errors, rather than a sign-in form that cannot work.
  if (session.isError) {
    return (
      <AuthContext.Provider value={{ authRequired: false, signOut }}>
        {children}
      </AuthContext.Provider>
    );
  }

  const { auth_required: authRequired, authenticated } = session.data;
  if (authRequired && !authenticated) {
    return <LoginPage onSignedIn={onSignedIn} />;
  }

  return <AuthContext.Provider value={{ authRequired, signOut }}>{children}</AuthContext.Provider>;
}
