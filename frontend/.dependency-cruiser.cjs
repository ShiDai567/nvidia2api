module.exports = {
  forbidden: [
    {
      name: "no-circular-dependencies",
      severity: "error",
      comment: "模块之间不得形成循环依赖。",
      from: {},
      to: { circular: true },
    },
    {
      name: "no-unresolved-dependencies",
      severity: "error",
      comment: "项目模块引用必须可解析。",
      from: {},
      to: { couldNotResolve: true },
    },
  ],
  options: {
    tsConfig: { fileName: "tsconfig.json" },
    doNotFollow: { path: "node_modules" },
    exclude: { path: "(^|/)([.]next|coverage|reports)(/|$)" },
    enhancedResolveOptions: {
      exportsFields: ["exports"],
      conditionNames: ["import", "require", "node", "default"],
    },
  },
};
