use tauri::{LogicalSize, Manager, PhysicalPosition, PhysicalSize, WebviewWindow};

const COLLAPSED_WIDTH: u32 = 64;
const COLLAPSED_HEIGHT: u32 = 64;
const PANEL_WIDTH: u32 = 420;
const PANEL_HEIGHT: u32 = 640;

pub fn resize_window(window: &WebviewWindow, open: bool) -> Result<(), String> {
    let current_position = window
        .outer_position()
        .map_err(|_| "无法读取桌面窗口位置".to_string())?;
    let current_size = window
        .outer_size()
        .map_err(|_| "无法读取桌面窗口尺寸".to_string())?;
    let target_logical_size = if open {
        LogicalSize::new(PANEL_WIDTH, PANEL_HEIGHT)
    } else {
        LogicalSize::new(COLLAPSED_WIDTH, COLLAPSED_HEIGHT)
    };
    let scale_factor = window
        .scale_factor()
        .map_err(|_| "无法读取桌面缩放比例".to_string())?;
    let target_physical_size: PhysicalSize<u32> = target_logical_size.to_physical(scale_factor);
    let target_position = PhysicalPosition::new(
        current_position.x + current_size.width as i32 - target_physical_size.width as i32,
        current_position.y + current_size.height as i32 - target_physical_size.height as i32,
    );
    window
        .set_size(target_logical_size)
        .map_err(|_| "无法调整桌面窗口尺寸".to_string())?;
    window
        .set_position(target_position)
        .map_err(|_| "无法保持桌面窗口锚点".to_string())?;
    if open {
        window.show().map_err(|_| "无法显示桌面窗口".to_string())?;
        window
            .set_focus()
            .map_err(|_| "无法聚焦桌面窗口".to_string())?;
    }
    Ok(())
}

pub fn place_near_bottom_right<R: tauri::Runtime>(app: &tauri::App<R>) -> tauri::Result<()> {
    let Some(window) = app.get_webview_window("main") else {
        return Ok(());
    };
    let Some(monitor) = window.primary_monitor()? else {
        return Ok(());
    };
    let monitor_position = monitor.position();
    let monitor_size = monitor.size();
    let scale_factor = monitor.scale_factor();
    let collapsed_size: PhysicalSize<u32> =
        LogicalSize::new(COLLAPSED_WIDTH, COLLAPSED_HEIGHT).to_physical(scale_factor);
    let right_margin = (26.0 * scale_factor).round() as i32;
    let bottom_margin = (82.0 * scale_factor).round() as i32;
    let x =
        monitor_position.x + monitor_size.width as i32 - collapsed_size.width as i32 - right_margin;
    let y = monitor_position.y + monitor_size.height as i32
        - collapsed_size.height as i32
        - bottom_margin;
    window.set_position(PhysicalPosition::new(x, y))?;
    Ok(())
}
