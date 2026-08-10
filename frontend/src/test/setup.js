import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

/**
 * Test environment setup.
 *
 * jsdom leaves state between test files inside one worker: a token written to
 * localStorage by one test is visible to the next, and the auth context reads
 * localStorage at mount. Clearing it here is what keeps a passing test from
 * depending on the file that ran before it.
 */
afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.clearAllMocks();
});

beforeEach(() => {
  localStorage.clear();
});

// Radix measures elements and jsdom reports every box as 0×0. These are the
// three APIs its popovers and scroll areas call that jsdom does not implement;
// without them a Select or Dialog throws on open rather than rendering.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
};

if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}

if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
}
