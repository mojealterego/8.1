use std::{env, path::PathBuf, process::Command};

fn run(command: &mut Command) {
    let status = command.status().expect("cannot start native tool");
    assert!(status.success(), "native tool failed: {:?}", command);
}

fn main() {
    for path in ["src/frame.c", "src/frame.h", "src/unix_client.c", "src/unix_client.h",
                 "src/unix_ffi.c", "src/unix_ffi.h"] {
        println!("cargo:rerun-if-changed={path}");
    }
    for key in ["CC", "AR"] {
        println!("cargo:rerun-if-env-changed={key}");
    }
    let target = env::var("TARGET").unwrap();
    let host = env::var("HOST").unwrap();
    let target_os = env::var("CARGO_CFG_TARGET_OS").unwrap();
    let tool = |key: &str, fallback: &str| {
        let specific = format!("{key}_{}", target.replace('-', "_"));
        println!("cargo:rerun-if-env-changed={specific}");
        env::var_os(&specific).or_else(|| {
            if target == host { env::var_os(key).or_else(|| Some(fallback.into())) } else { None }
        }).unwrap_or_else(|| panic!("cross build requires explicit {specific}"))
    };
    let cc = tool("CC", "cc");
    let ar = tool("AR", "ar");
    let out = PathBuf::from(env::var_os("OUT_DIR").unwrap());
    let mut sources = vec!["frame"];
    if target_os == "linux" || target_os == "android" {
        sources.extend(["unix_client", "unix_ffi"]);
    }
    let mut objects = Vec::new();
    for name in sources {
        let object = out.join(format!("{name}.o"));
        let mut cmd = Command::new(&cc);
        cmd.args(["-std=c11", "-fPIC", "-O2", "-Wall", "-Wextra", "-Werror"]);
        if name == "frame" { cmd.arg("-ffreestanding"); }
        run(cmd.arg("-c").arg(format!("src/{name}.c")).arg("-o").arg(&object));
        objects.push(object);
    }
    let archive = out.join("libomnicore_frame.a");
    match std::fs::remove_file(&archive) {
        Ok(()) => (),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => (),
        Err(e) => panic!("cannot remove stale archive: {e}"),
    }
    run(Command::new(ar).arg("crs").arg(archive).args(objects));
    println!("cargo:rustc-link-search=native={}", out.display());
    println!("cargo:rustc-link-lib=static=omnicore_frame");
}
