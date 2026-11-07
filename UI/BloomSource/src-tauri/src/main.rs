#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use base64::{engine::general_purpose::STANDARD, Engine as _};
use serde::{Deserialize, Serialize};
use std::io::{self, BufRead, Write};
use std::fs;
use std::sync::{
	atomic::{AtomicBool, Ordering},
	Arc, Mutex, OnceLock,
};
use std::time::{SystemTime, UNIX_EPOCH};
use tauri::{Emitter, LogicalPosition, LogicalSize, Manager, State, WebviewWindow};
use windows::Win32::Foundation::{LPARAM, LRESULT, WPARAM};
use windows::Win32::Graphics::Gdi::{CreateRectRgn, DeleteObject, SetWindowRgn};
use windows::Win32::UI::WindowsAndMessaging::{
	CallNextHookEx, DispatchMessageW, GetMessageW, PeekMessageW, SetWindowsHookExW,
	TranslateMessage, UnhookWindowsHookEx, MSLLHOOKSTRUCT, MSG, PM_NOREMOVE, WH_MOUSE_LL,
	WM_MOUSEHWHEEL, WM_MOUSEMOVE, WM_MOUSEWHEEL,
};

static GESTURE_APP: OnceLock<tauri::AppHandle> = OnceLock::new();
static GESTURE_ENABLED: AtomicBool = AtomicBool::new(false);
static GESTURE_HOVERED: AtomicBool = AtomicBool::new(false);
static GESTURE_CENTER_X: std::sync::atomic::AtomicI32 = std::sync::atomic::AtomicI32::new(0);
static GESTURE_TOP_Y: std::sync::atomic::AtomicI32 = std::sync::atomic::AtomicI32::new(0);
static GESTURE_SCALE_MILLI: std::sync::atomic::AtomicI32 = std::sync::atomic::AtomicI32::new(1000);
static LAST_WHEEL_LOG_MS: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);

const ACTIVATION_HALF_WIDTH: i32 = 68;
const ACTIVATION_HEIGHT: i32 = 62;
const EXPANDED_HALF_WIDTH: i32 = 360;
const EXPANDED_HEIGHT: i32 = 300;

fn emit_gesture(name: &'static str) {
	log_gesture(&format!("evento={name}"));
	if let Some(app) = GESTURE_APP.get() {
		let _ = app.emit("onyx-gesture", name);
	}
}

fn log_gesture(message: &str) {
	let Ok(root) = std::env::current_dir() else { return };
	let logs = root.join("logs");
	if fs::create_dir_all(&logs).is_err() { return; }
	let path = logs.join("onyx-gestures.log");
	let Ok(mut file) = fs::OpenOptions::new().create(true).append(true).open(path) else { return };
	let millis = SystemTime::now().duration_since(UNIX_EPOCH).map(|duration| duration.as_millis()).unwrap_or_default();
	let _ = writeln!(file, "{millis} {message}");
}

fn gesture_zone(point: windows::Win32::Foundation::POINT, half_width: i32, height: i32) -> bool {
	let center = GESTURE_CENTER_X.load(Ordering::Relaxed);
	let top = GESTURE_TOP_Y.load(Ordering::Relaxed);
	let scale_milli = GESTURE_SCALE_MILLI.load(Ordering::Relaxed).max(1);
	let scaled_half_width = half_width.saturating_mul(scale_milli) / 1000;
	let scaled_height = height.saturating_mul(scale_milli) / 1000;
	let top_margin = 4_i32.saturating_mul(scale_milli) / 1000;
	(point.x - center).abs() <= scaled_half_width
		&& point.y >= top - top_margin
		&& point.y <= top + scaled_height
}

fn log_wheel_event(message: u32, delta: i16, point: windows::Win32::Foundation::POINT, enabled: bool) {
	let now = SystemTime::now()
		.duration_since(UNIX_EPOCH)
		.map(|duration| duration.as_millis() as u64)
		.unwrap_or(0);
	let previous = LAST_WHEEL_LOG_MS.load(Ordering::Relaxed);
	if now.saturating_sub(previous) >= 300 {
		LAST_WHEEL_LOG_MS.store(now, Ordering::Relaxed);
		let activation_zone = gesture_zone(point, ACTIVATION_HALF_WIDTH, ACTIVATION_HEIGHT);
		let expanded_zone = gesture_zone(point, EXPANDED_HALF_WIDTH, EXPANDED_HEIGHT);
		let center = GESTURE_CENTER_X.load(Ordering::Relaxed);
		let top = GESTURE_TOP_Y.load(Ordering::Relaxed);
		log_gesture(&format!(
			"rotella ricevuta tipo={message} delta={delta} x={} y={} centro={center} alto={top} zona_attivazione={activation_zone} zona_estesa={expanded_zone} enabled={enabled}",
			point.x, point.y
		));
	}
}

unsafe extern "system" fn mouse_gesture_hook(
	code: i32,
	wparam: WPARAM,
	lparam: LPARAM,
) -> LRESULT {
	if code >= 0 {
		let event = *(lparam.0 as *const MSLLHOOKSTRUCT);
		let message = wparam.0 as u32;
		if message == WM_MOUSEMOVE && GESTURE_ENABLED.load(Ordering::Relaxed) {
			let should_hover = if GESTURE_HOVERED.load(Ordering::Relaxed) {
				gesture_zone(event.pt, EXPANDED_HALF_WIDTH, EXPANDED_HEIGHT)
			} else {
				gesture_zone(event.pt, 58, 44)
			};
			let was_hovered = GESTURE_HOVERED.swap(should_hover, Ordering::Relaxed);
			if should_hover != was_hovered {
				emit_gesture(if should_hover { "hover-enter" } else { "hover-leave" });
			}
		} else if message == WM_MOUSEWHEEL || message == WM_MOUSEHWHEEL {
			let delta = ((event.mouseData >> 16) as u16) as i16;
			log_wheel_event(message, delta, event.pt, GESTURE_ENABLED.load(Ordering::Relaxed));
		}
	}
	CallNextHookEx(None, code, wparam, lparam)
}

fn start_mouse_gesture_hook(app: tauri::AppHandle, center_x: i32, top_y: i32, scale_milli: i32) {
	let _ = GESTURE_APP.set(app);
	GESTURE_CENTER_X.store(center_x, Ordering::Relaxed);
	GESTURE_TOP_Y.store(top_y, Ordering::Relaxed);
	GESTURE_SCALE_MILLI.store(scale_milli.max(1), Ordering::Relaxed);
	let _ = std::thread::Builder::new()
		.name("onyx-notch-gesture-hook".into())
		.spawn(move || unsafe {
			let mut message = MSG::default();
			let _ = PeekMessageW(&mut message, None, 0, 0, PM_NOREMOVE);
			let hook = match SetWindowsHookExW(WH_MOUSE_LL, Some(mouse_gesture_hook), None, 0) {
				Ok(hook) => hook,
				Err(error) => {
					eprintln!("Onyx: impossibile installare il rilevatore gesti: {error}");
					return;
				}
			};
			log_gesture(&format!("hook installato centro={center_x} alto={top_y} scala_millesimi={scale_milli}"));
			while GetMessageW(&mut message, None, 0, 0).0 > 0 {
				let _ = TranslateMessage(&message);
				DispatchMessageW(&message);
			}
			let _ = UnhookWindowsHookEx(hook);
		});
}

#[derive(Clone, Deserialize, Serialize)]
struct VoiceEvent {
	sequence: u64,
	state: String,
	message: String,
}

#[derive(Clone, Default)]
struct BridgeState {
	ready: Arc<AtomicBool>,
	pending: Arc<Mutex<Option<VoiceEvent>>>,
}

fn publish_or_cache(app: &tauri::AppHandle, bridge: &BridgeState, event: VoiceEvent) {
	let Ok(mut pending) = bridge.pending.lock() else {
		return;
	};
	if bridge.ready.load(Ordering::Acquire) {
		drop(pending);
		let _ = app.emit("onyx-state", event);
	} else {
		// Keep the newest state until React subscribes. Partial transcripts replace
		// each other, so retaining the last one is enough to recover the current UI.
		*pending = Some(event);
	}
}

#[tauri::command]
fn ui_ready(app: tauri::AppHandle, bridge: State<'_, BridgeState>) {
	let Ok(mut pending) = bridge.pending.lock() else {
		return;
	};
	bridge.ready.store(true, Ordering::Release);
	if let Some(event) = pending.take() {
		drop(pending);
		let _ = app.emit("onyx-state", event);
	}
}

#[tauri::command]
fn latest_ui_state() -> Result<VoiceEvent, String> {
	let path = std::env::current_dir()
		.map_err(|error| error.to_string())?
		.join("logs/onyx-ui-state.json");
	let contents = match fs::read_to_string(path) {
		Ok(contents) => contents,
		Err(error) if error.kind() == io::ErrorKind::NotFound => {
			return Ok(VoiceEvent {
				sequence: 0,
				state: "hide".into(),
				message: String::new(),
			});
		}
		Err(error) => return Err(error.to_string()),
	};
	serde_json::from_str(&contents).map_err(|error| error.to_string())
}

#[tauri::command]
fn timer_control(action: String, timer_id: String) -> Result<(), String> {
	if !matches!(action.as_str(), "pause" | "resume" | "cancel" | "stop-alarm") {
		return Err("Comando timer non valido".into());
	}
	if timer_id.is_empty() || !timer_id.chars().all(|character| character.is_ascii_alphanumeric() || character == '-' || character == '_') {
		return Err("Identificativo timer non valido".into());
	}
	let path = std::env::current_dir().map_err(|e| e.to_string())?.join(format!("logs/onyx-timer-control-{timer_id}.txt"));
	fs::create_dir_all(path.parent().ok_or("Percorso timer non valido")?).map_err(|e| e.to_string())?;
	fs::write(path, action).map_err(|e| e.to_string())
}

#[tauri::command]
fn start_timer(seconds: u32, timer_id: String) -> Result<(), String> {
	if seconds == 0 || seconds > 24 * 60 * 60 {
		return Err("Durata timer non valida".into());
	}
	if timer_id.is_empty() || !timer_id.chars().all(|character| character.is_ascii_alphanumeric() || character == '-' || character == '_') {
		return Err("Identificativo timer non valido".into());
	}
	let path = std::env::current_dir().map_err(|e| e.to_string())?.join(format!("logs/onyx-timer-start-{timer_id}.txt"));
	let parent = path.parent().ok_or("Percorso timer non valido")?;
	fs::create_dir_all(parent).map_err(|e| e.to_string())?;
	fs::write(path, seconds.to_string()).map_err(|e| e.to_string())
}

#[tauri::command]
fn system_action(action: String, value: Option<i32>) -> Result<(), String> {
	if !matches!(action.as_str(), "status" | "brightness-set" | "volume-up" | "volume-down" | "wifi-toggle" | "bluetooth-toggle" | "airplane-toggle") {
		return Err("Comando di sistema non valido".into());
	}
	let payload = serde_json::json!({ "action": action, "value": value });
	let path = std::env::current_dir().map_err(|e| e.to_string())?.join("logs/onyx-system-control.json");
	let parent = path.parent().ok_or("Percorso controlli non valido")?;
	fs::create_dir_all(parent).map_err(|e| e.to_string())?;
	let temporary = parent.join(format!("onyx-system-control.{}.tmp", std::process::id()));
	fs::write(&temporary, serde_json::to_vec(&payload).map_err(|e| e.to_string())?)
		.map_err(|e| e.to_string())?;
	if path.exists() {
		let _ = fs::remove_file(&path);
	}
	fs::rename(temporary, path).map_err(|e| e.to_string())
}

#[tauri::command]
fn set_window_region(window: &WebviewWindow, interactive: bool, capture_gesture: bool) -> Result<(), String> {
	let hwnd = window.hwnd().map_err(|error| error.to_string())?;
	let region = if capture_gesture || interactive {
		let width = window.inner_size().map_err(|error| error.to_string())?.width as i32;
		let scale = window.scale_factor().unwrap_or(1.0).max(1.0);
		let (logical_half_width, logical_height) = if interactive {
			(EXPANDED_HALF_WIDTH, EXPANDED_HEIGHT)
		} else {
			(ACTIVATION_HALF_WIDTH, ACTIVATION_HEIGHT)
		};
		let half_width = (logical_half_width as f64 * scale).round() as i32;
		let height = (logical_height as f64 * scale).round() as i32;
		let region = unsafe { CreateRectRgn(width / 2 - half_width, 0, width / 2 + half_width, height) };
		if region.0.is_null() {
			return Err("Impossibile creare la regione di input del notch".into());
		}
		Some(region)
	} else {
		None
	};
	unsafe {
		if SetWindowRgn(hwnd, region, true) == 0 {
			if let Some(region) = region {
				let _ = DeleteObject(region.into());
			}
			return Err("Impossibile aggiornare la regione di input del notch".into());
		}
	}
	Ok(())
}

#[tauri::command]
fn set_overlay_interactive(app: tauri::AppHandle, interactive: bool, capture_gesture: bool) -> Result<(), String> {
	let window = app
		.get_webview_window("main")
		.ok_or_else(|| "Finestra Onyx non disponibile".to_string())?;
	set_window_region(&window, interactive, capture_gesture)?;
	window
		.set_ignore_cursor_events(!interactive && !capture_gesture)
		.map_err(|error| error.to_string())
}

#[tauri::command]
fn set_gesture_enabled(enabled: bool) {
	GESTURE_ENABLED.store(enabled, Ordering::Relaxed);
	log_gesture(if enabled { "modalita=attiva" } else { "modalita=disattiva" });
	let was_hovered = GESTURE_HOVERED.swap(enabled, Ordering::Relaxed);
	if !enabled && was_hovered {
		emit_gesture("disable");
	}
}

#[tauri::command]
fn log_overlay_ui_state(gesture_enabled: bool, hover_expanded: bool, voice_state: String, active_panel: String) {
	let voice = match voice_state.as_str() {
		"hidden" | "orb" | "wake" | "partial" | "processing" | "success" | "error" => voice_state.as_str(),
		_ => "unknown",
	};
	let panel = match active_panel.as_str() {
		"clock" | "timer" | "timer-setup" | "stopwatch" | "pomodoro" | "alarm" | "calendar" | "controls" => active_panel.as_str(),
		_ => "unknown",
	};
	log_gesture(&format!("ui gesture_enabled={gesture_enabled} hover_expanded={hover_expanded} voice={voice} panel={panel}"));
}

#[tauri::command]
fn log_overlay_wheel(delta_x: f64, delta_y: f64) {
	if delta_x.is_finite() && delta_y.is_finite() && (delta_x.abs() >= 2.0 || delta_y.abs() >= 2.0) {
		log_gesture(&format!("ui-wheel delta_x={delta_x:.1} delta_y={delta_y:.1}"));
	}
}

fn main() {
	tauri::Builder::default()
		.manage(BridgeState::default())
		.invoke_handler(tauri::generate_handler![ui_ready, latest_ui_state, timer_control, start_timer, system_action, set_overlay_interactive, set_gesture_enabled, log_overlay_ui_state, log_overlay_wheel])
		.setup(|app| {
			let mut gesture_center_x = 0;
			let mut gesture_top_y = 0;
			let mut gesture_scale_milli = 1000;
			if let Some(window) = app.get_webview_window("main") {
				// Keep only the visible notch hit-testable while idle; the rest of the
				// transparent overlay remains click-through.
				let _ = window.set_ignore_cursor_events(false);
				let monitor = window
					.current_monitor()
					.ok()
					.flatten()
					.or_else(|| window.primary_monitor().ok().flatten());
				if let Some(monitor) = monitor {
					let scale = monitor.scale_factor();
					gesture_scale_milli = (scale * 1000.0).round() as i32;
					let size = monitor.size();
					let position = monitor.position();
					let window_width = 1100.0_f64.min(size.width as f64 / scale);
					gesture_center_x = position.x + (size.width as f64 / 2.0) as i32;
					gesture_top_y = position.y;
					let _ = window.set_size(LogicalSize::new(window_width, 340.0));
					let _ = window.set_position(LogicalPosition::new(
						position.x as f64 / scale + (size.width as f64 / scale - window_width) / 2.0,
						position.y as f64 / scale,
					));
				}
				if let Err(error) = set_window_region(&window, false, true) {
					log_gesture(&format!("regione notch non applicata: {error}"));
				}
			}
			start_mouse_gesture_hook(app.handle().clone(), gesture_center_x, gesture_top_y, gesture_scale_milli);

			let app_handle = app.handle().clone();
			let bridge = app.state::<BridgeState>().inner().clone();
			std::thread::Builder::new()
				.name("onyx-voice-ui-bridge".into())
				.spawn(move || {
					for line in io::stdin().lock().lines() {
						let Ok(line) = line else { break };
						if line.trim() == "QUIT" {
						app_handle.exit(0);
						return;
					}

						let Some((sequence, event)) = line.split_once('|') else {
							continue;
						};
						let Ok(sequence) = sequence.trim().parse::<u64>() else {
							continue;
						};
						let Some((state, encoded)) = event.split_once('|') else {
							continue;
						};
						if !matches!(state, "wake" | "partial" | "processing" | "success" | "error" | "hide" | "timer" | "timer-end" | "timer-pause" | "timer-resume" | "timer-cancel" | "alarm-stop" | "stopwatch-open" | "stopwatch-pause" | "stopwatch-resume" | "stopwatch-lap" | "stopwatch-reset" | "system-result") {
							continue;
						}
						let Ok(bytes) = STANDARD.decode(encoded.trim()) else {
							continue;
						};
						let message = String::from_utf8_lossy(&bytes).into_owned();
						publish_or_cache(
							&app_handle,
							&bridge,
							VoiceEvent {
								sequence,
								state: state.to_string(),
								message,
							},
						);
					}
					app_handle.exit(0);
				})?;
			Ok(())
		})
		.run(tauri::generate_context!())
		.expect("Impossibile avviare l'interfaccia Bloom di Onyx");
}
