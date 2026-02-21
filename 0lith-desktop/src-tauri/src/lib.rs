use std::sync::Mutex;
use tauri::{
    image::Image,
    menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Emitter, Manager, WindowEvent,
};

struct TrayState {
    gaming_item: CheckMenuItem<tauri::Wry>,
}

#[tauri::command]
fn sync_tray_gaming(state: tauri::State<'_, Mutex<TrayState>>, checked: bool) {
    if let Ok(s) = state.lock() {
        let _ = s.gaming_item.set_checked(checked);
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .invoke_handler(tauri::generate_handler![sync_tray_gaming])
        .setup(|app| {
            // Load tray icon
            let icon = Image::from_path("icons/32x32.png")
                .or_else(|_| Image::from_path("src-tauri/icons/32x32.png"))
                .unwrap_or_else(|_| {
                    app.default_window_icon().cloned().expect("no app icon found")
                });

            // Build menu items
            let show_item = MenuItem::with_id(app, "show", "Show 0Lith", true, None::<&str>)?;
            let hide_item = MenuItem::with_id(app, "hide", "Hide 0Lith", true, None::<&str>)?;
            let gaming_item = CheckMenuItem::with_id(
                app,
                "gaming",
                "Gaming Mode",
                true,
                false,
                None::<&str>,
            )?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let sep1 = PredefinedMenuItem::separator(app)?;
            let sep2 = PredefinedMenuItem::separator(app)?;

            let menu = Menu::with_items(
                app,
                &[&show_item, &hide_item, &sep1, &gaming_item, &sep2, &quit_item],
            )?;

            // Store gaming item for frontend sync
            app.manage(Mutex::new(TrayState {
                gaming_item: gaming_item.clone(),
            }));

            // Build tray icon
            let _tray = TrayIconBuilder::new()
                .icon(icon)
                .tooltip("0Lith")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(move |app, event| {
                    match event.id.as_ref() {
                        "show" => {
                            if let Some(window) = app.get_webview_window("main") {
                                let _ = window.show();
                                let _ = window.set_focus();
                            }
                        }
                        "hide" => {
                            if let Some(window) = app.get_webview_window("main") {
                                let _ = window.hide();
                            }
                        }
                        "gaming" => {
                            // Emit event to frontend — it will handle the actual toggle
                            let _ = app.emit("tray-gaming-toggle", ());
                        }
                        "quit" => {
                            app.exit(0);
                        }
                        _ => {}
                    }
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                })
                .build(app)?;

            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                // Hide instead of quit — keep running in tray
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
