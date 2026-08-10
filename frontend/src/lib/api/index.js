/**
 * The API surface, one module per backend router.
 *
 * Every function here returns parsed data, never an axios response — callers
 * are TanStack Query hooks and should not be unwrapping `.data`. Nothing in
 * `components/` or `pages/` imports axios directly.
 */

export * as alertsApi from "./alerts";
export * as auditApi from "./audit";
export * as authApi from "./auth";
export * as chatApi from "./chat";
export * as dashboardApi from "./dashboard";
export * as documentsApi from "./documents";
export * as evaluationApi from "./evaluation";
export * as reportsApi from "./reports";
export * as sharesApi from "./shares";
export * as usersApi from "./users";
