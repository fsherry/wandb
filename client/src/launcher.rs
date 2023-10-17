use fork::{Fork, fork};
use std::process::Command;
use tempfile::NamedTempFile;
use std::fs;
use std::{thread, time};

pub struct Launcher {
    pub command: String,
}

fn wait_for_port(port_filename: &str) -> i32 {
    let delay_time = time::Duration::from_millis(20);
    loop {
        thread::sleep(delay_time);
        let contents = fs::read_to_string(port_filename)
            .expect("Should have been able to read the file");
        let lines = contents.lines().collect::<Vec<_>>();
        if lines.last().copied() == Some("EOF") {
            for item in lines.iter() {
                match item.split_once("=") {
                    None => continue,
                    Some((param, val)) =>
                        if param == "sock" {
                            let my_int = val.to_string().parse::<i32>().unwrap();
                            return my_int;
                        },
                }
            }
        }
    }
}

impl Launcher {
    pub fn start(&self) -> i32 {
        let port_file = NamedTempFile::new().expect("tempfile should be created");
        let port_filename = port_file.path().as_os_str().to_str().unwrap();
        match fork() {
            Ok(Fork::Parent(_child)) => {
                let port = wait_for_port(port_filename);
                return port;
            },
            Ok(Fork::Child) => {
                let _command = Command::new(self.command.clone())
                    .arg("--port-filename")
                    .arg(port_filename)
                    .output();
            },
            Err(_) => println!("Fork failed"),
        }
        0
    }
}