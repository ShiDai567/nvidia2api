import { describe, expect, it } from "vitest";
import { asList } from "./api";

describe("asList", () => {
  it("returns an array response directly", () => {
    const values = [{ id: 1 }];

    expect(asList(values)).toBe(values);
  });

  it("reads paginated results", () => {
    expect(asList({ results: [1, 2] })).toEqual([1, 2]);
  });

  it("reads data-wrapped results", () => {
    expect(asList({ data: ["model"] })).toEqual(["model"]);
  });

  it("returns an empty array for unsupported responses", () => {
    expect(asList({ results: "invalid", data: null })).toEqual([]);
    expect(asList(null)).toEqual([]);
  });
});
