using ComIpBridge.Core;
using ComIpBridge.Models;

namespace ComIpBridge.UI;

public class DataMonitorPanel : UserControl
{
    private readonly RichTextBox _logTextBox;
    private readonly ToolStrip _monitorToolStrip;
    private readonly CheckBox _chkAutoScroll;
    private readonly ComboBox _cboDisplayMode;
    private SerialBridge? _currentBridge;

    private enum DisplayMode { HexAndAscii, HexOnly, AsciiOnly }
    private DisplayMode _displayMode = DisplayMode.HexAndAscii;

    public DataMonitorPanel()
    {
        Dock = DockStyle.Fill;

        _monitorToolStrip = new ToolStrip { GripStyle = ToolStripGripStyle.Hidden };

        var lblTitle = new ToolStripLabel("데이터 모니터") { Font = new Font("Segoe UI", 9F, FontStyle.Bold) };

        _cboDisplayMode = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Width = 120 };
        _cboDisplayMode.Items.AddRange(new object[] { "Hex + ASCII", "Hex만", "ASCII만" });
        _cboDisplayMode.SelectedIndex = 0;
        _cboDisplayMode.SelectedIndexChanged += (_, _) =>
        {
            _displayMode = (DisplayMode)_cboDisplayMode.SelectedIndex;
            RefreshLog();
        };
        var hostDisplay = new ToolStripControlHost(_cboDisplayMode);

        _chkAutoScroll = new CheckBox { Text = "자동 스크롤", Checked = true };
        var hostScroll = new ToolStripControlHost(_chkAutoScroll);

        var btnClear = new ToolStripButton("지우기");
        btnClear.Click += (_, _) =>
        {
            _logTextBox!.Clear();
            _currentBridge?.ClearLog();
        };

        var btnCopy = new ToolStripButton("전체 복사");
        btnCopy.Click += (_, _) =>
        {
            if (_logTextBox!.TextLength > 0)
                Clipboard.SetText(_logTextBox.Text);
        };

        _monitorToolStrip.Items.AddRange(new ToolStripItem[]
        {
            lblTitle,
            new ToolStripSeparator(),
            hostDisplay,
            new ToolStripSeparator(),
            hostScroll,
            new ToolStripSeparator(),
            btnClear,
            btnCopy
        });

        _logTextBox = new RichTextBox
        {
            Dock = DockStyle.Fill,
            ReadOnly = true,
            BackColor = Color.FromArgb(30, 30, 30),
            ForeColor = Color.LightGray,
            Font = new Font("Consolas", 9F),
            WordWrap = false,
            ScrollBars = RichTextBoxScrollBars.Both
        };

        Controls.Add(_logTextBox);
        Controls.Add(_monitorToolStrip);
    }

    public void SetBridge(SerialBridge? bridge)
    {
        _currentBridge = bridge;
        RefreshLog();
    }

    public void AddLogEntry(LogEntry entry)
    {
        if (InvokeRequired)
        {
            try { BeginInvoke(() => AddLogEntry(entry)); }
            catch { /* form closing */ }
            return;
        }

        AppendLogEntry(entry);
    }

    private void RefreshLog()
    {
        if (InvokeRequired)
        {
            BeginInvoke(RefreshLog);
            return;
        }

        _logTextBox.Clear();
        if (_currentBridge == null) return;

        _logTextBox.SuspendLayout();
        foreach (var entry in _currentBridge.LogBuffer)
            AppendLogEntry(entry);
        _logTextBox.ResumeLayout();
    }

    private void AppendLogEntry(LogEntry entry)
    {
        var color = entry.Direction switch
        {
            LogDirection.ComToTcp => Color.LightGreen,
            LogDirection.TcpToCom => Color.LightSkyBlue,
            LogDirection.System => Color.Yellow,
            _ => Color.LightGray
        };

        string text = FormatEntry(entry);

        _logTextBox.SelectionStart = _logTextBox.TextLength;
        _logTextBox.SelectionLength = 0;
        _logTextBox.SelectionColor = color;
        _logTextBox.AppendText(text + Environment.NewLine);

        if (_chkAutoScroll.Checked)
        {
            _logTextBox.SelectionStart = _logTextBox.TextLength;
            _logTextBox.ScrollToCaret();
        }
    }

    private string FormatEntry(LogEntry entry)
    {
        if (entry.Message != null)
            return $"[{entry.Timestamp:HH:mm:ss.fff}] {entry.Message}";

        if (entry.Data == null)
            return $"[{entry.Timestamp:HH:mm:ss.fff}] (데이터 없음)";

        var dir = entry.Direction == LogDirection.ComToTcp ? "COM→TCP" : "TCP→COM";
        var prefix = $"[{entry.Timestamp:HH:mm:ss.fff}] {dir} ({entry.Data.Length}B): ";

        return _displayMode switch
        {
            DisplayMode.HexOnly => prefix + BitConverter.ToString(entry.Data).Replace("-", " "),
            DisplayMode.AsciiOnly => prefix + GetPrintableAscii(entry.Data),
            _ => prefix + BitConverter.ToString(entry.Data).Replace("-", " ") + "  |  " + GetPrintableAscii(entry.Data)
        };
    }

    private static string GetPrintableAscii(byte[] data)
    {
        var chars = new char[data.Length];
        for (int i = 0; i < data.Length; i++)
            chars[i] = data[i] >= 0x20 && data[i] < 0x7F ? (char)data[i] : '.';
        return new string(chars);
    }
}
