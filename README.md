# leaflow-rs

Rust SDK for the Leaflow platform, generated from the [leaflowapis](https://github.com/leaflowapis/leaflowapis) contracts.
Each service is a crate named `leaflow-<service>`.

| feature | contents |
| --- | --- |
| `rest` | models and async client for the OpenAPI contract |
| `rustls` | HTTPS access through reqwest |
| `proto` | protobuf messages and service paths |

All features are enabled by default.

```rust
let client = leaflow_fleet::v1::HttpClient::new().with_api_key(scoped_token);
let machines = client.list_machines(None, None, None::<&str>).await?;
```

## Generation

```sh
npm ci
python3 scripts/generate.py
```

The contract version is recorded in `CONTRACTS_REF`. `CONTRACTS_DIR` may point to a clean checkout at that ref.
