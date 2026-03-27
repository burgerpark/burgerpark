using ComIpBridge.UI;

namespace ComIpBridge;

static class Program
{
    [STAThread]
    static void Main(string[] args)
    {
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
}
