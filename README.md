# leaflow-rs

Leaflow 平台的 Rust SDK，由正式 [leaflowapis](https://github.com/leaflowapis/leaflowapis) 契约生成，所用契约版本记录于 `CONTRACTS_REF`。
每个服务对应一个 crate，命名为 `leaflow-<服务>`。

| feature | 内容 |
| --- | --- |
| `rest` | `<服务>::<版本>`：OpenAPI 契约的模型与异步客户端，由 openapi-to-rust 生成 |
| `rustls` | REST 客户端经 reqwest 的 rustls 访问 HTTPS |
| `proto` | `leaflow.<服务>.*` 的 protobuf 消息、各服务的方法路径与 `google::rpc`，由 prost 生成 |

默认启用全部 feature。仅使用 protobuf 消息时：

```toml
[dependencies]
leaflow-fleet = { git = "https://github.com/leaflowapis/leaflow-rs", rev = "<commit>", default-features = false, features = ["proto"] }
```

```rust
use leaflow_fleet::mcp::v1::{ListMcpServersRequest, mcp_service};

let path = mcp_service::LIST_MCP_SERVERS;
```

REST 客户端：

```rust
let client = leaflow_fleet::v1::HttpClient::new().with_api_key(scoped_token);
let machines = client.list_machines(None, None, None::<&str>).await?;
```

## 生成

```sh
npm ci
python3 scripts/generate.py
```

`CONTRACTS_DIR` 可指向一份位于 `CONTRACTS_REF` 且无未提交修改的契约副本；未设置时，契约将被拉取至 `leaflowapis/`。
