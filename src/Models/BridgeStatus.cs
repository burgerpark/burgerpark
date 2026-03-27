namespace ComIpBridge.Models;

public enum BridgeState
{
    Stopped,
    Starting,
    Running,
    Error,
    Reconnecting
}

public class BridgeStatus
{
    public BridgeState State { get; set; } = BridgeState.Stopped;
    public string StatusText { get; set; } = "Stopped";
    public long BytesSent { get; set; }
    public long BytesReceived { get; set; }
    public DateTime? ConnectedSince { get; set; }
    public string? LastError { get; set; }
    public string? RemoteEndpoint { get; set; }

    public void Reset()
    {
        State = BridgeState.Stopped;
        StatusText = "Stopped";
        BytesSent = 0;
        BytesReceived = 0;
        ConnectedSince = null;
        LastError = null;
        RemoteEndpoint = null;
    }
}
