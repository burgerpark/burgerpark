namespace ComIpBridge.Utils;

public class FileLogger : IDisposable
{
    private readonly string _logDir;
    private readonly object _lock = new();
    private StreamWriter? _writer;
    private string _currentDate = "";
    private bool _disposed;

    public FileLogger()
    {
        _logDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "ComIpBridge", "logs");
        Directory.CreateDirectory(_logDir);
    }

    public void Log(string bridgeName, string message)
    {
        lock (_lock)
        {
            try
            {
                EnsureWriter();
                _writer?.WriteLine($"[{DateTime.Now:yyyy-MM-dd HH:mm:ss.fff}] [{bridgeName}] {message}");
                _writer?.Flush();
            }
            catch { /* logging should never crash the app */ }
        }
    }

    public void LogData(string bridgeName, string direction, byte[] data, int length)
    {
        var hex = BitConverter.ToString(data, 0, Math.Min(length, 256)).Replace("-", " ");
        var truncated = length > 256 ? $" ... ({length}B total)" : "";
        Log(bridgeName, $"{direction} [{length}B]: {hex}{truncated}");
    }

    public void LogError(string bridgeName, string context, Exception ex)
    {
        Log(bridgeName, $"오류 [{context}]: {ex.Message}");
    }

    private void EnsureWriter()
    {
        var today = DateTime.Now.ToString("yyyy-MM-dd");
        if (today == _currentDate && _writer != null) return;

        _writer?.Close();
        _currentDate = today;
        var filePath = Path.Combine(_logDir, $"bridge_{today}.log");
        _writer = new StreamWriter(filePath, append: true, encoding: System.Text.Encoding.UTF8)
        {
            AutoFlush = true
        };

        // Clean old logs (keep 30 days)
        CleanOldLogs(30);
    }

    private void CleanOldLogs(int keepDays)
    {
        try
        {
            var cutoff = DateTime.Now.AddDays(-keepDays);
            foreach (var file in Directory.GetFiles(_logDir, "bridge_*.log"))
            {
                if (File.GetLastWriteTime(file) < cutoff)
                    File.Delete(file);
            }
        }
        catch { }
    }

    public string GetLogDirectory() => _logDir;

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        lock (_lock)
        {
            _writer?.Close();
            _writer = null;
        }
        GC.SuppressFinalize(this);
    }
}
