using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

internal sealed class OnyxTrayContext : ApplicationContext
{
    private const string RunKeyPath = @"Software\Microsoft\Windows\CurrentVersion\Run";
    private const string SettingsKeyPath = @"Software\Onyx";
    private const string RunValueName = "Onyx";
    private const string AutoStartValueName = "AutoStartEnabled";
    private const string AutoStartConfiguredValueName = "AutoStartConfigured";

    private readonly string root;
    private readonly string pythonPath;
    private readonly string scriptPath;
    private readonly string overlayPath;
    private readonly string restartCommandPath;
    private readonly string logsPath;
    private readonly string pidPath;
    private readonly NotifyIcon trayIcon;
    private readonly ToolStripMenuItem statusItem;
    private readonly ToolStripMenuItem listenItem;
    private readonly ToolStripMenuItem restartItem;
    private readonly ToolStripMenuItem autoStartItem;
    private readonly SynchronizationContext uiContext;
    private readonly object processLock = new object();
    private Process listener;
    private bool autoStartEnabled;
    private bool exiting;
    private bool restartInProgress;

    public OnyxTrayContext(string projectRoot)
    {
        root = projectRoot;
        pythonPath = Path.Combine(root, @".venv\Scripts\python.exe");
        scriptPath = Path.Combine(root, @"Azioni\ascolta_onix.py");
        overlayPath = Path.Combine(root, @"UI\BloomSource\src-tauri\target\onyx-ui-build-v5\release\onyx-ui.exe");
        restartCommandPath = Path.Combine(root, "Riavvia-Onyx.cmd");
        logsPath = Path.Combine(root, "logs");
        pidPath = Path.Combine(logsPath, "onyx.pid");

        using (Control dispatcher = new Control())
        {
            IntPtr unused = dispatcher.Handle;
            uiContext = SynchronizationContext.Current ?? new WindowsFormsSynchronizationContext();
        }

        ContextMenuStrip menu = new ContextMenuStrip();
        statusItem = new ToolStripMenuItem("Onyx") { Enabled = false };
        listenItem = new ToolStripMenuItem("Avvio ascolto", null, ToggleListening);
        restartItem = new ToolStripMenuItem("Riavvia", null, RestartOnyx);
        autoStartItem = new ToolStripMenuItem("Avvia con Windows", null, ToggleAutoStart);
        menu.Items.Add(statusItem);
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add(listenItem);
        menu.Items.Add(restartItem);
        menu.Items.Add(autoStartItem);
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add(new ToolStripMenuItem("Apri log", null, OpenLogs));
        menu.Items.Add(new ToolStripMenuItem("Esci da Onyx", null, ExitOnyx));
        menu.Opening += RefreshMenu;

        Icon icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        if (icon == null)
        {
            icon = SystemIcons.Application;
        }

        trayIcon = new NotifyIcon
        {
            Icon = icon,
            Text = "Onyx",
            ContextMenuStrip = menu,
            Visible = true
        };
        trayIcon.MouseDoubleClick += delegate { ToggleListening(this, EventArgs.Empty); };

        LoadOrInitializeAutoStart();
        UpdateTrayStatus();
        StartListening();
    }

    private void LoadOrInitializeAutoStart()
    {
        try
        {
            using (RegistryKey settings = Registry.CurrentUser.CreateSubKey(SettingsKeyPath))
            {
                object configured = settings.GetValue(AutoStartConfiguredValueName);
                object enabled = settings.GetValue(AutoStartValueName);
                bool shouldEnable = configured == null || (enabled != null && Convert.ToInt32(enabled) != 0);
                settings.SetValue(AutoStartConfiguredValueName, 1, RegistryValueKind.DWord);
                settings.SetValue(AutoStartValueName, shouldEnable ? 1 : 0, RegistryValueKind.DWord);
                SetAutoStartRegistration(shouldEnable);
            }
        }
        catch (Exception ex)
        {
            WriteAppLog("Impossibile configurare l'avvio automatico: " + ex.Message);
            autoStartEnabled = true;
        }
    }

    private void ToggleAutoStart(object sender, EventArgs args)
    {
        bool desiredState = !autoStartEnabled;
        try
        {
            SetAutoStartRegistration(desiredState);
            using (RegistryKey settings = Registry.CurrentUser.CreateSubKey(SettingsKeyPath))
            {
                settings.SetValue(AutoStartConfiguredValueName, 1, RegistryValueKind.DWord);
                settings.SetValue(AutoStartValueName, desiredState ? 1 : 0, RegistryValueKind.DWord);
            }
            trayIcon.ShowBalloonTip(2200, "Onyx", autoStartEnabled ? "Avvio automatico attivato." : "Avvio automatico disattivato.", ToolTipIcon.Info);
        }
        catch (Exception ex)
        {
            autoStartEnabled = IsAutoStartRegistered();
            WriteAppLog("Impossibile salvare l'impostazione di avvio: " + ex.Message);
            trayIcon.ShowBalloonTip(3500, "Onyx", "Non sono riuscito a salvare l'impostazione di avvio automatico.", ToolTipIcon.Error);
        }
    }

    private void SetAutoStartRegistration(bool enabled)
    {
        string exePath = Application.ExecutablePath;
        using (RegistryKey runKey = Registry.CurrentUser.CreateSubKey(RunKeyPath))
        {
            if (enabled)
            {
                runKey.SetValue(RunValueName, "\"" + exePath + "\"", RegistryValueKind.String);
            }
            else
            {
                runKey.DeleteValue(RunValueName, false);
            }
        }
        autoStartEnabled = enabled;
    }

    private bool IsAutoStartRegistered()
    {
        try
        {
            using (RegistryKey runKey = Registry.CurrentUser.OpenSubKey(RunKeyPath, false))
            {
                if (runKey == null) return false;
                string registeredPath = runKey.GetValue(RunValueName) as string;
                string expectedPath = "\"" + Application.ExecutablePath + "\"";
                return String.Equals(registeredPath, expectedPath, StringComparison.OrdinalIgnoreCase);
            }
        }
        catch { return false; }
    }

    private void ToggleListening(object sender, EventArgs args)
    {
        if (IsListening())
        {
            StopListening(true);
        }
        else
        {
            StartListening();
        }
        UpdateTrayStatus();
    }

    private void RestartOnyx(object sender, EventArgs args)
    {
        if (!File.Exists(restartCommandPath))
        {
            ReportStartError("Script di riavvio non trovato: " + restartCommandPath);
            return;
        }

        restartInProgress = true;
        try
        {
            ProcessStartInfo startInfo = new ProcessStartInfo
            {
                FileName = Environment.GetEnvironmentVariable("ComSpec") ?? "cmd.exe",
                Arguments = "/c \"\"" + restartCommandPath + "\"\"",
                WorkingDirectory = root,
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden
            };
            startInfo.EnvironmentVariables["ONYX_BACKGROUND"] = "1";
            if (Process.Start(startInfo) == null)
            {
                throw new InvalidOperationException("Windows non ha avviato la procedura di riavvio.");
            }

            WriteAppLog("Riavvio completo richiesto dal menu Onyx.");
            trayIcon.ShowBalloonTip(2200, "Onyx", "Riavvio completo in corso: aggiornamento e riapertura.", ToolTipIcon.Info);

            // Release the tray singleton before the rebuild starts. The restart
            // script can then launch the freshly compiled Onyx.exe without
            // depending on another process being able to enumerate this one.
            ExitOnyx(this, EventArgs.Empty);
        }
        catch (Exception ex)
        {
            restartInProgress = false;
            WriteAppLog("Impossibile avviare il riavvio completo: " + ex.Message);
            trayIcon.ShowBalloonTip(3500, "Onyx", "Non sono riuscito ad avviare il riavvio. Consulta logs\\riavvio.log.", ToolTipIcon.Error);
        }
    }

    private void StartListening()
    {
        lock (processLock)
        {
            if (listener != null && !HasExited(listener))
            {
                return;
            }
        }

        Directory.CreateDirectory(logsPath);
        Process existing = TryAdoptExistingListener();
        if (existing != null)
        {
            lock (processLock)
            {
                listener = existing;
            }
            WatchProcess(existing);
            WriteAppLog("Motore Onyx già attivo, collegato al processo " + existing.Id + ".");
            UpdateTrayStatus();
            return;
        }

        if (!File.Exists(pythonPath))
        {
            ReportStartError("Non trovo Python dell'ambiente Onyx: " + pythonPath);
            return;
        }
        if (!File.Exists(scriptPath))
        {
            ReportStartError("Non trovo il motore vocale: " + scriptPath);
            return;
        }
        if (!File.Exists(overlayPath))
        {
            ReportStartError("L'interfaccia Onyx non è compilata. Esegui PowerShell\\Compila-Interfaccia-Onyx.ps1.");
            return;
        }

        try
        {
            ProcessStartInfo startInfo = new ProcessStartInfo
            {
                FileName = pythonPath,
                Arguments = "\"" + scriptPath + "\"",
                WorkingDirectory = root,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = new UTF8Encoding(false),
                StandardErrorEncoding = new UTF8Encoding(false)
            };
            startInfo.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
            Process started = new Process { StartInfo = startInfo, EnableRaisingEvents = true };
            started.OutputDataReceived += delegate(object sender, DataReceivedEventArgs eventArgs)
            {
                if (eventArgs.Data != null) AppendLog("onyx.log", eventArgs.Data);
            };
            started.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs eventArgs)
            {
                if (eventArgs.Data != null) AppendLog("onyx-error.log", eventArgs.Data);
            };
            started.Exited += delegate { ListenerExited(started); };

            if (!started.Start())
            {
                throw new InvalidOperationException("Windows non ha avviato il motore Onyx.");
            }

            lock (processLock)
            {
                listener = started;
            }
            File.WriteAllText(pidPath, started.Id.ToString());
            started.BeginOutputReadLine();
            started.BeginErrorReadLine();
            if (HasExited(started)) ListenerExited(started);
            WriteAppLog("Motore Onyx avviato (PID " + started.Id + ").");
            UpdateTrayStatus();
        }
        catch (Exception ex)
        {
            ReportStartError("Non sono riuscito ad avviare Onyx: " + ex.Message);
        }
    }

    private Process TryAdoptExistingListener()
    {
        if (!File.Exists(pidPath)) return null;
        int processId;
        if (!Int32.TryParse(File.ReadAllText(pidPath).Trim(), out processId) || processId <= 0)
        {
            TryDeletePidFile();
            return null;
        }

        try
        {
            Process candidate = Process.GetProcessById(processId);
            string executable = candidate.MainModule.FileName;
            if (!String.Equals(executable, pythonPath, StringComparison.OrdinalIgnoreCase) &&
                !String.Equals(executable, Path.Combine(root, @".venv\Scripts\pythonw.exe"), StringComparison.OrdinalIgnoreCase))
            {
                TryDeletePidFile();
                return null;
            }
            return candidate;
        }
        catch
        {
            TryDeletePidFile();
            return null;
        }
    }

    private void WatchProcess(Process process)
    {
        process.EnableRaisingEvents = true;
        process.Exited += delegate { ListenerExited(process); };
    }

    private void ListenerExited(Process process)
    {
        lock (processLock)
        {
            if (Object.ReferenceEquals(listener, process)) listener = null;
        }
        RemovePidIfMatches(process.Id);
        WriteAppLog("Motore Onyx terminato (PID " + process.Id + ").");
        uiContext.Post(delegate
        {
            UpdateTrayStatus();
            if (!exiting && !restartInProgress)
            {
                trayIcon.ShowBalloonTip(2600, "Onyx", "L'ascolto si è arrestato. Apri il log per i dettagli.", ToolTipIcon.Warning);
            }
        }, null);
    }

    private bool IsListening()
    {
        lock (processLock)
        {
            return listener != null && !HasExited(listener);
        }
    }

    private static bool HasExited(Process process)
    {
        try { return process.HasExited; }
        catch { return true; }
    }

    private bool StopListening(bool showMessage)
    {
        Process current;
        lock (processLock) current = listener;
        if (current == null)
        {
            int savedId;
            if (Int32.TryParse(ReadPidFile(), out savedId) && savedId > 0)
            {
                try { current = Process.GetProcessById(savedId); }
                catch { current = null; }
            }
        }
        if (current == null || HasExited(current))
        {
            lock (processLock) listener = null;
            TryDeletePidFile();
            UpdateTrayStatus();
            return true;
        }

        try
        {
            Process killer = Process.Start(new ProcessStartInfo
            {
                FileName = "taskkill.exe",
                Arguments = "/PID " + current.Id + " /T /F",
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true
            });
            if (killer != null)
            {
                killer.WaitForExit(5000);
                killer.Dispose();
            }
            current.WaitForExit(5000);
            if (!HasExited(current))
            {
                current.Kill();
                current.WaitForExit(2000);
            }
            RemovePidIfMatches(current.Id);
            lock (processLock) listener = null;
            WriteAppLog("Ascolto Onyx messo in pausa.");
            UpdateTrayStatus();
            if (showMessage)
            {
                trayIcon.ShowBalloonTip(1800, "Onyx", "Ascolto in pausa.", ToolTipIcon.Info);
            }
            return true;
        }
        catch (Exception ex)
        {
            WriteAppLog("Errore durante l'arresto di Onyx: " + ex.Message);
            trayIcon.ShowBalloonTip(3500, "Onyx", "Non sono riuscito a fermare il motore. Consulta il log.", ToolTipIcon.Error);
            return false;
        }
    }

    private void RefreshMenu(object sender, System.ComponentModel.CancelEventArgs args)
    {
        bool active = IsListening();
        statusItem.Text = active ? "Onyx — ascolto attivo" : "Onyx — in pausa";
        listenItem.Text = active ? "Pausa ascolto" : "Riprendi ascolto";
        autoStartItem.Checked = autoStartEnabled;
    }

    private void UpdateTrayStatus()
    {
        bool active = IsListening();
        trayIcon.Text = active ? "Onyx — ascolto attivo" : "Onyx — in pausa";
    }

    private void OpenLogs(object sender, EventArgs args)
    {
        try
        {
            Directory.CreateDirectory(logsPath);
            Process.Start(new ProcessStartInfo { FileName = "explorer.exe", Arguments = "\"" + logsPath + "\"", UseShellExecute = true });
        }
        catch (Exception ex)
        {
            WriteAppLog("Impossibile aprire la cartella dei log: " + ex.Message);
        }
    }

    private void ExitOnyx(object sender, EventArgs args)
    {
        exiting = true;
        if (!StopListening(false))
        {
            exiting = false;
            return;
        }
        trayIcon.Visible = false;
        trayIcon.Dispose();
        ExitThread();
    }

    protected override void ExitThreadCore()
    {
        if (!exiting)
        {
            exiting = true;
            StopListening(false);
        }
        if (trayIcon != null)
        {
            trayIcon.Visible = false;
            trayIcon.Dispose();
        }
        base.ExitThreadCore();
    }

    private void ReportStartError(string message)
    {
        WriteAppLog(message);
        UpdateTrayStatus();
        trayIcon.ShowBalloonTip(5000, "Onyx non è partito", message, ToolTipIcon.Error);
    }

    private void AppendLog(string fileName, string line)
    {
        try
        {
            lock (processLock)
            {
                Directory.CreateDirectory(logsPath);
                File.AppendAllText(Path.Combine(logsPath, fileName), line + Environment.NewLine, new UTF8Encoding(false));
            }
        }
        catch { }
    }

    private void WriteAppLog(string message)
    {
        AppendLog("onyx-app.log", "[" + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "] " + message);
    }

    private string ReadPidFile()
    {
        try { return File.Exists(pidPath) ? File.ReadAllText(pidPath).Trim() : ""; }
        catch { return ""; }
    }

    private void RemovePidIfMatches(int processId)
    {
        try
        {
            int savedId;
            if (Int32.TryParse(ReadPidFile(), out savedId) && savedId == processId)
            {
                File.Delete(pidPath);
            }
        }
        catch { }
    }

    private void TryDeletePidFile()
    {
        try { if (File.Exists(pidPath)) File.Delete(pidPath); }
        catch { }
    }
}

internal static class OnyxTrayProgram
{
    [STAThread]
    private static void Main()
    {
        bool createdNew;
        using (Mutex mutex = new Mutex(true, @"Local\OnyxTrayApplication", out createdNew))
        {
            if (!createdNew)
            {
                MessageBox.Show("Onyx è già avviato. Cerca la sua icona vicino all'orologio.", "Onyx", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }

            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new OnyxTrayContext(AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar)));
            mutex.ReleaseMutex();
        }
    }
}
