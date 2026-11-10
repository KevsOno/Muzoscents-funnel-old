// =====================================================================
// Tauri v2 library entry point.
//
// Existing plugins:
//   - tauri-plugin-single-instance
//   - tauri-plugin-opener
//
// New:
//   - ble_print  → raw ESC/POS write to a Bluetooth thermal printer
//   - tauri-plugin-sql → SQLite offline store
//
// IMPORTANT: `initializationScript` is NOT a valid window key in the
// Tauri v2 schema. The BLE bridge is injected here instead via
// `append_invoke_initialization_script`, which runs on every page load
// (including the remote origin) and preserves the same global.
//
// `use tauri::Manager as _;` — imported anonymously. tauri::Manager is
// a trait that provides `get_webview_window`; btleplug::platform::Manager
// is a struct we call `::new()` on. Importing both under the same name
// is a duplicate-definition error, and importing only btleplug would
// lose the tauri trait methods. The `as _` form keeps the trait in
// scope for method resolution without occupying the `Manager` name.
//
// DEBUG BUILD (TEMPORARY):
// The `.setup(...)` block below opens the WebView inspector at startup
// for RELEASE builds so we can see load errors, script errors, network
// failures, and DOM/CSS state on a remote origin where devtools is
// otherwise unavailable. The `devtools` feature in Cargo.toml makes
// `open_devtools()` callable outside debug builds. Remove both when
// done debugging.
// =====================================================================

use btleplug::api::{
    Central, CharPropFlags, Manager as _, Peripheral as _, ScanFilter, WriteType,
};
use btleplug::platform::Manager;
use std::time::Duration;
use tokio::time::sleep;
use tauri::Manager as _;

#[tauri::command]
async fn ble_print(bytes: Vec<u8>) -> Result<(), String> {
    if bytes.is_empty() {
        return Err("Empty byte array — nothing to print".into());
    }

    let manager = Manager::new()
        .await
        .map_err(|e| format!("BLE manager init failed: {e}"))?;
    let adapters = manager
        .adapters()
        .await
        .map_err(|e| format!("Adapter list failed: {e}"))?;
    let central = adapters
        .into_iter()
        .next()
        .ok_or("No Bluetooth adapter found on this machine")?;

    central
        .start_scan(ScanFilter::default())
        .await
        .map_err(|e| format!("Scan start failed: {e}"))?;
    sleep(Duration::from_secs(3)).await;
    central
        .stop_scan()
        .await
        .map_err(|e| format!("Scan stop failed: {e}"))?;

    let peripherals = central
        .peripherals()
        .await
        .map_err(|e| format!("Peripheral list failed: {e}"))?;
    if peripherals.is_empty() {
        return Err(
            "No Bluetooth devices found. Make sure the printer is powered on and nearby."
                .to_string(),
        );
    }

    let printer_keywords = [
        "printer", "pos", "xprinter", "goojprt", "peripage", "zjiang", "zj-", "thermal",
        "receipt", "58mm", "80mm", "blue",
    ];

    let mut matched = None;
    for p in peripherals {
        let props = p
            .properties()
            .await
            .map_err(|e| format!("Device property read failed: {e}"))?;
        if let Some(pr) = props {
            let name = pr.local_name.unwrap_or_default().to_lowercase();
            if printer_keywords.iter().any(|k| name.contains(k)) {
                matched = Some(p);
                break;
            }
        }
    }

    let printer = matched.ok_or_else(|| {
        "No printer found nearby. Power on the Bluetooth printer and try again.".to_string()
    })?;

    if !printer
        .is_connected()
        .await
        .map_err(|e| format!("Connection state check failed: {e}"))?
    {
        printer
            .connect()
            .await
            .map_err(|e| format!("Printer connect failed: {e}"))?;
    }
    printer
        .discover_services()
        .await
        .map_err(|e| format!("Service discovery failed: {e}"))?;

    let chars = printer.characteristics();

    let known_write_uuids = [
        "00002af1-0000-1000-8000-00805f9b34fb",
        "0000ff02-0000-1000-8000-00805f9b34fb",
        "0000fec7-0000-1000-8000-00805f9b34fb",
        "bef8d6c9-9c21-4c9e-b632-bd58c1009f9f",
    ];

    let write_char = chars
        .iter()
        .find(|c| {
            known_write_uuids
                .iter()
                .any(|k| c.uuid.to_string().to_lowercase() == *k)
        })
        .or_else(|| {
            chars
                .iter()
                .find(|c| c.properties.contains(CharPropFlags::WRITE_WITHOUT_RESPONSE))
        })
        .or_else(|| chars.iter().find(|c| c.properties.contains(CharPropFlags::WRITE)))
        .ok_or_else(|| {
            "Printer connected but no writable characteristic was found. \
             This printer may use a proprietary BLE protocol."
                .to_string()
        })?;

    const CHUNK_SIZE: usize = 100;
    const INTER_CHUNK_DELAY_MS: u64 = 20;

    for (i, chunk) in bytes.chunks(CHUNK_SIZE).enumerate() {
        printer
            .write(write_char, chunk, WriteType::WithoutResponse)
            .await
            .map_err(|e| format!("BLE write failed at chunk {i}: {e}"))?;
        sleep(Duration::from_millis(INTER_CHUNK_DELAY_MS)).await;
    }

    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_sql::Builder::default().build())
        .append_invoke_initialization_script(
            r#"
            if (window.__TAURI_INTERNALS__ && typeof window.__TAURI_INTERNALS__.invoke === 'function') {
                window.POS_TAURI_BLE_PRINT = async (bytes) => {
                    await window.__TAURI_INTERNALS__.invoke('ble_print', { bytes: Array.from(bytes) });
                };
            }
            "#,
        )
        .invoke_handler(tauri::generate_handler![ble_print])
        // ── DEBUG ONLY: open the inspector on release builds ──
        // The `devtools` feature in Cargo.toml makes this available
        // outside debug builds. Remove this block (and the feature)
        // before shipping a production build.
        .setup(|app| {
            #[cfg(not(debug_assertions))]
            {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.open_devtools();
                }
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Kevs Digital bOS");
}
