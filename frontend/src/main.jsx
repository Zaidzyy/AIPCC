import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "@/App";
import { ToastProvider, TooltipProvider } from "@/components/ui";
import { AuthProvider } from "@/context/AuthContext";
import "@/index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // A 401 is handled globally by the apiClient interceptor; retrying it
      // would only produce a second failure before the redirect.
      retry: (failureCount, error) =>
        error?.response?.status === 401 ? false : failureCount < 1,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
  },
});

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <TooltipProvider delayDuration={300}>
            <ToastProvider>
              <App />
            </ToastProvider>
          </TooltipProvider>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
