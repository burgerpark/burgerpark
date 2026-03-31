using System.Net;
using System.Text;
using System.Text.Json;

namespace ComIpBridge.Core;

/// <summary>
/// Lightweight HTTP health check endpoint for remote monitoring.
/// GET http://localhost:18080/health → JSON status of all bridges
/// </summary>
public class HealthCheckServer : IDisposable
{
    private readonly BridgeManager _manager;
    private readonly HttpListener _listener;
    private readonly CancellationTokenSource _cts = new();
    private Task? _listenTask;
    private bool _disposed;

    public int Port { get; }

    public HealthCheckServer(BridgeManager manager, int port = 18080)
    {
        _manager = manager;
        Port = port;
        _listener = new HttpListener();
        _listener.Prefixes.Add($"http://localhost:{port}/");
    }

    public bool TryStart()
    {
        try
        {
            _listener.Start();
            _listenTask = Task.Run(() => ListenLoop(_cts.Token));
            return true;
        }
        catch
        {
            // Port in use or permission denied - not critical
            return false;
        }
    }

    private async Task ListenLoop(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            try
            {
                var context = await _listener.GetContextAsync().WaitAsync(ct);
                _ = Task.Run(() => HandleRequest(context), ct);
            }
            catch (OperationCanceledException) { break; }
            catch { /* listener stopped */ break; }
        }
    }

    private void HandleRequest(HttpListenerContext context)
    {
        try
        {
            var response = context.Response;
            response.ContentType = "application/json; charset=utf-8";
            response.Headers.Add("Access-Control-Allow-Origin", "*");

            var bridges = _manager.Bridges;
            var status = new
            {
                app = "COM-IP Bridge",
                version = "2.0.0",
                timestamp = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"),
                healthy = bridges.Values.All(b =>
                    b.Status.State != Models.BridgeState.Error),
                bridges = bridges.Values.Select(b => new
                {
                    name = b.Config.Name,
                    comPort = b.Config.ComPort,
                    mode = b.Config.Mode.ToString(),
                    state = b.Status.State.ToString(),
                    statusText = b.Status.StatusText,
                    bytesSent = b.Status.BytesSent,
                    bytesReceived = b.Status.BytesReceived,
                    connectedSince = b.Status.ConnectedSince?.ToString("yyyy-MM-dd HH:mm:ss"),
                    lastError = b.Status.LastError
                }).ToArray()
            };

            var json = JsonSerializer.Serialize(status, new JsonSerializerOptions
            {
                WriteIndented = true
            });

            var buffer = Encoding.UTF8.GetBytes(json);
            response.ContentLength64 = buffer.Length;
            response.StatusCode = status.healthy ? 200 : 503;
            response.OutputStream.Write(buffer, 0, buffer.Length);
            response.OutputStream.Close();
        }
        catch { }
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _cts.Cancel();
        try { _listener.Stop(); } catch { }
        _listener.Close();
        _cts.Dispose();
        GC.SuppressFinalize(this);
    }
}
