// =====================================================================
// Tauri v2 library entry point.
//
// `main.rs` calls `kevs_digital_bos_lib::run()`. Everything below is what
// actually boots the desktop app: the Builder, the plugins, and the
// custom commands exposed to the webview.
//
// Existing plugins (unchanged):
//   - tauri-plugin-single-instance  → focuses the running window on
//                                     second launch instead of spawning
//                                     a duplicate process
//   - tauri-plugin-opener           → open-in-browser helper
//
// New in this build:
//   - `ble_print` — raw ESC/POS write to a Bluetooth thermal printer.
//     The POS HTML calls it via window.POS_TAURI_BLE_PRINT (installed
//     by tauri.conf.json's initializationScript). On the browser, the
//     bridge doesn't exist, so the POS falls back to window.print().
// =====================================================================

use btleplug::api::{
    Central, CharPropFlags, Manager as _, Peripheral as _, ScanFilter, WriteType,
};
use btleplug::platform::Manager;
use std::time::Duration;
use tokio::time::sleep;
use tauri::Manager;

// ─────────────────────────────────────────────────────────────────────
// BLE printer discovery + write
//
// Called from the webview via:
//   window.POS_TAURI_BLE_PRINT = async (bytes) => {
//       await window.__TAURI_INTERNALS__.invoke('ble_print', {
//           bytes: Array.from(bytes),
//       });
//   };
//
// The POS HTML builds a Uint8Array of ESC/POS bytes and passes it here.
// Tauri deserialises it into Vec<u8>.
//
// Flow:
//   1. Grab the first available BLE adapter.
//   2. Scan for 3 seconds.
//   3. Find the first peripheral whose name looks like a thermal printer.
//   4. Connect, discover services, find the writable characteristic.
//   5. Write in 100-byte chunks (BLE MTU-safe across common printers).
//
// No connection caching in v1. A receipt is ~1–3 KB, so a 3-second scan
// before each print is noticeable but acceptable. Caching the connected
// `Peripheral` in a Tauri state handle is the natural next optimisation
// once the printer-per-terminal assumption holds.
// ─────────────────────────────────────────────────────────────────────

#[tauri::command]
async fn ble_print(bytes: Vec<u8>) -> Result<(), String> {
    if bytes.is_empty() {
        return Err("Empty byte array — nothing to print".into());
    }

    // ── 1. BLE adapter ──
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

    // ── 2. Scan ──
    central
        .start_scan(ScanFilter::default())
        .await
        .map_err(|e| format!("Scan start failed: {e}"))?;
    sleep(Duration::from_secs(3)).await;
    central
        .stop_scan()
        .await
        .map_err(|e| format!("Scan stop failed: {e}"))?;

    // ── 3. Filter for printer-looking devices ──
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

    // ── 4. Connect + discover services ──
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

    // Known ESC/POS write characteristic UUIDs across common BLE thermal
    // printers. Add new UUIDs here if you deploy a model whose
    // characteristic isn't caught by the property fallback below.
    let known_write_uuids = [
        "00002af1-0000-1000-8000-00805f9b34fb", // Standard BLE printer
        "0000ff02-0000-1000-8000-00805f9b34fb", // Chinese thermal printers
        "0000fec7-0000-1000-8000-00805f9b34fb", // Alternative
        "bef8d6c9-9c21-4c9e-b632-bd58c1009f9f", // Some Xprinter models
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

    // ── 5. Write in chunks ──
    // 100-byte chunks stay under the negotiated MTU on every common BLE
    // thermal printer. A 20ms inter-chunk delay prevents buffer overflow
    // on cheap controllers (Goojprt, generic 58mm).
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

// ─────────────────────────────────────────────────────────────────────
// App entry point — this is what `main.rs` calls.
// ─────────────────────────────────────────────────────────────────────

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        // Single-instance MUST be registered first, before other plugins.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                // show() is needed in case the window was minimized/hidden.
                let _ = window.show();
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_opener::init())
        // ── New: expose ble_print to the webview ──
        .invoke_handler(tauri::generate_handler![ble_print])
        .run(tauri::generate_context!())
        .expect("error while running Kevs Digital bOS");
}
