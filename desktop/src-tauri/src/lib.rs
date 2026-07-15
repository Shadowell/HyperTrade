mod api;
mod window;

use reqwest::Client;
use serde_json::Value;
use tauri::{
    ipc::Channel,
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, State, WebviewWindow,
};

#[tauri::command]
async fn check_connection(
    client: State<'_, Client>,
    api_base: String,
) -> Result<api::ConnectionResult, String> {
    api::check_connection(&client, &api_base).await
}

#[tauri::command]
async fn stream_agent(
    client: State<'_, Client>,
    api_base: String,
    prompt: String,
    idempotency_key: String,
    on_event: Channel<Value>,
) -> Result<(), String> {
    api::stream_agent(&client, &api_base, &prompt, &idempotency_key, on_event).await
}

#[tauri::command]
fn set_panel_open(window: WebviewWindow, open: bool) -> Result<(), String> {
    window::resize_window(&window, open)
}

#[tauri::command]
fn start_dragging(window: WebviewWindow) -> Result<(), String> {
    window
        .start_dragging()
        .map_err(|_| "无法拖动桌面窗口".to_string())
}

#[tauri::command]
fn hide_window(window: WebviewWindow) -> Result<(), String> {
    window.hide().map_err(|_| "无法隐藏桌面窗口".to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let client = api::build_client().expect("failed to build HyperTrade desktop client");
    tauri::Builder::default()
        .manage(client)
        .setup(|app| {
            #[cfg(target_os = "macos")]
            app.set_activation_policy(tauri::ActivationPolicy::Accessory);

            window::place_near_bottom_right(app)?;
            let show = MenuItem::with_id(app, "show", "打开 HyperTrade Bot", true, None::<&str>)?;
            let collapse =
                MenuItem::with_id(app, "collapse", "收起为悬浮图标", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &collapse, &quit])?;
            let mut tray = TrayIconBuilder::with_id("hypertrade-bot")
                .tooltip("HyperTrade Mission 助手")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_tray_icon_event(|tray, event| {
                    if matches!(
                        event,
                        TrayIconEvent::Click {
                            button: MouseButton::Left,
                            button_state: MouseButtonState::Up,
                            ..
                        }
                    ) {
                        let app = tray.app_handle();
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window::resize_window(&window, true);
                        }
                    }
                });
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            tray.build(app)?;
            Ok(())
        })
        .on_menu_event(|app, event| match event.id().as_ref() {
            "show" => {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window::resize_window(&window, true);
                }
            }
            "collapse" => {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window::resize_window(&window, false);
                }
            }
            "quit" => app.exit(0),
            _ => {}
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .invoke_handler(tauri::generate_handler![
            check_connection,
            stream_agent,
            set_panel_open,
            start_dragging,
            hide_window
        ])
        .run(tauri::generate_context!())
        .expect("error while running HyperTrade desktop bot");
}
