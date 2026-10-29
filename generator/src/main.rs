use std::collections::BTreeMap;
use std::error::Error;
use std::path::PathBuf;

use prost::Message;
use prost_types::{FileDescriptorProto, FileDescriptorSet};

const USAGE: &str = "usage: generator <service> <output directory> <descriptor set>...";

fn main() -> Result<(), Box<dyn Error>> {
    let mut arguments = std::env::args().skip(1);
    let service = arguments.next().ok_or(USAGE)?;
    let output = PathBuf::from(arguments.next().ok_or(USAGE)?);
    let mut files = BTreeMap::new();
    for path in arguments {
        let set = FileDescriptorSet::decode(std::fs::read(&path)?.as_slice())?;
        for file in set.file {
            files.entry(file.name().to_owned()).or_insert(file);
        }
    }
    let prefix = format!("leaflow.{service}.");
    let wanted = |file: &FileDescriptorProto| {
        file.package().starts_with(&prefix)
            || ["google.rpc", "google.protobuf"].contains(&file.package())
    };
    let set = FileDescriptorSet {
        file: files.into_values().filter(wanted).collect(),
    };
    if !set
        .file
        .iter()
        .any(|file| file.package().starts_with(&prefix))
    {
        return Err(format!("no package leaflow.{service}.* in the descriptor sets").into());
    }

    std::fs::create_dir_all(&output)?;
    let mut config = prost_build::Config::new();
    config
        .out_dir(&output)
        .include_file("mod.rs")
        .bytes(["."])
        .enable_type_names()
        .type_name_domain(["."], "type.googleapis.com")
        .service_generator(Box::new(MethodPaths));
    config.compile_fds(set)?;
    Ok(())
}

struct MethodPaths;

impl prost_build::ServiceGenerator for MethodPaths {
    fn generate(&mut self, service: prost_build::Service, buf: &mut String) {
        buf.push_str(&format!("pub mod {} {{\n", snake_case(&service.proto_name)));
        buf.push_str(&format!(
            "    pub const NAME: &str = \"{}.{}\";\n",
            service.package, service.proto_name
        ));
        for method in &service.methods {
            buf.push_str(&format!(
                "    pub const {}: &str = \"/{}.{}/{}\";\n",
                snake_case(&method.proto_name).to_uppercase(),
                service.package,
                service.proto_name,
                method.proto_name
            ));
        }
        buf.push_str("}\n");
    }
}

fn snake_case(name: &str) -> String {
    let mut out = String::with_capacity(name.len() + 4);
    for (index, character) in name.chars().enumerate() {
        if character.is_ascii_uppercase() {
            if index > 0 {
                out.push('_');
            }
            out.push(character.to_ascii_lowercase());
        } else {
            out.push(character);
        }
    }
    out
}
