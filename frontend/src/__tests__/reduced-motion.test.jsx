import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const styles = readFileSync(resolve(process.cwd(), "src/index.css"), "utf8");

describe("reduced-motion stylesheet", () => {
  it("disables decorative animation, transitions, and smooth scrolling", () => {
    const reducedMotionRules = styles.slice(styles.indexOf("@media (prefers-reduced-motion: reduce)"));

    expect(reducedMotionRules).toContain("animation-iteration-count: 1 !important");
    expect(reducedMotionRules).toContain("transition-duration: 0.01ms !important");
    expect(reducedMotionRules).toContain("scroll-behavior: auto !important");
  });
});
