// Prevents an additional console window on Windows in release builds.
// DO NOT REMOVE THIS ATTRIBUTE.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    kevs_digital_bos_lib::run();
}
