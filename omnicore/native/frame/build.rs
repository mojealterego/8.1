use std::{env, path::PathBuf, process::Command};

fn run(command: &mut Command) {
    let status = command.status().expect("cannot start native tool");
    assert!(status.success(), "native tool failed: {:?}", command);
}

fn main() {
    for path in ["src/frame.c", "src/frame.h"] {
        println!("cargo:rerun-if-changed={path}");
    }
    for key in ["CC", "AR"] {
        println!("cargo:rerun-if-env-changed={key}");
    }
    let target = env::var("TARGET").unwrap();
    let host = env::var("HOST").unwrap();
    let tool = |key: &str, fallback: &str| {
        let specific = format!("{key}_{}", target.replace('-', "_"));
        println!("cargo:rerun-if-env-changed={specific}");
        env::var_os(&specific).or_else(|| env::var_os(key)).unwrap_or_else(|| {
            assert_eq!(target, host, "cross build requires explicit {key}");
            fallback.into()
        })
    };
    let out = PathBuf::from(env::var_os("OUT_DIR").unwrap());
    let object = out.join("frame.o");
    run(Command::new(tool("CC", "cc")).args([
        "-std=c11", "-ffreestanding", "-fPIC", "-O2", "-Wall", "-Wextra", "-Werror",
        "-c", "src/frame.c", "-o",
    ]).arg(&object));
    run(Command::new(tool("AR", "ar")).arg("crs").arg(out.join("libomnicore_frame.a")).arg(object));
    println!("cargo:rustc-link-search=native={}", out.display());
    println!("cargo:rustc-link-lib=static=omnicore_frame");
}
