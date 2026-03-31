namespace ComIpBridge.Utils;

/// <summary>
/// Crash-safe disk buffer for pending data.
/// Stores data chunks as individual files so nothing is lost on app crash.
/// </summary>
public class DiskBuffer : IDisposable
{
    private readonly string _bufferDir;
    private readonly object _lock = new();
    private long _totalBytes;
    private const long MaxBufferBytes = 10 * 1024 * 1024; // 10MB max
    private bool _disposed;

    public long TotalBytes { get { lock (_lock) return _totalBytes; } }
    public int Count { get { lock (_lock) return Directory.Exists(_bufferDir) ? Directory.GetFiles(_bufferDir, "*.buf").Length : 0; } }

    public DiskBuffer(string bridgeId)
    {
        _bufferDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "ComIpBridge", "buffer", bridgeId);
        Directory.CreateDirectory(_bufferDir);

        // Calculate existing buffer size on startup
        _totalBytes = 0;
        foreach (var file in Directory.GetFiles(_bufferDir, "*.buf"))
        {
            try { _totalBytes += new FileInfo(file).Length; }
            catch { }
        }
    }

    /// <summary>
    /// Persist a data chunk to disk. Returns false if buffer is full.
    /// </summary>
    public bool Enqueue(byte[] data)
    {
        lock (_lock)
        {
            if (_totalBytes + data.Length > MaxBufferBytes)
            {
                // Drop oldest to make room
                DropOldest(data.Length);
            }

            try
            {
                var fileName = $"{DateTime.UtcNow:yyyyMMddHHmmssfff}_{Guid.NewGuid():N}.buf";
                var filePath = Path.Combine(_bufferDir, fileName);
                File.WriteAllBytes(filePath, data);
                _totalBytes += data.Length;
                return true;
            }
            catch
            {
                return false;
            }
        }
    }

    /// <summary>
    /// Read and remove all buffered data in chronological order.
    /// Returns a materialized list so the lock is NOT held during enumeration.
    /// </summary>
    public List<byte[]> DequeueAll()
    {
        lock (_lock)
        {
            var result = new List<byte[]>();
            if (!Directory.Exists(_bufferDir)) return result;

            var files = Directory.GetFiles(_bufferDir, "*.buf");
            Array.Sort(files); // Sorted by timestamp in filename

            foreach (var file in files)
            {
                try
                {
                    var data = File.ReadAllBytes(file);
                    File.Delete(file);
                    _totalBytes -= data.Length;
                    if (data.Length > 0)
                        result.Add(data);
                }
                catch { continue; }
            }

            return result;
        }
    }

    /// <summary>
    /// Check if there's any buffered data
    /// </summary>
    public bool HasData()
    {
        lock (_lock)
        {
            if (!Directory.Exists(_bufferDir)) return false;
            return Directory.GetFiles(_bufferDir, "*.buf").Length > 0;
        }
    }

    /// <summary>
    /// Clear all buffered data
    /// </summary>
    public void Clear()
    {
        lock (_lock)
        {
            try
            {
                if (Directory.Exists(_bufferDir))
                {
                    foreach (var file in Directory.GetFiles(_bufferDir, "*.buf"))
                    {
                        try { File.Delete(file); } catch { }
                    }
                }
                _totalBytes = 0;
            }
            catch { }
        }
    }

    private void DropOldest(long needBytes)
    {
        var files = Directory.GetFiles(_bufferDir, "*.buf");
        Array.Sort(files);

        foreach (var file in files)
        {
            if (_totalBytes + needBytes <= MaxBufferBytes) break;
            try
            {
                var size = new FileInfo(file).Length;
                File.Delete(file);
                _totalBytes -= size;
            }
            catch { }
        }
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        GC.SuppressFinalize(this);
    }
}
