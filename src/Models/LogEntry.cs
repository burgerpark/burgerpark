namespace ComIpBridge.Models;

public enum LogDirection
{
    ComToTcp,
    TcpToCom,
    System
}

public class LogEntry
{
    public DateTime Timestamp { get; set; } = DateTime.Now;
    public LogDirection Direction { get; set; }
    public byte[]? Data { get; set; }
    public string? Message { get; set; }

    public string GetDisplayText()
    {
        if (Message != null)
            return $"[{Timestamp:HH:mm:ss.fff}] {Message}";

        var dir = Direction == LogDirection.ComToTcp ? "COM→TCP" : "TCP→COM";
        var hex = Data != null ? BitConverter.ToString(Data).Replace("-", " ") : "";
        var ascii = Data != null ? GetPrintableAscii(Data) : "";
        return $"[{Timestamp:HH:mm:ss.fff}] {dir} ({Data?.Length ?? 0}B): {hex}  |  {ascii}";
    }

    private static string GetPrintableAscii(byte[] data)
    {
        var chars = new char[data.Length];
        for (int i = 0; i < data.Length; i++)
            chars[i] = data[i] >= 0x20 && data[i] < 0x7F ? (char)data[i] : '.';
        return new string(chars);
    }
}
