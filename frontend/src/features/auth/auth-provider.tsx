"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, type ReactNode } from "react";

import type { MeResponse } from "@/shared/api/contracts";

import {
  getSession,
  login as loginRequest,
  logout as logoutRequest,
  type LoginInput,
  type SessionReason,
  type SessionSnapshot,
} from "./api";

const sessionQueryKey = ["auth", "session"] as const;

type AuthContextValue = {
  actor: MeResponse | null;
  reason: SessionReason | null;
  isBootstrapping: boolean;
  bootstrapError: Error | null;
  isLoggingIn: boolean;
  isLoggingOut: boolean;
  login: (input: LoginInput) => Promise<MeResponse>;
  logout: () => Promise<void>;
  retrySession: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const sessionQuery = useQuery({
    queryKey: sessionQueryKey,
    queryFn: getSession,
    retry: false,
  });
  const loginMutation = useMutation({
    mutationFn: loginRequest,
    onSuccess: (actor) => {
      queryClient.setQueryData<SessionSnapshot>(sessionQueryKey, {
        actor,
        reason: null,
      });
    },
  });
  const logoutMutation = useMutation({
    mutationFn: logoutRequest,
    onSuccess: () => {
      queryClient.setQueryData<SessionSnapshot>(sessionQueryKey, {
        actor: null,
        reason: "AUTHENTICATION_REQUIRED",
      });
    },
  });

  const value: AuthContextValue = {
    actor: sessionQuery.data?.actor ?? null,
    reason: sessionQuery.data?.reason ?? null,
    isBootstrapping: sessionQuery.isPending,
    bootstrapError: sessionQuery.error,
    isLoggingIn: loginMutation.isPending,
    isLoggingOut: logoutMutation.isPending,
    login: loginMutation.mutateAsync,
    logout: logoutMutation.mutateAsync,
    retrySession: async () => {
      await sessionQuery.refetch();
    },
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (context === null) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return context;
}
