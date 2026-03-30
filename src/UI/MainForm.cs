using System.IO.Ports;
using Microsoft.Win32;
using ComIpBridge.Core;
using ComIpBridge.Models;
using ComIpBridge.Utils;

namespace ComIpBridge.UI;

public class MainForm : Form
{
    private readonly BridgeManager _manager = new();

    // Controls
    private readonly ListView _portListView;
    private readonly ToolStrip _toolStrip;
    private readonly StatusStrip _statusStrip;
    private readonly ToolStripStatusLabel _statusLabel;
    private readonly SplitContainer _splitContainer;
    private readonly DataMonitorPanel _monitorPanel;
    private readonly NotifyIcon _trayIcon;
    private readonly ContextMenuStrip _trayMenu;

    private string? _selectedBridgeId;

    public MainForm()
    {
        InitializeForm();

        // Initialize controls
        _toolStrip = CreateToolStrip();
        _statusStrip = CreateStatusStrip();
        _statusLabel = (ToolStripStatusLabel)_statusStrip.Items[0];

        _portListView = CreatePortListView();
        _monitorPanel = new DataMonitorPanel();

        _splitContainer = new SplitContainer
        {
            Dock = DockStyle.Fill,
            Orientation = Orientation.Horizontal,
            SplitterDistance = 280,
            Panel1MinSize = 150,
            Panel2MinSize = 100
        };
        _splitContainer.Panel1.Controls.Add(_portListView);
        _splitContainer.Panel2.Controls.Add(_monitorPanel);

        Controls.Add(_splitContainer);
        Controls.Add(_toolStrip);
        Controls.Add(_statusStrip);

        // Tray icon
        _trayMenu = CreateTrayMenu();
        _trayIcon = new NotifyIcon
        {
            Text = "COM-IP Bridge",
            Icon = SystemIcons.Application,
            ContextMenuStrip = _trayMenu,
            Visible = false
        };
        _trayIcon.DoubleClick += (_, _) => RestoreFromTray();

        // Events
        _manager.BridgeStatusChanged += OnBridgeStatusChanged;
        _manager.BridgeLogAdded += OnBridgeLogAdded;

        // Load saved config
        LoadConfiguration();

        UpdateStatusBar();

        // Auto-start enabled bridges on launch
        AutoStartBridges();
    }

    private void InitializeForm()
    {
        Text = "COM-IP Bridge v1.0 - 멀티포트 시리얼 브릿지  |  BurgerPark";
        Size = new Size(900, 650);
        MinimumSize = new Size(700, 500);
        StartPosition = FormStartPosition.CenterScreen;
        Icon = SystemIcons.Application;
        Font = new Font("Segoe UI", 9F);
    }

    #region Control Creation

    private ToolStrip CreateToolStrip()
    {
        var strip = new ToolStrip
        {
            ImageScalingSize = new Size(20, 20),
            GripStyle = ToolStripGripStyle.Hidden,
            Padding = new Padding(4, 2, 4, 2)
        };

        var btnAdd = new ToolStripButton("포트 추가") { ToolTipText = "새 브릿지 포트 추가" };
        btnAdd.Click += BtnAdd_Click;

        var btnEdit = new ToolStripButton("편집") { ToolTipText = "선택한 포트 설정 편집" };
        btnEdit.Click += BtnEdit_Click;

        var btnRemove = new ToolStripButton("삭제") { ToolTipText = "선택한 포트 삭제" };
        btnRemove.Click += BtnRemove_Click;

        var btnStartSelected = new ToolStripButton("시작") { ToolTipText = "선택한 포트 시작" };
        btnStartSelected.Click += BtnStartSelected_Click;

        var btnStopSelected = new ToolStripButton("정지") { ToolTipText = "선택한 포트 정지" };
        btnStopSelected.Click += BtnStopSelected_Click;

        var btnStartAll = new ToolStripButton("전체 시작") { ToolTipText = "활성화된 모든 포트 시작" };
        btnStartAll.Click += BtnStartAll_Click;

        var btnStopAll = new ToolStripButton("전체 정지") { ToolTipText = "모든 포트 정지" };
        btnStopAll.Click += BtnStopAll_Click;

        var btnExport = new ToolStripButton("내보내기") { ToolTipText = "설정 파일 내보내기" };
        btnExport.Click += BtnExport_Click;

        var btnImport = new ToolStripButton("가져오기") { ToolTipText = "설정 파일 가져오기" };
        btnImport.Click += BtnImport_Click;

        var chkStartup = new ToolStripButton("자동실행: OFF")
        {
            ToolTipText = "Windows 시작 시 자동 실행 등록/해제",
            CheckOnClick = true,
            Checked = IsRegisteredInStartup()
        };
        chkStartup.Text = chkStartup.Checked ? "자동실행: ON" : "자동실행: OFF";
        chkStartup.Click += (_, _) =>
        {
            SetStartupRegistration(chkStartup.Checked);
            chkStartup.Text = chkStartup.Checked ? "자동실행: ON" : "자동실행: OFF";
        };

        strip.Items.AddRange(new ToolStripItem[]
        {
            btnAdd, btnEdit, btnRemove,
            new ToolStripSeparator(),
            btnStartSelected, btnStopSelected,
            new ToolStripSeparator(),
            btnStartAll, btnStopAll,
            new ToolStripSeparator(),
            btnExport, btnImport,
            new ToolStripSeparator(),
            chkStartup
        });

        return strip;
    }

    private StatusStrip CreateStatusStrip()
    {
        var strip = new StatusStrip();
        strip.Items.Add(new ToolStripStatusLabel("Ready") { Spring = true, TextAlign = ContentAlignment.MiddleLeft });
        return strip;
    }

    private ListView CreatePortListView()
    {
        var lv = new ListView
        {
            Dock = DockStyle.Fill,
            View = View.Details,
            FullRowSelect = true,
            GridLines = true,
            MultiSelect = false,
            Font = new Font("Segoe UI", 9F)
        };

        lv.Columns.AddRange(new[]
        {
            new ColumnHeader { Text = "이름", Width = 100 },
            new ColumnHeader { Text = "COM 포트", Width = 80 },
            new ColumnHeader { Text = "모드", Width = 90 },
            new ColumnHeader { Text = "IP:포트", Width = 160 },
            new ColumnHeader { Text = "전송속도", Width = 80 },
            new ColumnHeader { Text = "상태", Width = 160 },
            new ColumnHeader { Text = "송신 (바이트)", Width = 90 },
            new ColumnHeader { Text = "수신 (바이트)", Width = 90 }
        });

        lv.SelectedIndexChanged += PortListView_SelectedIndexChanged;
        lv.DoubleClick += (_, _) => BtnEdit_Click(null, EventArgs.Empty);

        return lv;
    }

    private ContextMenuStrip CreateTrayMenu()
    {
        var menu = new ContextMenuStrip();
        menu.Items.Add("열기", null, (_, _) => RestoreFromTray());
        menu.Items.Add("전체 시작", null, (_, _) => _ = _manager.StartAllAsync());
        menu.Items.Add("전체 정지", null, (_, _) => _ = _manager.StopAllAsync());
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("종료", null, (_, _) => { _trayIcon.Visible = false; Application.Exit(); });
        return menu;
    }

    #endregion

    #region Event Handlers

    private void BtnAdd_Click(object? sender, EventArgs e)
    {
        var config = new BridgeConfig
        {
            Name = $"브릿지 {_manager.Bridges.Count + 1}"
        };

        using var dialog = new PortConfigDialog(config);
        if (dialog.ShowDialog(this) == DialogResult.OK)
        {
            _manager.AddBridge(config);
            RefreshPortList();
            SaveConfiguration();
        }
    }

    private void BtnEdit_Click(object? sender, EventArgs e)
    {
        if (_selectedBridgeId == null) return;

        var bridges = _manager.Bridges;
        if (!bridges.TryGetValue(_selectedBridgeId, out var bridge)) return;

        var wasRunning = bridge.Status.State == BridgeState.Running;
        if (wasRunning)
        {
            _ = bridge.StopAsync();
        }

        using var dialog = new PortConfigDialog(bridge.Config);
        if (dialog.ShowDialog(this) == DialogResult.OK)
        {
            RefreshPortList();
            SaveConfiguration();
            if (wasRunning)
                _ = bridge.StartAsync();
        }
        else if (wasRunning)
        {
            _ = bridge.StartAsync();
        }
    }

    private async void BtnRemove_Click(object? sender, EventArgs e)
    {
        if (_selectedBridgeId == null) return;

        var result = MessageBox.Show(this, "이 브릿지 포트를 삭제하시겠습니까?", "확인",
            MessageBoxButtons.YesNo, MessageBoxIcon.Question);
        if (result != DialogResult.Yes) return;

        await _manager.RemoveBridgeAsync(_selectedBridgeId);
        _selectedBridgeId = null;
        RefreshPortList();
        SaveConfiguration();
    }

    private async void BtnStartSelected_Click(object? sender, EventArgs e)
    {
        if (_selectedBridgeId == null) return;
        try { await _manager.StartBridgeAsync(_selectedBridgeId); }
        catch (Exception ex) { MessageBox.Show(this, ex.Message, "오류", MessageBoxButtons.OK, MessageBoxIcon.Error); }
    }

    private async void BtnStopSelected_Click(object? sender, EventArgs e)
    {
        if (_selectedBridgeId == null) return;
        await _manager.StopBridgeAsync(_selectedBridgeId);
    }

    private async void BtnStartAll_Click(object? sender, EventArgs e) => await _manager.StartAllAsync();
    private async void BtnStopAll_Click(object? sender, EventArgs e) => await _manager.StopAllAsync();

    private void BtnExport_Click(object? sender, EventArgs e)
    {
        using var dialog = new SaveFileDialog
        {
            Filter = "JSON files (*.json)|*.json",
            DefaultExt = "json",
            FileName = "com_ip_bridge_config.json"
        };
        if (dialog.ShowDialog(this) == DialogResult.OK)
        {
            ConfigManager.ExportToFile(_manager.GetAllConfigs(), dialog.FileName);
            MessageBox.Show(this, "설정을 내보냈습니다.", "내보내기", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
    }

    private void BtnImport_Click(object? sender, EventArgs e)
    {
        using var dialog = new OpenFileDialog
        {
            Filter = "JSON files (*.json)|*.json"
        };
        if (dialog.ShowDialog(this) != DialogResult.OK) return;

        try
        {
            var configs = ConfigManager.ImportFromFile(dialog.FileName);
            foreach (var config in configs)
            {
                config.Id = Guid.NewGuid().ToString("N")[..8]; // new ID to avoid conflicts
                _manager.AddBridge(config);
            }
            RefreshPortList();
            SaveConfiguration();
            MessageBox.Show(this, $"{configs.Count}개의 브릿지를 가져왔습니다.", "가져오기", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, $"가져오기 실패: {ex.Message}", "오류", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private void PortListView_SelectedIndexChanged(object? sender, EventArgs e)
    {
        if (_portListView.SelectedItems.Count == 0)
        {
            _selectedBridgeId = null;
            _monitorPanel.SetBridge(null);
            return;
        }

        _selectedBridgeId = _portListView.SelectedItems[0].Tag as string;
        if (_selectedBridgeId != null && _manager.Bridges.TryGetValue(_selectedBridgeId, out var bridge))
        {
            _monitorPanel.SetBridge(bridge);
        }
    }

    private void OnBridgeStatusChanged(string id, BridgeStatus status)
    {
        if (InvokeRequired)
        {
            BeginInvoke(() => OnBridgeStatusChanged(id, status));
            return;
        }
        UpdatePortListItem(id);
        UpdateStatusBar();
    }

    private void OnBridgeLogAdded(string id, LogEntry entry)
    {
        if (_selectedBridgeId == id)
            _monitorPanel.AddLogEntry(entry);
    }

    #endregion

    #region UI Refresh

    private void RefreshPortList()
    {
        _portListView.Items.Clear();
        foreach (var (id, bridge) in _manager.Bridges)
        {
            var config = bridge.Config;
            var status = bridge.Status;
            var item = new ListViewItem(new[]
            {
                config.Name,
                config.ComPort,
                config.Mode.ToString(),
                $"{config.RemoteIp}:{config.TcpPort}",
                config.BaudRate.ToString(),
                status.StatusText,
                status.BytesSent.ToString("N0"),
                status.BytesReceived.ToString("N0")
            })
            {
                Tag = id,
                ForeColor = status.State switch
                {
                    BridgeState.Running => Color.DarkGreen,
                    BridgeState.Error => Color.Red,
                    BridgeState.Reconnecting => Color.DarkOrange,
                    _ => Color.Black
                }
            };
            _portListView.Items.Add(item);
        }
    }

    private void UpdatePortListItem(string id)
    {
        foreach (ListViewItem item in _portListView.Items)
        {
            if (item.Tag as string != id) continue;
            if (!_manager.Bridges.TryGetValue(id, out var bridge)) continue;

            var status = bridge.Status;
            item.SubItems[5].Text = status.StatusText;
            item.SubItems[6].Text = status.BytesSent.ToString("N0");
            item.SubItems[7].Text = status.BytesReceived.ToString("N0");
            item.ForeColor = status.State switch
            {
                BridgeState.Running => Color.DarkGreen,
                BridgeState.Error => Color.Red,
                BridgeState.Reconnecting => Color.DarkOrange,
                _ => Color.Black
            };
            break;
        }
    }

    private void UpdateStatusBar()
    {
        var bridges = _manager.Bridges;
        int total = bridges.Count;
        int running = bridges.Values.Count(b => b.Status.State == BridgeState.Running);
        _statusLabel.Text = $"포트: {total}개  |  실행 중: {running}개  |  사용 가능 COM: {string.Join(", ", SerialPort.GetPortNames())}";
    }

    #endregion

    #region Configuration

    private void LoadConfiguration()
    {
        var configs = ConfigManager.Load();
        foreach (var config in configs)
            _manager.AddBridge(config);
        RefreshPortList();
    }

    private void SaveConfiguration()
    {
        ConfigManager.Save(_manager.GetAllConfigs());
    }

    private async void AutoStartBridges()
    {
        // Wait briefly for form to fully load
        await Task.Delay(500);

        int started = 0;
        int failed = 0;
        foreach (var (id, bridge) in _manager.Bridges)
        {
            if (!bridge.Config.Enabled) continue;
            try
            {
                await _manager.StartBridgeAsync(id);
                started++;
            }
            catch
            {
                failed++;
            }
        }

        if (started > 0 || failed > 0)
        {
            var msg = $"{started}개 브릿지 자동 시작됨";
            if (failed > 0) msg += $", {failed}개 실패";
            _statusLabel.Text = msg;
        }
    }

    #endregion

    #region Windows Startup

    private const string StartupRegistryKey = @"SOFTWARE\Microsoft\Windows\CurrentVersion\Run";
    private const string AppRegistryName = "ComIpBridge";

    private static bool IsRegisteredInStartup()
    {
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(StartupRegistryKey, false);
            return key?.GetValue(AppRegistryName) != null;
        }
        catch { return false; }
    }

    private static void SetStartupRegistration(bool register)
    {
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(StartupRegistryKey, true);
            if (key == null) return;

            if (register)
            {
                var exePath = Application.ExecutablePath;
                key.SetValue(AppRegistryName, $"\"{exePath}\" --minimized");
            }
            else
            {
                key.DeleteValue(AppRegistryName, false);
            }
        }
        catch (Exception ex)
        {
            MessageBox.Show($"자동실행 등록 실패: {ex.Message}",
                "오류", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    #endregion

    #region Minimize to Tray

    protected override void OnResize(EventArgs e)
    {
        base.OnResize(e);
        if (WindowState == FormWindowState.Minimized)
        {
            Hide();
            _trayIcon.Visible = true;
            _trayIcon.ShowBalloonTip(1000, "COM-IP Bridge", "백그라운드에서 실행 중입니다.", ToolTipIcon.Info);
        }
    }

    private void RestoreFromTray()
    {
        Show();
        WindowState = FormWindowState.Normal;
        _trayIcon.Visible = false;
        BringToFront();
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        base.OnFormClosing(e);
        SaveConfiguration();
        _manager.Dispose();
        _trayIcon.Visible = false;
        _trayIcon.Dispose();
    }

    #endregion
}
