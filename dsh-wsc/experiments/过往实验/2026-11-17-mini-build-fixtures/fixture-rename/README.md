# rename-fixture

A tiny tree builder. The public entry point is `buildTree`, exported from
`src/tree.js`. `buildTree(paths)` splits each path on `/` and nests the
segments under a single root node named `root`; sibling segments keep the
order they first appear in.

`src/config.json` names the entry module and the exported symbol. Every module
in `src/` imports the entry point, and `src/registry.js` collects the six
groups into one object. `bin/cli.js` prints the registry as JSON.

Run the tests with `node --test tests/visible/basic.test.mjs`.


| 臂 | 场景 | 样本 | 总成本¥ 中位(区间) | 压缩次数 中位 | 测试 | 严格探针 |
|---|---|---|---|---|---|---|

## 裁定
