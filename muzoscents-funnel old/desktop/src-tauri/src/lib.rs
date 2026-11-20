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
// =====================================================================

use btleplug::api::{
    Central, CharPropFlags, Manager as _, Peripheral as _, ScanFilter, WriteType,
};
use btleplug::platform::Manager;
use std::time::Duration;
use tauri::webview::PageLoadEvent;
use tauri::Manager as _;
use tokio::time::sleep;

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

fn offline_fallback_script(target_url: &str) -> String {
    let escaped_url = target_url
        .replace('\\', "\\\\")
        .replace('\'', "\\'")
        .replace('"', "&quot;");
    format!(
        r#"
        (() => {{
            if (window.__KEVS_OFFLINE_FALLBACK_SHOWN__) return;
            const hasContent = !!(document.body && document.body.innerText && document.body.innerText.trim().length > 0);
            const isErrorUrl = location.protocol === 'about:' || location.href.includes('error') || !hasContent;
            if (!isErrorUrl) return;

            window.__KEVS_OFFLINE_FALLBACK_SHOWN__ = true;
            const retryTarget = "{escaped_url}" || "https://kevsbos.netlify.app/kdsiginin";
            document.documentElement.innerHTML = `
                <head>
                    <meta name="viewport" content="width=device-width,initial-scale=1.0" />
                    <style>
                        *{{box-sizing:border-box;margin:0;padding:0}}
                        body{{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px;background:#0F172A;color:#F8FAFC;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
                        .card{{width:100%;max-width:380px;background:#1E293B;border:1px solid rgba(255,255,255,0.1);border-radius:16px;padding:28px 24px;text-align:center;box-shadow:0 20px 40px rgba(0,0,0,0.35)}}
                        h1{{font-size:20px;font-weight:700;margin-bottom:8px}}
                        p{{font-size:14px;line-height:1.5;color:#CBD5E1;margin-bottom:18px}}
                        .pill{{font-size:12px;color:#94A3B8;background:rgba(15,23,42,0.65);border-radius:10px;padding:10px 12px;margin-bottom:18px}}
                        button{{width:100%;border:0;border-radius:10px;padding:13px 16px;font-size:15px;font-weight:600;color:#FFFFFF;background:#2563EB;cursor:pointer}}
                    </style>
                </head>
                <body>
                    <div class="card">
                        <h1>Kevs Digital bOS</h1>
                        <p>No active internet connection right now. Connect to Wi-Fi or mobile data to load this workspace.</p>
                        <div class="pill">Offline mode active</div>
                        <button id="kevs-tauri-retry" type="button">Retry Connection</button>
                    </div>
                </body>
            `;
            const btn = document.getElementById('kevs-tauri-retry');
            if (btn) {{
                btn.addEventListener('click', () => {{
                    window.__KEVS_OFFLINE_FALLBACK_SHOWN__ = false;
                    window.location.replace(retryTarget);
                }});
            }}
        }})();
        "#
    )
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
        .on_page_load(|webview, payload| {
            if payload.event() == PageLoadEvent::Finished {
                let script = offline_fallback_script(payload.url().as_str());
                let _ = webview.eval(&script);
            }
        })
        .invoke_handler(tauri::generate_handler![ble_print])
        .run(tauri::generate_context!())
        .expect("error while running Kevs Digital bOS");
}
