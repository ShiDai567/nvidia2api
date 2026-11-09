import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { TokenUsageChart } from "./token-usage-chart";

describe("TokenUsageChart", () => {
  it("gives every daily bar the plot height so token percentages are visible", () => {
    const days = Array.from({ length: 7 }, (_, index) => ({
      date: `2026-11-${String(index + 1).padStart(2, "0")}`,
      prompt_tokens: index === 6 ? 80 : 0,
      completion_tokens: index === 6 ? 20 : 0,
      total_tokens: index === 6 ? 100 : 0,
      requests: index === 6 ? 1 : 0,
      success: index === 6 ? 1 : 0,
    }));
    const html = renderToStaticMarkup(createElement(TokenUsageChart, { days }));
    const barClasses = [...html.matchAll(/<div class="([^"]*)">/g)]
      .map(([, className]) => className.split(" "))
      .filter((classes) => classes.includes("group") && classes.includes("flex-1"));

    expect(barClasses).toHaveLength(7);
    expect(barClasses.every((classes) => classes.includes("h-full"))).toBe(true);
  });
});
