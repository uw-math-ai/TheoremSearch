// observablehq.config.js — requires "type": "module" in package.json
// or rename to observablehq.config.mjs
export default {
  root: "src",
  pages: [
    {name: "Structural Report", path: "/"},
    {name: "Cycle Consistency", path: "/cycle-consistency"},
  ],
};
