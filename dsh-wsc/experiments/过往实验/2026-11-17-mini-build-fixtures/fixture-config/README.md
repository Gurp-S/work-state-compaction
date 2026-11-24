# settings-kit

`loadSettings(raw)` normalises a settings object for the runtime.

The current file format is version 1:

    { "db": { "host": "localhost", "port": 5432 } }

and `loadSettings` returns the internal shape:

    { "database": { "host": "localhost", "port": 5432, "ssl": false } }


| 臂 | 场景 | 样本 | 总成本¥ 中位(区间) | 压缩次数 中位 | 测试 | 严格探针 |
|---|---|---|---|---|---|---|

## 裁定
