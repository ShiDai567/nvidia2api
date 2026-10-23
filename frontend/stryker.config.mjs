/** @type {import('@stryker-mutator/api/core').PartialStrykerOptions} */
export default {
  mutate: ["lib/api.ts:74:1-83:2"],
  testRunner: "vitest",
  checkers: ["typescript"],
  tsconfigFile: "tsconfig.json",
  reporters: ["clear-text", "html", "progress"],
  coverageAnalysis: "perTest",
  concurrency: 2,
  timeoutMS: 10000,
  vitest: {
    configFile: "vitest.config.ts",
  },
};
