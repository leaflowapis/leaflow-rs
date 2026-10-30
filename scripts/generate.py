#!/usr/bin/env python3
import json
import os
import pathlib
import re
import shutil
import subprocess
import tomllib

import contracts

ROOT = pathlib.Path(__file__).resolve().parent.parent
OPENAPI_TO_RUST = "0.23.0"
BUF = "1.75.0"
REDOCLY = "2.47.0"
VERSION = "0.8.0"
PROTO_DEPENDENCIES = {"bytes": "1", "prost": "0.14", "prost-types": "0.14"}
GOOGLE_RPC = ["google/rpc/status.proto", "google/rpc/code.proto", "google/rpc/error_details.proto"]


def require_source(source, ref):
    head = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if head != ref:
        raise ValueError("source HEAD differs from CONTRACTS_REF")
    dirty = subprocess.check_output(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=all"], text=True)
    if dirty:
        raise ValueError("CONTRACTS_DIR must be a clean checkout of CONTRACTS_REF")
    return head


def node_tool(name, version):
    path = shutil.which(name, path=str(ROOT / "node_modules" / ".bin"))
    if path is None:
        raise SystemExit(f"{name} is not in node_modules: run npm ci")
    got = subprocess.check_output([path, "--version"], text=True, cwd=ROOT).strip()
    if got != version:
        raise SystemExit(f"{name} is {got}, not {version}: run npm ci")
    return path


def openapi_to_rust():
    tools = ROOT / ".tools"

    def installed():
        path = shutil.which("openapi-to-rust", path=str(tools / "bin"))
        if path and subprocess.check_output([path, "--version"], text=True).split()[-1] == OPENAPI_TO_RUST:
            return path
        return None

    if not installed():
        subprocess.run(["cargo", "install", "--locked", "--root", str(tools), f"openapi-to-rust@{OPENAPI_TO_RUST}"],
                       cwd=ROOT, check=True)
    return installed()


def remove_generated():
    manifest = ROOT / "Cargo.toml"
    if not manifest.exists():
        return
    for member in tomllib.loads(manifest.read_text(encoding="utf-8"))["workspace"]["members"]:
        shutil.rmtree(ROOT / member, ignore_errors=True)


class Crate:
    def __init__(self, directory):
        self.directory = directory
        self.name = "leaflow-" + "-".join(directory.parts)
        self.versions = {}
        self.proto = False
        self.features = {"rest": set(), "proto": set()}
        self.dependencies = {}
        self.dependency_features = {}

    def add_dependency(self, feature, name, spec):
        spec = {"version": spec} if isinstance(spec, str) else dict(spec)
        features = spec.pop("features", [])
        known = self.dependencies.setdefault(name, spec)
        if known != spec:
            raise ValueError(f"{self.name}: {name} is required as {known} and as {spec}")
        self.features[feature].add(name)
        self.dependency_features.setdefault((feature, name), set()).update(features)


def generate_services(source, crates):
    redocly = node_tool("redocly", REDOCLY)
    generator = openapi_to_rust()
    bundled = ROOT / "target" / "contracts"
    shutil.rmtree(bundled, ignore_errors=True)
    environment = {**os.environ, "REDOCLY_TELEMETRY": "off", "REDOCLY_SUPPRESS_UPDATE_NOTICE": "true"}
    for spec in sorted((source / "leaflow").glob("**/openapi.yaml")):
        relative = spec.parent.relative_to(source / "leaflow")
        directory, version = pathlib.PurePosixPath(*relative.parts[:-1]), relative.parts[-1]
        crate = crates.setdefault(directory, Crate(directory))
        contract = f"leaflow/{relative.as_posix()}/openapi.yaml"
        crate.versions[version] = contract
        subprocess.run([redocly, "bundle", str(spec), "--output", str(bundled / contract)],
                       cwd=ROOT, env=environment, check=True, stdout=subprocess.DEVNULL)
        output = ROOT / directory / "src" / version
        subprocess.run([generator, "generate", contract, "--output-dir", str(output), "--quiet"], cwd=bundled, check=True)
        required = output / "REQUIRED_DEPS.toml"
        for name, dependency in tomllib.loads(required.read_text(encoding="utf-8"))["dependencies"].items():
            if name == "reqwest":
                dependency = {**dependency, "features": [f for f in dependency["features"] if f != "rustls"]}
            crate.add_dependency("rest", name, dependency)
        required.unlink()
        print(contract, flush=True)


def generate_protos(source, crates):
    if not (source / "buf.yaml").exists():
        return
    buf = node_tool("buf", BUF)
    work = ROOT / "target" / "proto"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    contract_set, google_set = work / "contracts.binpb", work / "googleapis.binpb"
    subprocess.run([buf, "build", str(source), "--as-file-descriptor-set", "-o", str(contract_set)], cwd=ROOT, check=True)
    lock = (source / "buf.lock").read_text(encoding="utf-8")
    commit = re.search(r"name: buf\.build/googleapis/googleapis\s+commit: (\w+)", lock).group(1)
    paths = [argument for path in GOOGLE_RPC for argument in ("--path", path)]
    subprocess.run([buf, "build", f"buf.build/googleapis/googleapis:{commit}", *paths, "--as-file-descriptor-set",
                    "-o", str(google_set)], cwd=ROOT, check=True)
    services = sorted({proto.relative_to(source / "leaflow").parts[0] for proto in (source / "leaflow").glob("**/*.proto")})
    for service in services:
        directory = pathlib.PurePosixPath(service)
        crate = crates.setdefault(directory, Crate(directory))
        crate.proto = True
        for name, version in PROTO_DEPENDENCIES.items():
            crate.add_dependency("proto", name, version)
        subprocess.run(["cargo", "run", "--quiet", "--locked", "--manifest-path", str(ROOT / "generator" / "Cargo.toml"),
                        "--", service, str(ROOT / directory / "src" / "proto"), str(contract_set), str(google_set)],
                       cwd=ROOT, check=True)
        print(f"leaflow.{service}.*", flush=True)


def quoted(items):
    return "[" + ", ".join(json.dumps(item) for item in items) + "]"


def inline(spec):
    parts = []
    for key, value in spec.items():
        if isinstance(value, bool):
            parts.append(f"{key} = {'true' if value else 'false'}")
        elif isinstance(value, list):
            parts.append(f"{key} = {quoted(value)}")
        else:
            parts.append(f"{key} = {json.dumps(value)}")
    return "{ " + ", ".join(parts) + " }"


def write_manifest(crate):
    used = {feature: names for feature, names in crate.features.items() if names}
    owners = {name: [feature for feature in used if name in used[feature]] for name in crate.dependencies}
    features, dependencies = {}, {}
    for feature, names in used.items():
        entries = []
        for name in sorted(names):
            entries.append(f"dep:{name}")
            if len(owners[name]) > 1:
                entries += [f"{name}/{item}" for item in sorted(crate.dependency_features[(feature, name)])]
        features[feature] = entries
    if "rest" in features:
        features["rustls"] = ["rest", "reqwest/rustls"]
    for name, spec in crate.dependencies.items():
        spec = dict(spec)
        if len(owners[name]) == 1 and crate.dependency_features[(owners[name][0], name)]:
            spec["features"] = sorted(crate.dependency_features[(owners[name][0], name)])
        spec["optional"] = True
        dependencies[name] = spec
    lines = [
        "[package]",
        f'name = "{crate.name}"',
        "version.workspace = true",
        "edition.workspace = true",
        "rust-version.workspace = true",
        "license.workspace = true",
        "repository.workspace = true",
        "",
        "[lib]",
        "doctest = false",
        "",
        "[features]",
        f"default = {quoted(sorted(features))}",
        *[f"{feature} = {quoted(features[feature])}" for feature in sorted(features)],
        "",
        "[dependencies]",
        *[f"{name} = {inline(dependencies[name])}" for name in sorted(dependencies)],
    ]
    (ROOT / crate.directory / "Cargo.toml").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_library(crate):
    lines = []
    for version in sorted(crate.versions):
        lines += ['#[cfg(feature = "rest")]', "#[allow(dead_code, unused, clippy::all)]", f"pub mod {version};"]
    if crate.proto:
        package = "_".join(crate.directory.parts).replace("-", "_")
        lines += ['#[cfg(feature = "proto")]', "#[allow(clippy::all)]", "mod proto;",
                  '#[cfg(feature = "proto")]', "pub use proto::google;",
                  '#[cfg(feature = "proto")]', f"pub use proto::leaflow::{package}::*;"]
    (ROOT / crate.directory / "src" / "lib.rs").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_workspace(crates):
    lines = [
        "[workspace]",
        'resolver = "3"',
        "members = [",
        *[f'    "{member}",' for member in sorted(str(directory) for directory in crates)],
        "]",
        "",
        "[workspace.package]",
        f'version = "{VERSION}"',
        'edition = "2024"',
        'rust-version = "1.94"',
        'license = "MIT"',
        'repository = "https://github.com/leaflowapis/leaflow-rs"',
    ]
    (ROOT / "Cargo.toml").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main():
    ref = (ROOT / "CONTRACTS_REF").read_text().strip()
    source = os.environ.get("CONTRACTS_DIR")
    if source:
        source = pathlib.Path(source).resolve()
        require_source(source, ref)
    else:
        source = ROOT / "leaflowapis"
        contracts.fetch("https://github.com/leaflowapis/leaflowapis.git", source)
    remove_generated()
    crates = {}
    generate_services(source, crates)
    generate_protos(source, crates)
    for crate in crates.values():
        write_manifest(crate)
        write_library(crate)
    write_workspace(crates)
    subprocess.run(["cargo", "metadata", "--format-version", "1"], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["cargo", "fmt", "--all"], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
