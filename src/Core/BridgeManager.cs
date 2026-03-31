using ComIpBridge.Models;
using ComIpBridge.Utils;

namespace ComIpBridge.Core;

public class BridgeManager : IDisposable
{
    private readonly Dictionary<string, SerialBridge> _bridges = new();
    private readonly object _lock = new();
    private readonly FileLogger _fileLogger = new();
    private readonly System.Timers.Timer _watchdogTimer;
    private int _watchdogRunning;

    public event Action? BridgesChanged;
    public event Action<string, BridgeStatus>? BridgeStatusChanged;
    public event Action<string, LogEntry>? BridgeLogAdded;
    public event Action<string>? BridgeFaulted;

    public BridgeManager()
    {
        // Watchdog: check every 15 seconds for dead bridges that should be running
        _watchdogTimer = new System.Timers.Timer(15000);
        _watchdogTimer.Elapsed += async (_, _) => await WatchdogCheckAsync();
        _watchdogTimer.AutoReset = true;
        _watchdogTimer.Start();
    }

    public IReadOnlyDictionary<string, SerialBridge> Bridges
    {
        get { lock (_lock) return new Dictionary<string, SerialBridge>(_bridges); }
    }

    public SerialBridge AddBridge(BridgeConfig config)
    {
        lock (_lock)
        {
            if (_bridges.ContainsKey(config.Id))
                throw new InvalidOperationException($"Bridge {config.Id} already exists");

            var bridge = new SerialBridge(config, _fileLogger);
            bridge.StatusChanged += status => BridgeStatusChanged?.Invoke(config.Id, status);
            bridge.LogAdded += entry => BridgeLogAdded?.Invoke(config.Id, entry);
            bridge.BridgeFaulted += name => BridgeFaulted?.Invoke(name);
            _bridges[config.Id] = bridge;
            BridgesChanged?.Invoke();
            return bridge;
        }
    }

    public async Task RemoveBridgeAsync(string id)
    {
        SerialBridge? bridge;
        lock (_lock)
        {
            if (!_bridges.TryGetValue(id, out bridge))
                return;
            _bridges.Remove(id);
        }

        await bridge.StopAsync();
        bridge.Dispose();
        BridgesChanged?.Invoke();
    }

    public async Task StartBridgeAsync(string id)
    {
        SerialBridge? bridge;
        lock (_lock) _bridges.TryGetValue(id, out bridge);
        if (bridge != null) await bridge.StartAsync();
    }

    public async Task StopBridgeAsync(string id)
    {
        SerialBridge? bridge;
        lock (_lock) _bridges.TryGetValue(id, out bridge);
        if (bridge != null) await bridge.StopAsync();
    }

    public async Task StartAllAsync()
    {
        List<SerialBridge> bridges;
        lock (_lock) bridges = _bridges.Values.Where(b => b.Config.Enabled).ToList();
        foreach (var bridge in bridges)
        {
            try { await bridge.StartAsync(); }
            catch { /* logged internally */ }
        }
    }

    public async Task StopAllAsync()
    {
        List<SerialBridge> bridges;
        lock (_lock) bridges = _bridges.Values.ToList();
        foreach (var bridge in bridges)
        {
            try { await bridge.StopAsync(); }
            catch { /* logged internally */ }
        }
    }

    public List<BridgeConfig> GetAllConfigs()
    {
        lock (_lock) return _bridges.Values.Select(b => b.Config).ToList();
    }

    private async Task WatchdogCheckAsync()
    {
        // Prevent re-entry if previous check is still running
        if (Interlocked.CompareExchange(ref _watchdogRunning, 1, 0) != 0)
            return;

        try
        {
            await WatchdogCheckCoreAsync();
        }
        finally
        {
            Interlocked.Exchange(ref _watchdogRunning, 0);
        }
    }

    private async Task WatchdogCheckCoreAsync()
    {
        List<(string id, SerialBridge bridge)> deadBridges;
        lock (_lock)
        {
            deadBridges = _bridges
                .Where(kvp => kvp.Value.Config.Enabled
                    && kvp.Value.Config.AutoReconnect
                    && kvp.Value.Status.State == Models.BridgeState.Error)
                .Select(kvp => (kvp.Key, kvp.Value))
                .ToList();
        }

        foreach (var (id, bridge) in deadBridges)
        {
            try
            {
                _fileLogger.Log(bridge.Config.Name, "워치독: 장애 감지, 자동 재시작 시도");
                await bridge.StopAsync();
                await Task.Delay(1000);
                await bridge.StartAsync();
                _fileLogger.Log(bridge.Config.Name, "워치독: 재시작 성공");
            }
            catch (Exception ex)
            {
                _fileLogger.LogError(bridge.Config.Name, "워치독 재시작", ex);
            }
        }
    }

    public void Dispose()
    {
        _watchdogTimer.Stop();
        _watchdogTimer.Dispose();
        lock (_lock)
        {
            foreach (var bridge in _bridges.Values)
            {
                try { bridge.StopAsync().Wait(3000); } catch { }
                bridge.Dispose();
            }
            _bridges.Clear();
        }
        _fileLogger.Dispose();
        GC.SuppressFinalize(this);
    }

    public string GetLogDirectory() => _fileLogger.GetLogDirectory();
}
