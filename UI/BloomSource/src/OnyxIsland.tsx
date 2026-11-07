import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useCallback, useEffect, useRef, useState, type CSSProperties, type WheelEvent } from "react";
import { ThinkingOrb, type OrbState } from "thinking-orbs";
import { EdgeSurface } from "./components/EdgeSurface";
import "./OnyxIsland.css";

type VoiceState = "hidden" | "orb" | "wake" | "partial" | "processing" | "success" | "error";
type NotchPanel = "clock" | "timer" | "timer-setup" | "stopwatch" | "pomodoro" | "alarm" | "calendar" | "controls";
const VOICE_STATES = new Set<VoiceState>(["wake", "partial", "processing", "success", "error"]);

function isVoiceState(state: VoiceEvent["state"]): state is Exclude<VoiceState, "hidden" | "orb"> {
	return VOICE_STATES.has(state as Exclude<VoiceState, "hidden" | "orb">);
}

interface VoiceEvent {
	sequence: number;
	state: Exclude<VoiceState, "hidden" | "orb"> | "hide" | "timer" | "timer-end" | "timer-pause" | "timer-resume" | "timer-cancel" | "alarm-stop" | "stopwatch-open" | "stopwatch-pause" | "stopwatch-resume" | "stopwatch-lap" | "stopwatch-reset" | "system-result";
	message: string;
}

type SoundCue = "entry" | "exit" | "error";

interface TimerSnapshot {
	durationSeconds: number;
	remainingMs: number;
	updatedAt: number;
	paused: boolean;
	alarm: boolean;
}

interface TimerCard extends TimerSnapshot {
	id: string;
}

interface StopwatchSnapshot {
	elapsedMs: number;
	updatedAt: number;
	running: boolean;
}

interface SystemControlState {
	brightness: number | null;
	wifi: boolean | null;
	bluetooth: boolean | null;
	airplane: boolean | null;
}

interface CalendarEntry {
	id: string;
	date: string;
	time: string;
	title: string;
}

const TIMER_STORAGE_KEY = "onyx-active-timer-v1";
const TIMER_LIST_STORAGE_KEY = "onyx-active-timers-v2";
const STOPWATCH_STORAGE_KEY = "onyx-stopwatch-v1";
const GESTURE_ENABLED_KEY = "onyx-notch-gestures-enabled-v1";
const CALENDAR_STORAGE_KEY = "onyx-calendar-events-v1";

function readCalendarEntries(): CalendarEntry[] {
	try {
		const value = JSON.parse(localStorage.getItem(CALENDAR_STORAGE_KEY) ?? "[]") as CalendarEntry[];
		return Array.isArray(value) ? value.filter((entry) => entry && typeof entry.id === "string" && typeof entry.date === "string" && typeof entry.time === "string" && typeof entry.title === "string") : [];
	} catch {
		return [];
	}
}

function readStopwatchSnapshot(): StopwatchSnapshot {
	try {
		const raw = localStorage.getItem(STOPWATCH_STORAGE_KEY);
		if (!raw) return { elapsedMs: 0, updatedAt: Date.now(), running: false };
		const value = JSON.parse(raw) as Partial<StopwatchSnapshot>;
		if (!Number.isFinite(value.elapsedMs) || !Number.isFinite(value.updatedAt)) {
			localStorage.removeItem(STOPWATCH_STORAGE_KEY);
			return { elapsedMs: 0, updatedAt: Date.now(), running: false };
		}
		const elapsedMs = Math.max(0, Number(value.elapsedMs)) + (value.running ? Math.max(0, Date.now() - Number(value.updatedAt)) : 0);
		return { elapsedMs, updatedAt: Date.now(), running: Boolean(value.running) };
	} catch {
		return { elapsedMs: 0, updatedAt: Date.now(), running: false };
	}
}

function writeStopwatchSnapshot(elapsedMs: number, running: boolean) {
	try {
		localStorage.setItem(STOPWATCH_STORAGE_KEY, JSON.stringify({ elapsedMs, updatedAt: Date.now(), running } satisfies StopwatchSnapshot));
	} catch (error) {
		console.warn("Onyx: impossibile salvare lo stato del cronometro:", error);
	}
}

function readTimerSnapshot(): { snapshot: TimerSnapshot; remainingMs: number } | null {
	try {
		const raw = localStorage.getItem(TIMER_STORAGE_KEY);
		if (!raw) return null;
		const value = JSON.parse(raw) as Partial<TimerSnapshot>;
		if (!Number.isFinite(value.durationSeconds) || !Number.isFinite(value.remainingMs) || !Number.isFinite(value.updatedAt)) {
			localStorage.removeItem(TIMER_STORAGE_KEY);
			return null;
		}
		const now = Date.now();
		const elapsedWhileRunning = value.paused || value.alarm ? 0 : Math.max(0, now - Number(value.updatedAt));
		const remainingMs = value.alarm ? 0 : Math.max(0, Number(value.remainingMs) - elapsedWhileRunning);
		const snapshot: TimerSnapshot = {
			durationSeconds: Number(value.durationSeconds),
			remainingMs,
			updatedAt: now,
			paused: Boolean(value.paused),
			alarm: Boolean(value.alarm) || (!value.paused && remainingMs === 0)
		};
		localStorage.setItem(TIMER_STORAGE_KEY, JSON.stringify(snapshot));
		return { snapshot, remainingMs };
	} catch {
		return null;
	}
}

function writeTimerSnapshot(snapshot: TimerSnapshot | null) {
	try {
		if (snapshot) localStorage.setItem(TIMER_STORAGE_KEY, JSON.stringify(snapshot));
		else localStorage.removeItem(TIMER_STORAGE_KEY);
	} catch (error) {
		console.warn("Onyx: impossibile salvare lo stato del timer:", error);
	}
}

function readTimerCards(legacy: { snapshot: TimerSnapshot; remainingMs: number } | null): TimerCard[] {
	try {
		const raw = localStorage.getItem(TIMER_LIST_STORAGE_KEY);
		if (raw) {
			const items = JSON.parse(raw) as Array<Partial<TimerCard>>;
			if (Array.isArray(items)) {
				const now = Date.now();
				const restored = items.filter((item) => typeof item.id === "string" && Number.isFinite(item.durationSeconds) && Number.isFinite(item.remainingMs) && Number.isFinite(item.updatedAt))
					.map((item) => {
						const durationSeconds = Math.max(1, Number(item.durationSeconds));
						const alarm = Boolean(item.alarm);
						const paused = Boolean(item.paused);
						const remainingMs = alarm ? 0 : Math.max(0, Number(item.remainingMs) - (paused ? 0 : Math.max(0, now - Number(item.updatedAt))));
						return { id: item.id as string, durationSeconds, remainingMs, updatedAt: now, paused, alarm: alarm || (!paused && remainingMs === 0) };
					});
				if (restored.length) return restored;
			}
		}
	} catch {
		localStorage.removeItem(TIMER_LIST_STORAGE_KEY);
	}
	return legacy ? [{ id: "legacy", ...legacy.snapshot, remainingMs: legacy.remainingMs, updatedAt: Date.now() }] : [];
}

function writeTimerCards(cards: TimerCard[]) {
	try {
		localStorage.setItem(TIMER_LIST_STORAGE_KEY, JSON.stringify(cards));
		if (cards.length === 0) localStorage.removeItem(TIMER_STORAGE_KEY);
	} catch (error) {
		console.warn("Onyx: impossibile salvare i timer attivi:", error);
	}
}

export default function OnyxIsland() {
	const [restoredTimer] = useState(readTimerSnapshot);
	const [restoredTimerCards] = useState(() => readTimerCards(restoredTimer));
	const firstRestoredTimer = restoredTimerCards[0] ?? null;
	const [restoredStopwatch] = useState(readStopwatchSnapshot);
	const [clockNow, setClockNow] = useState(() => new Date());
	const [gestureEnabled, setGestureEnabled] = useState(() => localStorage.getItem(GESTURE_ENABLED_KEY) === "true");
	const [hoverExpanded, setHoverExpanded] = useState(false);
	const [gestureExpanded, setGestureExpanded] = useState(false);
	const islandExpanded = hoverExpanded || gestureExpanded;
	const [activePanel, setActivePanel] = useState<NotchPanel>("clock");
	const restoredDuration = firstRestoredTimer?.durationSeconds ?? 0;
	const restoredRemaining = firstRestoredTimer?.remainingMs ?? 0;
	const [voiceState, setVoiceState] = useState<VoiceState>("hidden");
	const [transcript, setTranscript] = useState("");
	const [errorPulse, setErrorPulse] = useState(0);
	const [timerVisible, setTimerVisible] = useState(restoredTimerCards.length > 0);
	const [timerCompact, setTimerCompact] = useState(false);
	const [timerAlarm, setTimerAlarm] = useState(() => firstRestoredTimer?.alarm ?? false);
	const [timerSeconds, setTimerSeconds] = useState(() => Math.ceil(restoredRemaining / 1000));
	const [timerDuration, setTimerDuration] = useState(restoredDuration);
	const [timerPaused, setTimerPaused] = useState(() => firstRestoredTimer?.paused ?? false);
	const [timerCards, setTimerCards] = useState<TimerCard[]>(restoredTimerCards);
	const [selectedTimerId, setSelectedTimerId] = useState(firstRestoredTimer?.id ?? "");
	const [stopwatchVisible, setStopwatchVisible] = useState(false);
	const [stopwatchCompact, setStopwatchCompact] = useState(false);
	const [stopwatchRunning, setStopwatchRunning] = useState(restoredStopwatch.running);
	const [stopwatchElapsedMs, setStopwatchElapsedMs] = useState(restoredStopwatch.elapsedMs);
	const [stopwatchLaps, setStopwatchLaps] = useState<number[]>([]);
	const [calendarMonth, setCalendarMonth] = useState(() => new Date(new Date().getFullYear(), new Date().getMonth(), 1));
	const [calendarDay, setCalendarDay] = useState(() => new Date().getDate());
	const [calendarEntries, setCalendarEntries] = useState<CalendarEntry[]>(readCalendarEntries);
	const [calendarTitleInput, setCalendarTitleInput] = useState("");
	const [calendarTimeInput, setCalendarTimeInput] = useState("09:00");
	const [timerMinutesInput, setTimerMinutesInput] = useState("10");
	const [alarmTimeInput, setAlarmTimeInput] = useState(() => {
		const next = new Date(Date.now() + 60 * 60 * 1000);
		return `${String(next.getHours()).padStart(2, "0")}:${String(next.getMinutes()).padStart(2, "0")}`;
	});
	const [timerSetupMessage, setTimerSetupMessage] = useState("");
	const [controlState, setControlState] = useState<SystemControlState>({ brightness: null, wifi: null, bluetooth: null, airplane: null });
	const [controlBusy, setControlBusy] = useState(false);
	const [controlMessage, setControlMessage] = useState("");
	const timerElapsedMs = useRef(restoredDuration * 1000 - restoredRemaining);
	const timerDurationRef = useRef(restoredDuration);
	const timerPausedRef = useRef(firstRestoredTimer?.paused ?? false);
	const timerAlarmRef = useRef(firstRestoredTimer?.alarm ?? false);
	const timerCardsRef = useRef<TimerCard[]>(restoredTimerCards);
	const selectedTimerIdRef = useRef(firstRestoredTimer?.id ?? "");
	const stopwatchElapsedRef = useRef(restoredStopwatch.elapsedMs);
	const stopwatchRunningRef = useRef(restoredStopwatch.running);
	const stopwatchStartedAtRef = useRef(performance.now() - restoredStopwatch.elapsedMs);
	const alarmOrbPinnedRef = useRef(false);
	const voiceStateRef = useRef<VoiceState>("hidden");
	const lastEventSequence = useRef(0);
	const timerIslandRef = useRef<HTMLDivElement | null>(null);
	const timerActiveRef = useRef(restoredTimerCards.length > 0);
	const controlStatusRequestedRef = useRef(false);
	const gestureWheelRef = useRef<{ deltaX: number; deltaY: number; timer: number | null }>({ deltaX: 0, deltaY: 0, timer: null });
	const reducedMotion = useReducedMotion();
	const successTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
	const brightnessTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
	const sounds = useRef<Record<SoundCue, HTMLAudioElement> | null>(null);

	useEffect(() => {
		const players: Record<SoundCue, HTMLAudioElement> = {
			entry: new Audio("/sounds/in.mp3"),
			exit: new Audio("/sounds/out.mp3"),
			error: new Audio("/sounds/non-ho-capito.mp3")
		};
		Object.values(players).forEach((player) => {
			player.preload = "auto";
			player.volume = 0.68;
		});
		sounds.current = players;

		return () => {
			Object.values(players).forEach((player) => {
				player.pause();
				player.removeAttribute("src");
				player.load();
			});
			sounds.current = null;
		};
	}, []);

	useEffect(() => {
		const clock = window.setInterval(() => setClockNow(new Date()), 1000);
		return () => window.clearInterval(clock);
	}, []);

	const focusTimer = useCallback((timerId: string) => {
		const timer = timerCardsRef.current.find((item) => item.id === timerId);
		if (!timer) return;
		const remainingMs = timer.alarm ? 0 : Math.max(0, timer.remainingMs - (timer.paused ? 0 : Date.now() - timer.updatedAt));
		selectedTimerIdRef.current = timer.id;
		timerDurationRef.current = timer.durationSeconds;
		timerElapsedMs.current = Math.max(0, timer.durationSeconds * 1000 - remainingMs);
		timerPausedRef.current = timer.paused;
		timerAlarmRef.current = timer.alarm;
		setSelectedTimerId(timer.id);
		setTimerVisible(true);
		setTimerDuration(timer.durationSeconds);
		setTimerSeconds(Math.ceil(remainingMs / 1000));
		setTimerPaused(timer.paused);
		setTimerAlarm(timer.alarm);
		setTimerCompact(false);
		setActivePanel("timer");
		timerIslandRef.current?.style.setProperty("--timer-progress", String(timer.alarm ? 1 : Math.min(1, 1 - remainingMs / (timer.durationSeconds * 1000))));
	}, []);

	const cycleGesturePanel = useCallback((direction: 1 | -1) => {
		const pages: Array<{ panel: NotchPanel; timerId?: string }> = [
			{ panel: "clock" },
			...timerCards.map((timer) => ({ panel: "timer" as const, timerId: timer.id })),
			{ panel: "timer-setup" },
			...(stopwatchVisible ? [{ panel: "stopwatch" as const }] : []),
			{ panel: "pomodoro" }, { panel: "alarm" }, { panel: "calendar" }, { panel: "controls" }
		];
		const pageIndex = pages.findIndex((page) => page.panel === activePanel && (page.panel !== "timer" || page.timerId === selectedTimerId));
		const nextPage = pages[(Math.max(0, pageIndex) + direction + pages.length) % pages.length];
		if (nextPage.panel === "timer" && nextPage.timerId) focusTimer(nextPage.timerId);
		setActivePanel(nextPage.panel);
	}, [activePanel, focusTimer, selectedTimerId, stopwatchVisible, timerCards]);

	const handleGestureWheel = useCallback((event: WheelEvent<HTMLDivElement>) => {
		const target = event.target as HTMLElement;
		if (target.closest("button, input, textarea, select, [contenteditable='true'], .onyx-calendar-grid, .onyx-calendar-events")) return;
		if (!Number.isFinite(event.deltaX) || !Number.isFinite(event.deltaY)
			|| (Math.abs(event.deltaX) < 1 && Math.abs(event.deltaY) < 1)) return;
		event.preventDefault();
		const gesture = gestureWheelRef.current;
		gesture.deltaX += event.deltaX;
		gesture.deltaY += event.deltaY;
		if (gesture.timer !== null) window.clearTimeout(gesture.timer);
		gesture.timer = window.setTimeout(() => {
			const { deltaX, deltaY } = gesture;
			gesture.deltaX = 0;
			gesture.deltaY = 0;
			gesture.timer = null;
			if (Math.abs(deltaX) < 2 && Math.abs(deltaY) < 2) return;

			void invoke("log_overlay_wheel", { deltaX, deltaY })
				.catch((error: unknown) => console.error("Onyx touchpad log:", error));

			if (Math.abs(deltaY) > Math.abs(deltaX) * 1.15) {
				if (!islandExpanded) {
					setGestureEnabled(true);
					setGestureExpanded(true);
					setActivePanel("clock");
				} else if (deltaY > 0) {
					setGestureEnabled(false);
					setGestureExpanded(false);
					setHoverExpanded(false);
					setActivePanel("clock");
				} else {
					setGestureExpanded(true);
				}
				return;
			}
			if (islandExpanded && Math.abs(deltaX) >= Math.abs(deltaY) * 0.85) cycleGesturePanel(deltaX > 0 ? 1 : -1);
		}, 380);
	}, [cycleGesturePanel, islandExpanded]);

	useEffect(() => () => {
		const timer = gestureWheelRef.current.timer;
		if (timer !== null) window.clearTimeout(timer);
	}, []);

	useEffect(() => {
		localStorage.setItem(GESTURE_ENABLED_KEY, String(gestureEnabled));
		void invoke("set_gesture_enabled", { enabled: gestureEnabled })
			.catch((error: unknown) => console.error("Onyx notch gestures:", error));
	}, [gestureEnabled]);

	useEffect(() => {
		void invoke("log_overlay_ui_state", { gestureEnabled, hoverExpanded: islandExpanded, voiceState, activePanel })
			.catch((error: unknown) => console.error("Onyx overlay state log:", error));
	}, [activePanel, gestureEnabled, islandExpanded, voiceState]);

	useEffect(() => {
		let cancelled = false;
		let unlisten: (() => void) | undefined;
		listen<string>("onyx-gesture", ({ payload }) => {
			if (payload === "enable") {
				setGestureEnabled(true);
				setActivePanel("clock");
			} else if (payload === "disable") {
				setGestureEnabled(false);
				setHoverExpanded(false);
				setGestureExpanded(false);
				setTimerCompact(timerActiveRef.current);
				setStopwatchCompact(true);
			} else if (payload === "hover-enter") {
				setHoverExpanded(true);
			} else if (payload === "hover-leave") {
				setHoverExpanded(false);
				if (!gestureExpanded) {
					setActivePanel("clock");
					setTimerCompact(timerActiveRef.current);
					setStopwatchCompact(true);
				}
			} else if (payload === "next" || payload === "previous") {
				cycleGesturePanel(payload === "next" ? 1 : -1);
			}
		}).then((stop) => {
			if (cancelled) stop();
			else unlisten = stop;
		}).catch((error: unknown) => console.error("Onyx gesture listener:", error));
		return () => {
			cancelled = true;
			unlisten?.();
		};
	}, [cycleGesturePanel, gestureExpanded]);

	useEffect(() => {
		setTimerCompact(timerVisible && activePanel !== "timer");
		setStopwatchCompact(stopwatchVisible && activePanel !== "stopwatch");
	}, [activePanel, stopwatchVisible, timerVisible]);

	useEffect(() => {
		const selected = timerCardsRef.current.find((timer) => timer.id === selectedTimerId);
		if (!selected) return;
		const remainingMs = selected.alarm ? 0 : Math.max(0, selected.remainingMs - (selected.paused ? 0 : Date.now() - selected.updatedAt));
		selectedTimerIdRef.current = selected.id;
		timerDurationRef.current = selected.durationSeconds;
		timerElapsedMs.current = Math.max(0, selected.durationSeconds * 1000 - remainingMs);
		timerPausedRef.current = selected.paused;
		timerAlarmRef.current = selected.alarm;
		timerActiveRef.current = true;
		setTimerVisible(true);
		setTimerDuration(selected.durationSeconds);
		setTimerSeconds(Math.ceil(remainingMs / 1000));
		setTimerPaused(selected.paused);
		setTimerAlarm(selected.alarm);
	}, [selectedTimerId]);

	const playCue = useCallback((cue: SoundCue) => {
		const players = sounds.current;
		if (!players) return;

		Object.entries(players).forEach(([name, player]) => {
			if (name !== cue) {
				player.pause();
				player.currentTime = 0;
			}
		});

		const player = players[cue];
		player.pause();
		player.currentTime = 0;
		void player.play().catch((error: unknown) => {
			console.warn(`Onyx audio cue '${cue}' non riprodotto:`, error);
		});
	}, []);

	const stopCues = useCallback(() => {
		Object.values(sounds.current ?? {}).forEach((player) => {
			player.pause();
			player.currentTime = 0;
		});
	}, []);

	const setVoiceStateTracked = useCallback((state: VoiceState) => {
		voiceStateRef.current = state;
		setVoiceState(state);
	}, []);

	const updateTimerCards = useCallback((updater: (current: TimerCard[]) => TimerCard[]) => {
		const next = updater(timerCardsRef.current);
		timerCardsRef.current = next;
		setTimerCards(next);
		writeTimerCards(next);
		timerActiveRef.current = next.length > 0;
	}, []);

	const persistTimerState = useCallback((paused: boolean, alarm = false) => {
		const durationSeconds = timerDurationRef.current;
		if (durationSeconds <= 0) return;
		const durationMs = durationSeconds * 1000;
		const remainingMs = alarm ? 0 : Math.max(0, durationMs - timerElapsedMs.current);
		const updatedAt = Date.now();
		writeTimerSnapshot({ durationSeconds, remainingMs, updatedAt, paused, alarm });
		const id = selectedTimerIdRef.current;
		if (id) updateTimerCards((current) => current.map((timer) => timer.id === id ? { ...timer, durationSeconds, remainingMs, updatedAt, paused, alarm } : timer));
	}, [updateTimerCards]);

	const clearTimerState = useCallback((timerId = selectedTimerIdRef.current) => {
		const remaining = timerCardsRef.current.filter((timer) => timer.id !== timerId);
		updateTimerCards(() => remaining);
		setTimerVisible(remaining.length > 0);
		if (selectedTimerIdRef.current === timerId) {
			const next = remaining[0];
			selectedTimerIdRef.current = next?.id ?? "";
			setSelectedTimerId(next?.id ?? "");
			timerDurationRef.current = next?.durationSeconds ?? 0;
			timerElapsedMs.current = next ? next.durationSeconds * 1000 - next.remainingMs : 0;
			timerPausedRef.current = next?.paused ?? false;
			timerAlarmRef.current = next?.alarm ?? false;
			setTimerDuration(next?.durationSeconds ?? 0);
			setTimerSeconds(next ? Math.ceil(next.remainingMs / 1000) : 0);
			setTimerPaused(next?.paused ?? false);
			setTimerAlarm(next?.alarm ?? false);
		}
		alarmOrbPinnedRef.current = false;
		if (!remaining.length) writeTimerSnapshot(null);
		setTimerCompact(remaining.length > 0 && activePanel !== "timer");
		setTranscript("");
		setVoiceStateTracked("hidden");
	}, [activePanel, setVoiceStateTracked, updateTimerCards]);

	const clearAlarmTimers = useCallback(() => {
		const remaining = timerCardsRef.current.filter((timer) => !timer.alarm);
		updateTimerCards(() => remaining);
		if (timerAlarmRef.current) clearTimerState(selectedTimerIdRef.current);
	}, [clearTimerState, updateTimerCards]);

	const saveStopwatch = useCallback((elapsedMs: number, running: boolean) => {
		stopwatchElapsedRef.current = elapsedMs;
		stopwatchRunningRef.current = running;
		setStopwatchElapsedMs(elapsedMs);
		setStopwatchRunning(running);
		writeStopwatchSnapshot(elapsedMs, running);
	}, []);

	const saveCalendarEntry = useCallback(() => {
		const title = calendarTitleInput.trim();
		if (!title) return;
		const date = `${calendarMonth.getFullYear()}-${String(calendarMonth.getMonth() + 1).padStart(2, "0")}-${String(calendarDay).padStart(2, "0")}`;
		const next = [...calendarEntries, { id: crypto.randomUUID(), date, time: calendarTimeInput, title }].sort((a, b) => a.date.localeCompare(b.date) || a.time.localeCompare(b.time));
		setCalendarEntries(next);
		localStorage.setItem(CALENDAR_STORAGE_KEY, JSON.stringify(next));
		setCalendarTitleInput("");
	}, [calendarDay, calendarEntries, calendarMonth, calendarTimeInput, calendarTitleInput]);

	const removeCalendarEntry = useCallback((id: string) => {
		const next = calendarEntries.filter((entry) => entry.id !== id);
		setCalendarEntries(next);
		localStorage.setItem(CALENDAR_STORAGE_KEY, JSON.stringify(next));
	}, [calendarEntries]);

	const pauseStopwatch = useCallback(() => {
		if (!stopwatchRunningRef.current) return;
		const elapsed = Math.max(0, performance.now() - stopwatchStartedAtRef.current);
		saveStopwatch(elapsed, false);
	}, [saveStopwatch]);

	const resumeStopwatch = useCallback(() => {
		if (stopwatchRunningRef.current) return;
		stopwatchStartedAtRef.current = performance.now() - stopwatchElapsedRef.current;
		saveStopwatch(stopwatchElapsedRef.current, true);
	}, [saveStopwatch]);

	const recordStopwatchLap = useCallback(() => {
		if (!stopwatchRunningRef.current) return;
		const elapsed = Math.max(0, performance.now() - stopwatchStartedAtRef.current);
		stopwatchElapsedRef.current = elapsed;
		setStopwatchElapsedMs(elapsed);
		setStopwatchLaps((laps) => [elapsed, ...laps].slice(0, 8));
		writeStopwatchSnapshot(elapsed, true);
	}, []);

	const resetStopwatch = useCallback(() => {
		stopwatchStartedAtRef.current = performance.now();
		setStopwatchLaps([]);
		saveStopwatch(0, false);
	}, [saveStopwatch]);

	const requestSystemAction = useCallback((action: string, value?: number) => {
		setControlBusy(true);
		setControlMessage("Applico la modifica…");
		void invoke("system_action", { action, value: value ?? null }).catch((error: unknown) => {
			setControlBusy(false);
			setControlMessage(`Errore: ${String(error)}`);
		});
	}, []);

	const startTimerFromPanel = useCallback((seconds: number) => {
		setTimerSetupMessage("Avvio timer…");
		setActivePanel("timer");
		const timerId = crypto.randomUUID().replace(/-/g, "");
		void invoke("start_timer", { seconds, timerId }).catch((error: unknown) => {
			setTimerSetupMessage(`Errore: ${String(error)}`);
		});
	}, []);

	useEffect(() => () => {
		if (brightnessTimeoutRef.current) clearTimeout(brightnessTimeoutRef.current);
	}, []);

	useEffect(() => {
		if (activePanel !== "controls" || !islandExpanded) {
			controlStatusRequestedRef.current = false;
			return;
		}
		if (!controlStatusRequestedRef.current) {
			controlStatusRequestedRef.current = true;
			requestSystemAction("status");
		}
	}, [activePanel, islandExpanded, requestSystemAction]);

	const handleVoiceEvent = useCallback(({ sequence, state, message }: VoiceEvent) => {
		if (sequence <= lastEventSequence.current) return;
		lastEventSequence.current = sequence;
		if (successTimer.current) clearTimeout(successTimer.current);
		if (state.startsWith("stopwatch-")) {
			setStopwatchVisible(true);
			setStopwatchCompact(false);
			setActivePanel("stopwatch");
			setTranscript("");
			if (state === "stopwatch-open") {
				setVoiceStateTracked("hidden");
				return;
			}
			if (state === "stopwatch-pause") pauseStopwatch();
			if (state === "stopwatch-resume") resumeStopwatch();
			if (state === "stopwatch-lap") recordStopwatchLap();
			if (state === "stopwatch-reset") resetStopwatch();
			setVoiceStateTracked("hidden");
			return;
		}
		if (state === "system-result") {
			try {
				const result = JSON.parse(message) as { ok?: boolean; message?: string; state?: Partial<SystemControlState> };
				if (result.state) setControlState((current) => ({ ...current, ...result.state }));
				setControlMessage(result.message ?? (result.ok ? "Modifica completata." : "Non sono riuscito ad applicare la modifica."));
			} catch {
				setControlMessage("Risposta del controllo non leggibile.");
			}
			setControlBusy(false);
			return;
		}
		if (state === "timer-pause") {
			if (message) focusTimer(message);
			timerPausedRef.current = true;
			persistTimerState(true);
			setTimerPaused(true);
			setTimerCompact(false);
			setTranscript("");
			setVoiceStateTracked(timerAlarmRef.current && alarmOrbPinnedRef.current ? "orb" : "hidden");
			return;
		}
		if (state === "timer-resume") {
			if (message) focusTimer(message);
			timerPausedRef.current = false;
			persistTimerState(false);
			setTimerPaused(false);
			setTimerCompact(false);
			setTranscript("");
			setVoiceStateTracked("hidden");
			return;
		}
		if (state === "timer-cancel") {
			clearTimerState(message || selectedTimerIdRef.current);
			return;
		}
		if (state === "timer-end") {
			const endedId = message || selectedTimerIdRef.current;
			updateTimerCards((current) => current.map((timer) => timer.id === endedId ? { ...timer, remainingMs: 0, updatedAt: Date.now(), alarm: true, paused: false } : timer));
			if (endedId !== selectedTimerIdRef.current) return;
			timerActiveRef.current = true;
			timerAlarmRef.current = true;
			timerElapsedMs.current = timerDurationRef.current * 1000;
			persistTimerState(false, true);
			timerIslandRef.current?.style.setProperty("--timer-progress", "1");
			setTimerVisible(true);
			setTimerCompact(false);
			setTimerAlarm(true);
			if (voiceStateRef.current !== "hidden" && voiceStateRef.current !== "orb") {
				alarmOrbPinnedRef.current = true;
				setVoiceStateTracked("orb");
			}
			setTimerSeconds(0);
			timerPausedRef.current = false;
			setTimerPaused(false);
			return;
		}
		if (state === "alarm-stop") {
			if (message) clearTimerState(message);
			else clearAlarmTimers();
			return;
		}
		if (state === "timer") {
			setTimerSetupMessage("");
			let timerId = `timer-${sequence}`;
			let duration = Math.max(1, Number(message) || 1);
			try {
				const decoded = JSON.parse(message) as { id?: string; durationSeconds?: number };
				if (decoded.id) timerId = decoded.id;
				if (decoded.durationSeconds) duration = Math.max(1, decoded.durationSeconds);
			} catch { /* compatibilità con eventi timer della versione precedente */ }
			const startedAt = Date.now();
			const nextTimer: TimerCard = { id: timerId, durationSeconds: duration, remainingMs: duration * 1000, updatedAt: startedAt, paused: false, alarm: false };
			updateTimerCards((current) => [...current.filter((timer) => timer.id !== timerId), nextTimer]);
			selectedTimerIdRef.current = timerId;
			setSelectedTimerId(timerId);
			timerActiveRef.current = true;
			timerAlarmRef.current = false;
			alarmOrbPinnedRef.current = false;
			timerDurationRef.current = duration;
			timerElapsedMs.current = 0;
			timerPausedRef.current = false;
			persistTimerState(false);
			timerIslandRef.current?.style.setProperty("--timer-progress", "0");
			setTimerVisible(true);
			setActivePanel("timer");
			setTimerCompact(false);
			setTimerAlarm(false);
			setTimerSeconds(duration);
			setTimerDuration(duration);
			setTimerPaused(false);
			setTranscript("");
			setVoiceStateTracked("hidden");
			return;
		}

		if (state === "hide") {
			if (voiceStateRef.current !== "hidden") playCue("exit");
			setTimerCompact(false);
			setStopwatchCompact(false);
			setVoiceStateTracked(timerAlarmRef.current && alarmOrbPinnedRef.current ? "orb" : "hidden");
			setTranscript("");
			return;
		}
		if (state === "wake") {
			playCue("entry");
			if (stopwatchVisible) setStopwatchCompact(true);
			if (timerActiveRef.current) {
				if (timerAlarmRef.current) {
					setTimerCompact(false);
					alarmOrbPinnedRef.current = true;
				} else {
					setTimerCompact(true);
				}
			}
			setTranscript("");
			setVoiceStateTracked("wake");
			return;
		}

		if (timerActiveRef.current) {
			if (stopwatchVisible) setStopwatchCompact(true);
			if (timerAlarmRef.current) {
				setTimerCompact(false);
				alarmOrbPinnedRef.current = true;
			} else {
				setTimerCompact(true);
			}
		}
		if (state === "partial" || state === "processing" || state === "success") stopCues();
		if (state === "error") {
			playCue("error");
			setErrorPulse((pulse) => pulse + 1);
		}
		setTranscript(message);
		if (state === "success" && timerActiveRef.current && !timerAlarmRef.current) {
			setTimerCompact(false);
			setVoiceStateTracked("hidden");
			setTranscript("");
			playCue("exit");
			return;
		}
		if (state === "success" && stopwatchVisible) {
			setStopwatchCompact(false);
			setVoiceStateTracked("hidden");
			setTranscript("");
			playCue("exit");
			return;
		}
		if (!isVoiceState(state)) return;
		setVoiceStateTracked(state);
		if (state === "success") {
			successTimer.current = setTimeout(() => {
				playCue("exit");
				setTimerCompact(false);
				setVoiceStateTracked(timerAlarmRef.current && alarmOrbPinnedRef.current ? "orb" : "hidden");
				setTranscript("");
			}, 1250);
		}
	}, [clearAlarmTimers, clearTimerState, focusTimer, pauseStopwatch, persistTimerState, playCue, recordStopwatchLap, resetStopwatch, resumeStopwatch, setVoiceStateTracked, stopCues, stopwatchVisible, updateTimerCards]);

	useEffect(() => {
		let cancelled = false;
		let unlisten: (() => void) | undefined;
		let polling = false;
		const pollSnapshot = async () => {
			if (cancelled || polling) return;
			polling = true;
			try {
				handleVoiceEvent(await invoke<VoiceEvent>("latest_ui_state"));
			} catch (error: unknown) {
				console.error("Onyx voice state sync:", error);
			} finally {
				polling = false;
			}
		};
		const pollTimer = window.setInterval(() => void pollSnapshot(), 180);

		listen<VoiceEvent>("onyx-state", (event) => handleVoiceEvent(event.payload)).then((stop) => {
			if (cancelled) {
				stop();
				return;
			}
			unlisten = stop;
			return invoke("ui_ready").then(pollSnapshot);
		}).catch((error: unknown) => console.error("Onyx voice bridge:", error));
		void pollSnapshot();

		return () => {
			cancelled = true;
			window.clearInterval(pollTimer);
			unlisten?.();
			if (successTimer.current) clearTimeout(successTimer.current);
		};
	}, [handleVoiceEvent]);

	useEffect(() => {
		if (firstRestoredTimer?.alarm) timerIslandRef.current?.style.setProperty("--timer-progress", "1");
	}, [firstRestoredTimer]);

	useEffect(() => {
		if (!timerVisible || timerAlarm || timerPaused || timerDuration <= 0) return;
		const durationMs = timerDuration * 1000;
		const startedAt = performance.now() - timerElapsedMs.current;
		let frame = 0;
		const update = (now: number) => {
			const elapsed = Math.min(durationMs, Math.max(0, now - startedAt));
			timerElapsedMs.current = elapsed;
			timerIslandRef.current?.style.setProperty("--timer-progress", String(elapsed / durationMs));
			setTimerSeconds(Math.ceil((durationMs - elapsed) / 1000));
			if (elapsed < durationMs) frame = window.requestAnimationFrame(update);
		};
		frame = window.requestAnimationFrame(update);
		return () => window.cancelAnimationFrame(frame);
	}, [selectedTimerId, timerAlarm, timerDuration, timerPaused, timerVisible]);

	useEffect(() => {
		if (!stopwatchVisible || !stopwatchRunning) return;
		let frame = 0;
		const update = () => {
			setStopwatchElapsedMs(Math.max(0, performance.now() - stopwatchStartedAtRef.current));
			frame = window.requestAnimationFrame(update);
		};
		frame = window.requestAnimationFrame(update);
		return () => window.cancelAnimationFrame(frame);
	}, [stopwatchRunning, stopwatchVisible]);

	useEffect(() => {
		const interactive = islandExpanded || (timerVisible && !timerCompact) || (stopwatchVisible && !stopwatchCompact);
		const captureGesture = voiceState === "hidden" && !interactive;
		void invoke("set_overlay_interactive", { interactive, captureGesture })
			.catch((error: unknown) => console.error("Onyx overlay input:", error));
	}, [islandExpanded, stopwatchCompact, stopwatchVisible, timerCompact, timerVisible, voiceState]);

	const timerText = `${Math.floor(timerSeconds / 60)}:${String(timerSeconds % 60).padStart(2, "0")}`;
	const formatStopwatch = (elapsedMs: number) => {
		const centiseconds = Math.floor(elapsedMs / 10);
		const hundredths = centiseconds % 100;
		const totalSeconds = Math.floor(centiseconds / 100);
		const seconds = totalSeconds % 60;
		const minutes = Math.floor(totalSeconds / 60) % 60;
		const hours = Math.floor(totalSeconds / 3600);
		return hours > 0
			? `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
			: `${minutes}:${String(seconds).padStart(2, "0")}.${String(hundredths).padStart(2, "0")}`;
	};
	const stopwatchText = formatStopwatch(stopwatchElapsedMs);
	const clockText = clockNow.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
	const otherTimerIslands = timerCards.filter((timer) => timer.id !== selectedTimerId).map((timer) => {
		const remainingMs = timer.alarm ? 0 : Math.max(0, timer.remainingMs - (timer.paused ? 0 : Date.now() - timer.updatedAt));
		const seconds = Math.ceil(remainingMs / 1000);
		const progress = timer.alarm ? 1 : Math.min(1, Math.max(0, 1 - remainingMs / (timer.durationSeconds * 1000)));
		return <motion.div key={`timer-mini-${timer.id}`} className={`bloom onyx-island onyx-timer onyx-timer-mini is-compact ${timer.alarm ? "onyx-alarm" : ""}`} initial={{ opacity: 0, scale: .85 }} animate={{ opacity: 1, scale: 1, width: 56, height: 56 }} exit={{ opacity: 0, scale: .8 }} transition={transition} style={{ "--surface-bg": timer.alarm ? "rgba(12, 12, 16, .96)" : "rgba(0, 0, 0, .96)", "--timer-progress": progress } as CSSProperties} role="button" aria-label={`Timer ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`} onClick={() => focusTimer(timer.id)}><EdgeSurface edge="top" flares /><strong>{Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")}</strong></motion.div>;
	});
	const dateText = clockNow.toLocaleDateString("it-IT", { weekday: "long", day: "numeric", month: "long" });
	const monthTitle = calendarMonth.toLocaleDateString("it-IT", { month: "long", year: "numeric" });
	const calendarOffset = (new Date(calendarMonth.getFullYear(), calendarMonth.getMonth(), 1).getDay() + 6) % 7;
	const calendarDayCount = new Date(calendarMonth.getFullYear(), calendarMonth.getMonth() + 1, 0).getDate();
	const calendarCells: Array<number | null> = [
		...Array.from({ length: calendarOffset }, () => null),
		...Array.from({ length: calendarDayCount }, (_, index) => index + 1)
	];
	const selectedCalendarDate = new Date(calendarMonth.getFullYear(), calendarMonth.getMonth(), Math.min(calendarDay, calendarDayCount));
	const selectedCalendarDateText = selectedCalendarDate.toLocaleDateString("it-IT", { weekday: "long", day: "numeric", month: "long" });
	const selectedCalendarKey = `${selectedCalendarDate.getFullYear()}-${String(selectedCalendarDate.getMonth() + 1).padStart(2, "0")}-${String(selectedCalendarDate.getDate()).padStart(2, "0")}`;
	const selectedCalendarEntries = calendarEntries.filter((entry) => entry.date === selectedCalendarKey);
	const message = voiceState === "wake"
		? "In ascolto"
		: voiceState === "processing"
			? `Eseguo: ${transcript}`
			: transcript;
	const orbState: OrbState = voiceState === "processing"
		? "solving"
		: voiceState === "success"
			? "breathing"
			: "listening";
	const voicePillVisible = voiceState !== "hidden" && voiceState !== "orb";
	const voiceOrbVisible = voiceState === "orb";
	const voicePillWidth = voiceState === "wake"
		? 154
		: Math.min(690, Math.max(178, 142 + Array.from(message).length * 7.1));
	const transition = reducedMotion
		? { duration: 0.1, ease: "easeOut" as const }
		: { type: "spring" as const, stiffness: 420, damping: 34, mass: 0.82 };
	const restingClock = !islandExpanded && voiceState === "hidden" && !timerVisible && !stopwatchVisible ? (
		<motion.div
			key="resting-clock"
			className="bloom onyx-island onyx-clock"
			initial={{ opacity: 0, y: -8, scale: 0.94, width: 72, height: 36 }}
			animate={{ opacity: 1, y: 0, scale: 1, width: 92, height: 38 }}
			exit={{ opacity: 0, y: -6, scale: 0.95, width: 72, height: 36 }}
			transition={transition}
			style={{ "--surface-bg": "rgba(9, 9, 13, .88)" } as CSSProperties}
			role="button"
			tabIndex={0}
			onClick={() => { setGestureEnabled(true); setHoverExpanded(true); setActivePanel("clock"); }}
			onKeyDown={(event) => {
				if (event.key === "Enter" || event.key === " ") {
					event.preventDefault();
					setGestureEnabled(true);
					setHoverExpanded(true);
					setActivePanel("clock");
				}
			}}
			aria-label={`Ora ${clockText}`}
		>
			<EdgeSurface edge="top" flares />
			<time dateTime={clockNow.toISOString()}>{clockText}</time>
		</motion.div>
	) : null;

	const workspacePanel = gestureEnabled && islandExpanded && voiceState === "hidden" ? (
		activePanel === "clock" ? (
			<motion.div key="clock-workspace" className="bloom onyx-island onyx-workspace onyx-clock-workspace" initial={{ opacity: 0, y: -8, scale: .96 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -6, scale: .96 }} transition={transition}>
				<EdgeSurface edge="top" flares />
				<div className="onyx-workspace-time"><span>{dateText}</span><strong>{clockText}</strong></div>
				<div className="onyx-workspace-actions">
					<button type="button" onClick={() => setActivePanel("timer-setup")}>Timer</button>
					<button type="button" onClick={() => { setStopwatchVisible(true); setStopwatchCompact(false); setActivePanel("stopwatch"); }}>Cronometro</button>
					<button type="button" onClick={() => setActivePanel("pomodoro")}>Pomodoro</button>
					<button type="button" onClick={() => setActivePanel("alarm")}>Sveglia</button>
					<button type="button" onClick={() => setActivePanel("calendar")}>Calendario</button>
					<button type="button" onClick={() => setActivePanel("controls")}>Controlli</button>
				</div>
				<small className="onyx-workspace-hint">↓ apre e mantiene · ←/→ cambia scheda · ↑ chiude · il cursore apre temporaneamente</small>
			</motion.div>
		) : activePanel === "timer-setup" ? (
			<motion.div key="timer-setup-workspace" className="bloom onyx-island onyx-workspace onyx-timer-setup" initial={{ opacity: 0, y: -8, scale: .96 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -6, scale: .96 }} transition={transition}>
				<EdgeSurface edge="top" flares />
				<div className="onyx-timer-setup-heading"><span>Timer</span><small>Imposta un conto alla rovescia</small></div>
				<div className="onyx-timer-presets">{[5, 10, 15, 25, 50].map((minutes) => <button key={minutes} type="button" onClick={() => startTimerFromPanel(minutes * 60)}>{minutes} min</button>)}</div>
				<div className="onyx-timer-custom"><label htmlFor="onyx-timer-minutes">Minuti</label><input id="onyx-timer-minutes" type="number" min="1" max="1440" value={timerMinutesInput} onChange={(event) => setTimerMinutesInput(event.currentTarget.value)} /><button type="button" disabled={!Number.isFinite(Number(timerMinutesInput)) || Number(timerMinutesInput) < 1 || Number(timerMinutesInput) > 1440} onClick={() => startTimerFromPanel(Number(timerMinutesInput) * 60)}>Avvia</button></div>
				{timerSetupMessage && <small className="onyx-timer-setup-status">{timerSetupMessage}</small>}
			</motion.div>
		) : activePanel === "pomodoro" ? (
			<motion.div key="pomodoro-workspace" className="bloom onyx-island onyx-workspace onyx-timer-setup" initial={{ opacity: 0, y: -8, scale: .96 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -6, scale: .96 }} transition={transition}>
				<EdgeSurface edge="top" flares />
				<div className="onyx-timer-setup-heading"><span>Pomodoro</span><small>Concentrazione intervallata da pause</small></div>
				<div className="onyx-timer-presets"><button type="button" onClick={() => startTimerFromPanel(25 * 60)}>Concentrazione · 25 min</button><button type="button" onClick={() => startTimerFromPanel(5 * 60)}>Pausa breve · 5 min</button><button type="button" onClick={() => startTimerFromPanel(15 * 60)}>Pausa lunga · 15 min</button></div>
				<small className="onyx-timer-setup-status">A fine conto alla rovescia puoi interrompere l’allarme dal notch.</small>
			</motion.div>
		) : activePanel === "alarm" ? (
			<motion.div key="alarm-workspace" className="bloom onyx-island onyx-workspace onyx-timer-setup" initial={{ opacity: 0, y: -8, scale: .96 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -6, scale: .96 }} transition={transition}>
				<EdgeSurface edge="top" flares />
				<div className="onyx-timer-setup-heading"><span>Sveglia</span><small>Imposta un allarme per l’ora scelta</small></div>
				<div className="onyx-timer-custom"><label htmlFor="onyx-alarm-time">Ora</label><input id="onyx-alarm-time" type="time" value={alarmTimeInput} onChange={(event) => setAlarmTimeInput(event.currentTarget.value)} /><button type="button" onClick={() => { const [hours, minutes] = alarmTimeInput.split(":").map(Number); const target = new Date(); target.setHours(hours, minutes, 0, 0); if (target.getTime() <= Date.now()) target.setDate(target.getDate() + 1); startTimerFromPanel(Math.ceil((target.getTime() - Date.now()) / 1000)); }}>Imposta</button></div>
				<small className="onyx-timer-setup-status">La sveglia suona tramite l’allarme timer Onyx.</small>
			</motion.div>
		) : activePanel === "calendar" ? (
			<motion.div key="calendar-workspace" className="bloom onyx-island onyx-workspace onyx-calendar-workspace" initial={{ opacity: 0, y: -8, scale: .96 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -6, scale: .96 }} transition={transition}>
				<EdgeSurface edge="top" flares />
				<div className="onyx-calendar-main">
					<div className="onyx-calendar-header">
						<button type="button" aria-label="Mese precedente" onClick={() => { setCalendarMonth((month) => new Date(month.getFullYear(), month.getMonth() - 1, 1)); setCalendarDay(1); }}>‹</button>
						<strong>{monthTitle}</strong>
						<button type="button" aria-label="Mese successivo" onClick={() => { setCalendarMonth((month) => new Date(month.getFullYear(), month.getMonth() + 1, 1)); setCalendarDay(1); }}>›</button>
					</div>
					<div className="onyx-calendar-grid">
						{["L", "M", "M", "G", "V", "S", "D"].map((day, index) => <span className="weekday" key={`${day}-${index}`}>{day}</span>)}
						{calendarCells.map((day, index) => day === null ? <span key={`empty-${index}`} /> : <button key={day} type="button" className={`${day === calendarDay ? "selected" : ""} ${day === clockNow.getDate() && calendarMonth.getMonth() === clockNow.getMonth() && calendarMonth.getFullYear() === clockNow.getFullYear() ? "today" : ""}`} onClick={() => setCalendarDay(day)}>{day}</button>)}
					</div>
				</div>
				<div className="onyx-calendar-selection">
					<span>{selectedCalendarDateText}</span>
					{selectedCalendarEntries.length ? <div className="onyx-calendar-events">{selectedCalendarEntries.map((entry) => <div key={entry.id}><time>{entry.time}</time><strong>{entry.title}</strong><button type="button" aria-label={`Elimina ${entry.title}`} onClick={() => removeCalendarEntry(entry.id)}>×</button></div>)}</div> : <strong>Nessun evento</strong>}
					<form className="onyx-calendar-add" onSubmit={(event) => { event.preventDefault(); saveCalendarEntry(); }}>
						<input aria-label="Nome evento" placeholder="Aggiungi evento" maxLength={64} value={calendarTitleInput} onChange={(event) => setCalendarTitleInput(event.currentTarget.value)} />
						<input aria-label="Ora evento" type="time" value={calendarTimeInput} onChange={(event) => setCalendarTimeInput(event.currentTarget.value)} />
						<button type="submit" disabled={!calendarTitleInput.trim()} aria-label="Salva evento">＋</button>
					</form>
					<small>Eventi salvati in questo dispositivo</small>
				</div>
			</motion.div>
		) : activePanel === "controls" ? (
			<motion.div key="controls-workspace" className="bloom onyx-island onyx-workspace onyx-controls-workspace" initial={{ opacity: 0, y: -8, scale: .96 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -6, scale: .96 }} transition={transition}>
				<EdgeSurface edge="top" flares />
				<div className="onyx-controls-main">
					<div className="onyx-control-slider">
						<label htmlFor="onyx-brightness">Luminosità <b>{controlState.brightness === null ? "—" : `${controlState.brightness}%`}</b></label>
						<input id="onyx-brightness" type="range" min="0" max="100" value={controlState.brightness ?? 50} disabled={controlBusy || controlState.brightness === null} onChange={(event) => { const value = Number(event.currentTarget.value); setControlState((state) => ({ ...state, brightness: value })); if (brightnessTimeoutRef.current) clearTimeout(brightnessTimeoutRef.current); brightnessTimeoutRef.current = setTimeout(() => requestSystemAction("brightness-set", value), 220); }} onPointerUp={() => { if (brightnessTimeoutRef.current) { clearTimeout(brightnessTimeoutRef.current); brightnessTimeoutRef.current = null; } if (controlState.brightness !== null) requestSystemAction("brightness-set", controlState.brightness); }} />
					</div>
					<div className="onyx-control-volume"><span>Volume</span><button type="button" disabled={controlBusy} aria-label="Abbassa volume" onClick={() => requestSystemAction("volume-down")}>−</button><button type="button" disabled={controlBusy} aria-label="Alza volume" onClick={() => requestSystemAction("volume-up")}>+</button></div>
					<div className="onyx-control-radios">
						<button type="button" disabled={controlBusy} className={controlState.wifi ? "active" : ""} onClick={() => requestSystemAction("wifi-toggle")}>Wi‑Fi <small>{controlState.wifi === null ? "—" : controlState.wifi ? "Attivo" : "Spento"}</small></button>
						<button type="button" disabled={controlBusy} className={controlState.bluetooth ? "active" : ""} onClick={() => requestSystemAction("bluetooth-toggle")}>Bluetooth <small>{controlState.bluetooth === null ? "—" : controlState.bluetooth ? "Attivo" : "Spento"}</small></button>
						<button type="button" disabled={controlBusy} className={controlState.airplane ? "active airplane" : ""} onClick={() => requestSystemAction("airplane-toggle")}>Modalità aereo <small>{controlState.airplane === null ? "—" : controlState.airplane ? "Attiva" : "Disattiva"}</small></button>
					</div>
					<div className="onyx-control-status" aria-live="polite">{controlBusy ? "Applico…" : controlMessage || ""}</div>
				</div>
			</motion.div>
		) : null
	) : null;

	const stopwatchIsland = stopwatchVisible ? (
		<motion.div
			key="stopwatch-island"
			className={`bloom onyx-island onyx-stopwatch ${stopwatchCompact ? "is-compact" : ""}`}
			initial={{ opacity: 0, y: -10, scale: 0.94, width: 74, height: 38 }}
			animate={{ opacity: 1, y: 0, scale: 1, width: stopwatchCompact ? 74 : 354, height: stopwatchCompact ? 38 : 88 }}
			exit={{ opacity: 0, y: -8, scale: 0.93, width: 74, height: 38 }}
			transition={transition}
			style={{ "--surface-bg": "rgba(0, 0, 0, .96)" } as CSSProperties}
			role="timer"
			aria-label={`Cronometro ${stopwatchText}`}
		>
			<EdgeSurface edge="top" flares />
			{stopwatchCompact ? (
				<div className="onyx-stopwatch-compact"><strong>{stopwatchText}</strong></div>
			) : (
				<div className="onyx-stopwatch-expanded">
					<div className="onyx-stopwatch-reading">
						<span>Cronometro{stopwatchRunning ? " · In corso" : " · In pausa"}</span>
						<strong>{stopwatchText}</strong>
						{stopwatchLaps.length > 0 && <small>Giro {stopwatchLaps.length}: {formatStopwatch(stopwatchLaps[0])}</small>}
					</div>
					<div className="onyx-stopwatch-controls">
						<button type="button" aria-label={stopwatchRunning ? "Metti in pausa il cronometro" : "Riprendi il cronometro"} onClick={stopwatchRunning ? pauseStopwatch : resumeStopwatch}>{stopwatchRunning ? "Ⅱ" : "▶"}</button>
						<button type="button" aria-label="Registra giro" disabled={!stopwatchRunning} onClick={recordStopwatchLap}>Giro</button>
						<button type="button" aria-label="Azzera cronometro" onClick={resetStopwatch}>Azzera</button>
						<button type="button" className="stopwatch-close" aria-label="Chiudi cronometro" onClick={() => setStopwatchVisible(false)}>×</button>
					</div>
					{stopwatchLaps.length > 0 && <div className="onyx-stopwatch-laps" aria-label="Giri recenti">
						{stopwatchLaps.slice(0, 3).map((lap, index) => <span key={`${lap}-${index}`}>Giro {stopwatchLaps.length - index} <b>{formatStopwatch(lap)}</b></span>)}
					</div>}
				</div>
			)}
		</motion.div>
	) : null;

	const timerIsland = timerVisible ? (
		<motion.div
			key="timer-island"
			ref={timerIslandRef}
			className={`bloom onyx-island onyx-timer ${timerAlarm ? "onyx-alarm" : ""} ${timerCompact ? "is-compact" : ""}`}
			initial={{ opacity: 0, y: -10, scale: 0.94, width: 92, height: 38 }}
			animate={{ opacity: 1, y: 0, scale: 1, width: timerCompact ? 56 : 310, height: timerCompact ? 56 : 46 }}
			exit={{ opacity: 0, y: -8, scale: 0.93, width: 92, height: 38 }}
			transition={transition}
			style={{ "--surface-bg": timerAlarm ? "rgba(12, 12, 16, .96)" : "rgba(0, 0, 0, .96)" } as CSSProperties}
			role="timer"
		>
			<EdgeSurface edge="top" flares />
			<div className={`onyx-message timer-message ${timerCompact ? "is-compact" : ""}`}>
				{timerCompact ? <strong>{timerText}</strong> : <><span>{timerAlarm ? "Allarme" : "Timer"}</span><strong>{timerText}</strong></>}
			</div>
			{!timerCompact && <div className={`onyx-timer-controls ${timerAlarm ? "is-alarm" : ""}`}>
				{timerAlarm ? <button type="button" className="onyx-alarm-stop" aria-label="Interrompi allarme" onClick={() => {
					void invoke("timer_control", { action: "stop-alarm", timerId: selectedTimerId }).then(() => clearTimerState(selectedTimerId)).catch((error: unknown) => console.error("Onyx alarm control:", error));
				}}>Interrompi</button> : <>
					<button type="button" className="onyx-timer-add" aria-label="Aggiungi timer" onClick={() => setActivePanel("timer-setup")}>＋</button>
					<button type="button" className="onyx-timer-pause" aria-label={timerPaused ? "Riprendi timer" : "Metti in pausa"} onClick={() => {
						const next = !timerPaused;
						timerPausedRef.current = next;
						setTimerPaused(next);
						persistTimerState(next);
						void invoke("timer_control", { action: next ? "pause" : "resume", timerId: selectedTimerId }).catch((error: unknown) => {
							console.error("Onyx timer control:", error);
							timerPausedRef.current = !next;
							setTimerPaused(!next);
							persistTimerState(!next);
						});
					}}>{timerPaused ? "▶" : "Ⅱ"}</button>
					<button type="button" aria-label="Annulla timer" onClick={() => {
						void invoke("timer_control", { action: "cancel", timerId: selectedTimerId }).then(() => clearTimerState(selectedTimerId)).catch((error: unknown) => console.error("Onyx timer control:", error));
					}} className="onyx-timer-cancel">×</button>
				</>}
			</div>}
		</motion.div>
	) : null;

	const onyxOrb = voiceOrbVisible ? (
		<motion.div
			key="onyx-orb"
			className="onyx-orb-dock"
			initial={{ opacity: 0, scale: 0.7 }}
			animate={{ opacity: 1, scale: 1 }}
			exit={{ opacity: 0, scale: 0.7 }}
			transition={transition}
			aria-label="Onyx in ascolto"
		>
			<ThinkingOrb state="listening" size={20} theme="dark" />
		</motion.div>
	) : null;

	const onyxPill = voicePillVisible ? (
		<motion.div
			key="onyx-pill"
			className={`bloom onyx-island onyx-${voiceState}`}
			initial={{ opacity: 0, y: -10, scale: 0.94, width: 92, height: 38 }}
			animate={{
				opacity: 1,
				y: 0,
				scale: 1,
				width: voicePillWidth,
				height: 46,
				x: voiceState === "error" && !reducedMotion
					? errorPulse % 2 === 0 ? [0, -4, 3, -2, 0] : [0, 4, -3, 2, 0]
					: 0
			}}
			exit={{ opacity: 0, y: -8, scale: 0.93, width: 92, height: 38 }}
			transition={{ ...transition, x: { duration: 0.28, ease: "easeInOut" } }}
			style={{ "--surface-bg": voiceState === "error" ? "rgba(37, 17, 24, .84)" : "rgba(9, 9, 13, .88)" } as CSSProperties}
			role="status"
		>
			<EdgeSurface edge="top" flares />
			<div className="onyx-message" key={voiceState === "wake" ? "wake" : "message"}>
				{Array.from(message).map((character, index) => (
					<motion.span
						key={`${index}-${character}`}
						initial={reducedMotion ? false : { opacity: 0, y: 3 }}
						animate={{ opacity: 1, y: 0 }}
						transition={{ duration: 0.16, delay: reducedMotion ? 0 : Math.min(index * 0.012, 0.18) }}
					>
						{character === " " ? "\u00a0" : character}
					</motion.span>
				))}
			</div>
			<div className={`onyx-orb orb-${voiceState}`} aria-hidden="true">
				<ThinkingOrb state={orbState} size={20} theme="dark" />
			</div>
		</motion.div>
	) : null;

	const orbBeforeTimer = timerAlarm && voiceOrbVisible;

	return (
		<div className="onyx-screen" aria-live="polite" aria-atomic="true" onWheel={handleGestureWheel}>
			<AnimatePresence>
				{restingClock}
				{workspacePanel}
				{orbBeforeTimer && onyxOrb}
				{otherTimerIslands}
				{stopwatchIsland}
				{timerIsland}
				{voiceOrbVisible && !orbBeforeTimer && onyxOrb}
				{onyxPill}
			</AnimatePresence>
		</div>
	);
}
