import { expect, test } from "vitest";

import { resolveApiBase } from "../src/config";

test("production build uses same-origin api by default", () => {
  expect(resolveApiBase(undefined, false)).toBe("/api");
});

test("development build reaches the local backend by default", () => {
  expect(resolveApiBase("", true)).toBe("http://127.0.0.1:8000/api");
});

test("explicit api base overrides the environment default", () => {
  expect(resolveApiBase("https://example.com/api/", false)).toBe(
    "https://example.com/api",
  );
});
