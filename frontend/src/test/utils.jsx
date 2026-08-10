import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { ToastProvider, TooltipProvider } from "@/components/ui";
import { AuthProvider } from "@/context/AuthContext";

/**
 * A render that gives a component the same providers `main.jsx` does.
 *
 * `retry: false` is the important one. The app retries a failed query once, so
 * without this every error-state assertion waits for a second request before
 * the component ever renders its error branch — which reads as a flaky test
 * rather than as the deliberate retry it is.
 */
export function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });
}

export function renderWithProviders(
  ui,
  { route = "/", queryClient = createTestQueryClient(), withAuth = false } = {},
) {
  const tree = (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>
        <TooltipProvider>
          <ToastProvider>{withAuth ? <AuthProvider>{ui}</AuthProvider> : ui}</ToastProvider>
        </TooltipProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );

  return { queryClient, ...render(tree) };
}
