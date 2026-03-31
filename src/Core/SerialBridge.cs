using System.IO.Ports;
using System.Net;
using System.Net.Sockets;
using ComIpBridge.Models;

namespace ComIpBridge.Core;

public class SerialBridge : IDisposable
{
    private readonly BridgeConfig _config;
    private readonly BridgeStatus _status;
    private readonly List<LogEntry> _logBuffer = new();
    private readonly object _logLock = new();

    private SerialPort? _serialPort;
    private TcpListener? _tcpListener;
    private TcpClient? _tcpClient;
    private NetworkStream? _networkStream;
    private UdpClient? _udpClient;
    private IPEndPoint? _udpRemoteEndpoint;

    private CancellationTokenSource? _cts;
    private Task? _bridgeTask;
    private bool _disposed;

    public event Action<BridgeStatus>? StatusChanged;
    public event Action<LogEntry>? LogAdded;

    public BridgeConfig Config => _config;
    public BridgeStatus Status => _status;
    public IReadOnlyList<LogEntry> LogBuffer
    {
        get { lock (_logLock) return _logBuffer.ToList(); }
    }

    public SerialBridge(BridgeConfig config)
    {
        _config = config;
        _status = new BridgeStatus();
    }

    public async Task StartAsync()
    {
        if (_status.State == BridgeState.Running)
            return;

        _cts = new CancellationTokenSource();
        UpdateStatus(BridgeState.Starting, "Starting...");

        try
        {
            OpenSerialPort();
            _bridgeTask = _config.Mode switch
            {
                ConnectionMode.TcpServer => RunTcpServerAsync(_cts.Token),
                ConnectionMode.TcpClient => RunTcpClientAsync(_cts.Token),
                ConnectionMode.Udp => RunUdpAsync(_cts.Token),
                _ => throw new InvalidOperationException($"Unknown mode: {_config.Mode}")
            };
            await Task.CompletedTask;
        }
        catch (Exception ex)
        {
            UpdateStatus(BridgeState.Error, $"Start failed: {ex.Message}");
            _status.LastError = ex.Message;
            AddLog(LogDirection.System, null, $"Error: {ex.Message}");
            CleanupConnections();
            throw;
        }
    }

    public async Task StopAsync()
    {
        if (_status.State == BridgeState.Stopped)
            return;

        _cts?.Cancel();
        CleanupConnections();

        if (_bridgeTask != null)
        {
            try { await _bridgeTask.WaitAsync(TimeSpan.FromSeconds(5)); }
            catch { /* timeout or cancelled, ok */ }
        }

        UpdateStatus(BridgeState.Stopped, "정지됨");
        AddLog(LogDirection.System, null, "브릿지 정지됨");
    }

    public void ClearLog()
    {
        lock (_logLock) _logBuffer.Clear();
    }

    private void OpenSerialPort()
    {
        _serialPort = new SerialPort
        {
            PortName = _config.ComPort,
            BaudRate = _config.BaudRate,
            DataBits = _config.DataBits,
            StopBits = _config.StopBits switch
            {
                1 => System.IO.Ports.StopBits.One,
                1.5f => System.IO.Ports.StopBits.OnePointFive,
                2 => System.IO.Ports.StopBits.Two,
                _ => System.IO.Ports.StopBits.One
            },
            Parity = Enum.Parse<System.IO.Ports.Parity>(_config.Parity),
            Handshake = _config.FlowControl switch
            {
                FlowControlType.RtsCts => Handshake.RequestToSend,
                FlowControlType.XonXoff => Handshake.XOnXOff,
                _ => Handshake.None
            },
            ReadTimeout = 500,
            WriteTimeout = 10000,
            ReadBufferSize = 131072,  // 128KB
            WriteBufferSize = 131072, // 128KB
            ReceivedBytesThreshold = 1
        };

        if (_config.FlowControl == FlowControlType.DtrDsr)
        {
            _serialPort.DtrEnable = true;
        }

        _serialPort.Open();
        _serialPort.DiscardInBuffer();
        _serialPort.DiscardOutBuffer();
        AddLog(LogDirection.System, null, $"시리얼 포트 {_config.ComPort} 열림 ({_config.BaudRate} baud, 버퍼 128KB)");
    }

    #region TCP Server Mode

    private async Task RunTcpServerAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            try
            {
                var bindAddress = IPAddress.Parse(_config.RemoteIp);
                _tcpListener = new TcpListener(bindAddress, _config.TcpPort);
                _tcpListener.Start();

                UpdateStatus(BridgeState.Running, $"Listening on {_config.RemoteIp}:{_config.TcpPort}");
                AddLog(LogDirection.System, null, $"TCP Server listening on {_config.RemoteIp}:{_config.TcpPort}");

                while (!ct.IsCancellationRequested)
                {
                    TcpClient client;
                    try
                    {
                        client = await _tcpListener.AcceptTcpClientAsync(ct);
                    }
                    catch (OperationCanceledException) { break; }

                    var endpoint = client.Client.RemoteEndPoint?.ToString() ?? "unknown";
                    _status.RemoteEndpoint = endpoint;
                    _status.ConnectedSince = DateTime.Now;
                    UpdateStatus(BridgeState.Running, $"Connected: {endpoint}");
                    AddLog(LogDirection.System, null, $"Client connected: {endpoint}");

                    // Disconnect previous client if any
                    DisconnectTcpClient();

                    _tcpClient = client;
                    _networkStream = client.GetStream();

                    await RunBridgeLoopAsync(ct);

                    AddLog(LogDirection.System, null, $"Client disconnected: {endpoint}");
                    _status.RemoteEndpoint = null;
                    _status.ConnectedSince = null;
                    UpdateStatus(BridgeState.Running, $"Listening on {_config.RemoteIp}:{_config.TcpPort}");
                }
            }
            catch (OperationCanceledException) { break; }
            catch (Exception ex)
            {
                if (ct.IsCancellationRequested) break;
                AddLog(LogDirection.System, null, $"Server error: {ex.Message}");
                UpdateStatus(BridgeState.Error, $"Error: {ex.Message}");
                _status.LastError = ex.Message;

                _tcpListener?.Stop();
                _tcpListener = null;

                if (!_config.AutoReconnect) break;
                UpdateStatus(BridgeState.Reconnecting, "Reconnecting...");
                try { await Task.Delay(_config.ReconnectIntervalMs, ct); }
                catch (OperationCanceledException) { break; }
            }
        }
    }

    #endregion

    #region TCP Client Mode

    private async Task RunTcpClientAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            try
            {
                if (_config.ConnectOnData)
                {
                    UpdateStatus(BridgeState.Running, "Waiting for data (lazy connect)...");
                    AddLog(LogDirection.System, null, "Waiting for COM data before connecting...");
                    await WaitForSerialDataAsync(ct);
                }

                _tcpClient = new TcpClient();
                UpdateStatus(BridgeState.Running, $"Connecting to {_config.RemoteIp}:{_config.TcpPort}...");

                using var connectCts = CancellationTokenSource.CreateLinkedTokenSource(ct);
                connectCts.CancelAfter(10000);
                await _tcpClient.ConnectAsync(_config.RemoteIp, _config.TcpPort, connectCts.Token);

                _networkStream = _tcpClient.GetStream();
                _status.RemoteEndpoint = $"{_config.RemoteIp}:{_config.TcpPort}";
                _status.ConnectedSince = DateTime.Now;
                UpdateStatus(BridgeState.Running, $"Connected to {_config.RemoteIp}:{_config.TcpPort}");
                AddLog(LogDirection.System, null, $"Connected to {_config.RemoteIp}:{_config.TcpPort}");

                await RunBridgeLoopAsync(ct);

                AddLog(LogDirection.System, null, "Connection closed");
            }
            catch (OperationCanceledException) { break; }
            catch (Exception ex)
            {
                if (ct.IsCancellationRequested) break;
                AddLog(LogDirection.System, null, $"Connection error: {ex.Message}");
                _status.LastError = ex.Message;
            }
            finally
            {
                DisconnectTcpClient();
                _status.RemoteEndpoint = null;
                _status.ConnectedSince = null;
            }

            if (!_config.AutoReconnect || ct.IsCancellationRequested) break;
            UpdateStatus(BridgeState.Reconnecting, $"Reconnecting in {_config.ReconnectIntervalMs / 1000}s...");
            try { await Task.Delay(_config.ReconnectIntervalMs, ct); }
            catch (OperationCanceledException) { break; }
        }
    }

    private async Task WaitForSerialDataAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            if (_serialPort?.BytesToRead > 0)
                return;
            await Task.Delay(50, ct);
        }
    }

    #endregion

    #region UDP Mode

    private async Task RunUdpAsync(CancellationToken ct)
    {
        try
        {
            if (_config.Mode == ConnectionMode.Udp)
            {
                _udpClient = new UdpClient(_config.TcpPort);
                _udpRemoteEndpoint = new IPEndPoint(IPAddress.Parse(_config.RemoteIp), _config.TcpPort);

                UpdateStatus(BridgeState.Running, $"UDP on port {_config.TcpPort}");
                AddLog(LogDirection.System, null, $"UDP mode on port {_config.TcpPort}");

                var comToUdpTask = Task.Run(async () =>
                {
                    var buffer = new byte[4096];
                    while (!ct.IsCancellationRequested)
                    {
                        try
                        {
                            if (_serialPort?.BytesToRead > 0)
                            {
                                int read = _serialPort.Read(buffer, 0, Math.Min(buffer.Length, _serialPort.BytesToRead));
                                if (read > 0 && _udpRemoteEndpoint != null)
                                {
                                    await _udpClient!.SendAsync(buffer.AsMemory(0, read), _udpRemoteEndpoint, ct);
                                    _status.BytesSent += read;
                                    OnDataTransferred(LogDirection.ComToTcp, buffer, read);
                                }
                            }
                            else
                            {
                                await Task.Delay(10, ct);
                            }
                        }
                        catch (OperationCanceledException) { break; }
                        catch (TimeoutException) { }
                        catch (Exception ex)
                        {
                            AddLog(LogDirection.System, null, $"COM→UDP error: {ex.Message}");
                        }
                    }
                }, ct);

                var udpToComTask = Task.Run(async () =>
                {
                    while (!ct.IsCancellationRequested)
                    {
                        try
                        {
                            var result = await _udpClient!.ReceiveAsync(ct);
                            _udpRemoteEndpoint = result.RemoteEndPoint;
                            _serialPort?.Write(result.Buffer, 0, result.Buffer.Length);
                            _status.BytesReceived += result.Buffer.Length;
                            OnDataTransferred(LogDirection.TcpToCom, result.Buffer, result.Buffer.Length);
                        }
                        catch (OperationCanceledException) { break; }
                        catch (Exception ex)
                        {
                            AddLog(LogDirection.System, null, $"UDP→COM error: {ex.Message}");
                        }
                    }
                }, ct);

                await Task.WhenAll(comToUdpTask, udpToComTask);
            }
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            AddLog(LogDirection.System, null, $"UDP error: {ex.Message}");
            UpdateStatus(BridgeState.Error, $"Error: {ex.Message}");
        }
        finally
        {
            _udpClient?.Close();
            _udpClient = null;
        }
    }

    #endregion

    #region Bridge Loop (COM <-> TCP)

    private async Task RunBridgeLoopAsync(CancellationToken ct)
    {
        DateTime lastActivity = DateTime.Now;
        var comToTcpTask = Task.Run(async () =>
        {
            var buffer = new byte[65536];
            while (!ct.IsCancellationRequested)
            {
                try
                {
                    if (_serialPort?.BytesToRead > 0)
                    {
                        // Wait briefly for more data to arrive (receipt data comes in bursts)
                        await Task.Delay(50, ct);

                        int available = _serialPort.BytesToRead;
                        if (available > 0)
                        {
                            int read = _serialPort.Read(buffer, 0, Math.Min(buffer.Length, available));
                            if (read > 0 && _networkStream != null)
                            {
                                await _networkStream.WriteAsync(buffer.AsMemory(0, read), ct);
                                await _networkStream.FlushAsync(ct);
                                _status.BytesSent += read;
                                lastActivity = DateTime.Now;
                                OnDataTransferred(LogDirection.ComToTcp, buffer, read);
                                StatusChanged?.Invoke(_status);
                            }
                        }
                    }
                    else
                    {
                        await Task.Delay(10, ct);
                    }
                }
                catch (OperationCanceledException) { break; }
                catch (TimeoutException) { }
                catch (IOException) { break; }
                catch (Exception ex)
                {
                    AddLog(LogDirection.System, null, $"COM→TCP 오류: {ex.Message}");
                    break;
                }
            }
        }, ct);

        var tcpToComTask = Task.Run(async () =>
        {
            var buffer = new byte[65536];
            while (!ct.IsCancellationRequested)
            {
                try
                {
                    if (_networkStream == null) break;
                    int read = await _networkStream.ReadAsync(buffer, ct);
                    if (read == 0) break; // Connection closed

                    // Write in chunks to avoid overwhelming serial port
                    int offset = 0;
                    while (offset < read)
                    {
                        int chunkSize = Math.Min(read - offset, _serialPort?.WriteBufferSize ?? 4096);
                        _serialPort?.Write(buffer, offset, chunkSize);
                        offset += chunkSize;

                        // Small delay between chunks for serial port to process
                        if (offset < read)
                            await Task.Delay(10, ct);
                    }

                    _status.BytesReceived += read;
                    lastActivity = DateTime.Now;
                    OnDataTransferred(LogDirection.TcpToCom, buffer, read);
                    StatusChanged?.Invoke(_status);
                }
                catch (OperationCanceledException) { break; }
                catch (IOException) { break; }
                catch (Exception ex)
                {
                    AddLog(LogDirection.System, null, $"TCP→COM 오류: {ex.Message}");
                    break;
                }
            }
        }, ct);

        // Inactivity timeout check
        var timeoutTask = Task.Run(async () =>
        {
            if (_config.InactivityTimeoutMs <= 0) return;
            while (!ct.IsCancellationRequested)
            {
                await Task.Delay(1000, ct);
                if ((DateTime.Now - lastActivity).TotalMilliseconds > _config.InactivityTimeoutMs)
                {
                    AddLog(LogDirection.System, null, "Inactivity timeout - disconnecting");
                    break;
                }
            }
        }, ct);

        await Task.WhenAny(comToTcpTask, tcpToComTask, timeoutTask);
    }

    #endregion

    #region Helpers

    private void OnDataTransferred(LogDirection direction, byte[] buffer, int count)
    {
        if (!_config.EnableLogging) return;
        var data = new byte[count];
        Array.Copy(buffer, data, count);
        AddLog(direction, data, null);
    }

    private void AddLog(LogDirection direction, byte[]? data, string? message)
    {
        var entry = new LogEntry
        {
            Direction = direction,
            Data = data,
            Message = message
        };

        lock (_logLock)
        {
            _logBuffer.Add(entry);
            while (_logBuffer.Count > _config.MaxLogLines)
                _logBuffer.RemoveAt(0);
        }

        LogAdded?.Invoke(entry);
    }

    private void UpdateStatus(BridgeState state, string text)
    {
        _status.State = state;
        _status.StatusText = text;
        StatusChanged?.Invoke(_status);
    }

    private void DisconnectTcpClient()
    {
        _networkStream?.Close();
        _networkStream = null;
        _tcpClient?.Close();
        _tcpClient = null;
    }

    private void CleanupConnections()
    {
        DisconnectTcpClient();
        _tcpListener?.Stop();
        _tcpListener = null;
        _udpClient?.Close();
        _udpClient = null;

        try { _serialPort?.Close(); } catch { }
        _serialPort?.Dispose();
        _serialPort = null;
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _cts?.Cancel();
        CleanupConnections();
        _cts?.Dispose();
        GC.SuppressFinalize(this);
    }

    #endregion
}
