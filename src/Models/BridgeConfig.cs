namespace ComIpBridge.Models;

public enum ConnectionMode
{
    TcpServer,
    TcpClient,
    Udp
}

public enum FlowControlType
{
    None,
    RtsCts,
    DtrDsr,
    XonXoff
}

public class BridgeConfig
{
    public string Id { get; set; } = Guid.NewGuid().ToString("N")[..8];
    public string Name { get; set; } = "";
    public bool Enabled { get; set; } = true;

    // Serial Port Settings
    public string ComPort { get; set; } = "COM1";
    public int BaudRate { get; set; } = 9600;
    public int DataBits { get; set; } = 8;
    public float StopBits { get; set; } = 1;
    public string Parity { get; set; } = "None";
    public FlowControlType FlowControl { get; set; } = FlowControlType.None;

    // Network Settings
    public ConnectionMode Mode { get; set; } = ConnectionMode.TcpServer;
    public string RemoteIp { get; set; } = "0.0.0.0";
    public int TcpPort { get; set; } = 5000;

    // Advanced Settings
    public bool AutoReconnect { get; set; } = true;
    public int ReconnectIntervalMs { get; set; } = 3000;
    public bool ConnectOnData { get; set; } = false;
    public int InactivityTimeoutMs { get; set; } = 0; // 0 = disabled
    public bool EnableRfc2217 { get; set; } = false;
    public bool EnableLogging { get; set; } = true;
    public int MaxLogLines { get; set; } = 1000;

    public BridgeConfig Clone()
    {
        return (BridgeConfig)MemberwiseClone();
    }
}
