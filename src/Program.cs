using ComIpBridge.UI;

namespace ComIpBridge;

static class Program
{
    [STAThread]
    static void Main(string[] args)
    {
        // Global exception handlers to prevent silent crashes
        Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
        Application.ThreadException += (_, e) =>
        {
            LogFatalError(e.Exception);
            MessageBox.Show(
                $"예기치 않은 오류가 발생했습니다.\n프로그램을 계속 실행합니다.\n\n{e.Exception.Message}",
                "COM-IP Bridge 오류", MessageBoxButtons.OK, MessageBoxIcon.Error);
        };
        AppDomain.CurrentDomain.UnhandledException += (_, e) =>
        {
            if (e.ExceptionObject is Exception ex)
                LogFatalError(ex);
        };

        bool startMinimized = args.Contains("--minimized", StringComparer.OrdinalIgnoreCase);

        ApplicationConfiguration.Initialize();
        var form = new MainForm();

        if (startMinimized)
        {
            form.WindowState = FormWindowState.Minimized;
            form.ShowInTaskbar = false;
        }

        Application.Run(form);
    }

    private static void LogFatalError(Exception ex)
    {
        try
        {
            var logDir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                "ComIpBridge", "logs");
            Directory.CreateDirectory(logDir);
            var logFile = Path.Combine(logDir, "crash.log");
            File.AppendAllText(logFile,
                $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] {ex}\n---\n");
        }
        catch { /* logging must never throw */ }
    }
}
