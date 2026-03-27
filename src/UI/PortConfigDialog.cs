using System.IO.Ports;
using ComIpBridge.Models;

namespace ComIpBridge.UI;

public class PortConfigDialog : Form
{
    private readonly BridgeConfig _config;

    // General
    private readonly TextBox _txtName;
    private readonly ComboBox _cboComPort;
    private readonly ComboBox _cboMode;
    private readonly TextBox _txtIp;
    private readonly NumericUpDown _nudPort;

    // Serial
    private readonly ComboBox _cboBaudRate;
    private readonly ComboBox _cboDataBits;
    private readonly ComboBox _cboStopBits;
    private readonly ComboBox _cboParity;
    private readonly ComboBox _cboFlowControl;

    // Advanced
    private readonly CheckBox _chkAutoReconnect;
    private readonly NumericUpDown _nudReconnectInterval;
    private readonly CheckBox _chkConnectOnData;
    private readonly NumericUpDown _nudInactivityTimeout;
    private readonly CheckBox _chkEnableRfc2217;
    private readonly CheckBox _chkEnableLogging;
    private readonly CheckBox _chkEnabled;

    public PortConfigDialog(BridgeConfig config)
    {
        _config = config;

        Text = config.Name == "" ? "Add Bridge Port" : $"Edit: {config.Name}";
        Size = new Size(480, 560);
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        StartPosition = FormStartPosition.CenterParent;
        Font = new Font("Segoe UI", 9F);

        var tabs = new TabControl { Dock = DockStyle.Fill };
        var tabGeneral = new TabPage("General");
        var tabSerial = new TabPage("Serial Port");
        var tabAdvanced = new TabPage("Advanced");

        // ── General Tab ──
        int y = 15;
        _chkEnabled = AddCheckBox(tabGeneral, "Enabled", config.Enabled, ref y);

        _txtName = AddTextBox(tabGeneral, "Name:", config.Name, ref y);

        AddLabel(tabGeneral, "COM Port:", ref y);
        _cboComPort = new ComboBox { Left = 140, Top = y - 22, Width = 280, DropDownStyle = ComboBoxStyle.DropDown };
        _cboComPort.Items.AddRange(SerialPort.GetPortNames().Cast<object>().ToArray());
        if (_cboComPort.Items.Count == 0)
        {
            for (int i = 1; i <= 20; i++) _cboComPort.Items.Add($"COM{i}");
        }
        _cboComPort.Text = config.ComPort;
        tabGeneral.Controls.Add(_cboComPort);

        AddLabel(tabGeneral, "Connection Mode:", ref y);
        _cboMode = new ComboBox { Left = 140, Top = y - 22, Width = 280, DropDownStyle = ComboBoxStyle.DropDownList };
        _cboMode.Items.AddRange(new object[] { "TCP Server", "TCP Client", "UDP" });
        _cboMode.SelectedIndex = (int)config.Mode;
        _cboMode.SelectedIndexChanged += CboMode_Changed;
        tabGeneral.Controls.Add(_cboMode);

        _txtIp = AddTextBox(tabGeneral, "IP Address:", config.RemoteIp, ref y);

        AddLabel(tabGeneral, "TCP/UDP Port:", ref y);
        _nudPort = new NumericUpDown
        {
            Left = 140, Top = y - 22, Width = 280,
            Minimum = 1, Maximum = 65535, Value = config.TcpPort
        };
        tabGeneral.Controls.Add(_nudPort);

        // ── Serial Tab ──
        y = 15;
        AddLabel(tabSerial, "Baud Rate:", ref y);
        _cboBaudRate = new ComboBox { Left = 140, Top = y - 22, Width = 280, DropDownStyle = ComboBoxStyle.DropDown };
        _cboBaudRate.Items.AddRange(new object[] { "300", "1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600" });
        _cboBaudRate.Text = config.BaudRate.ToString();
        tabSerial.Controls.Add(_cboBaudRate);

        AddLabel(tabSerial, "Data Bits:", ref y);
        _cboDataBits = new ComboBox { Left = 140, Top = y - 22, Width = 280, DropDownStyle = ComboBoxStyle.DropDownList };
        _cboDataBits.Items.AddRange(new object[] { "5", "6", "7", "8" });
        _cboDataBits.Text = config.DataBits.ToString();
        tabSerial.Controls.Add(_cboDataBits);

        AddLabel(tabSerial, "Stop Bits:", ref y);
        _cboStopBits = new ComboBox { Left = 140, Top = y - 22, Width = 280, DropDownStyle = ComboBoxStyle.DropDownList };
        _cboStopBits.Items.AddRange(new object[] { "1", "1.5", "2" });
        _cboStopBits.Text = config.StopBits.ToString("0.##");
        tabSerial.Controls.Add(_cboStopBits);

        AddLabel(tabSerial, "Parity:", ref y);
        _cboParity = new ComboBox { Left = 140, Top = y - 22, Width = 280, DropDownStyle = ComboBoxStyle.DropDownList };
        _cboParity.Items.AddRange(new object[] { "None", "Odd", "Even", "Mark", "Space" });
        _cboParity.Text = config.Parity;
        tabSerial.Controls.Add(_cboParity);

        AddLabel(tabSerial, "Flow Control:", ref y);
        _cboFlowControl = new ComboBox { Left = 140, Top = y - 22, Width = 280, DropDownStyle = ComboBoxStyle.DropDownList };
        _cboFlowControl.Items.AddRange(new object[] { "None", "RTS/CTS", "DTR/DSR", "XON/XOFF" });
        _cboFlowControl.SelectedIndex = (int)config.FlowControl;
        tabSerial.Controls.Add(_cboFlowControl);

        // ── Advanced Tab ──
        y = 15;
        _chkAutoReconnect = AddCheckBox(tabAdvanced, "Auto Reconnect", config.AutoReconnect, ref y);

        AddLabel(tabAdvanced, "Reconnect Interval (ms):", ref y);
        _nudReconnectInterval = new NumericUpDown
        {
            Left = 180, Top = y - 22, Width = 240,
            Minimum = 500, Maximum = 60000, Value = config.ReconnectIntervalMs, Increment = 500
        };
        tabAdvanced.Controls.Add(_nudReconnectInterval);

        _chkConnectOnData = AddCheckBox(tabAdvanced, "Connect on Data (lazy connect)", config.ConnectOnData, ref y);

        AddLabel(tabAdvanced, "Inactivity Timeout (ms):", ref y);
        _nudInactivityTimeout = new NumericUpDown
        {
            Left = 180, Top = y - 22, Width = 240,
            Minimum = 0, Maximum = 600000, Value = config.InactivityTimeoutMs, Increment = 1000
        };
        tabAdvanced.Controls.Add(_nudInactivityTimeout);
        AddLabel(tabAdvanced, "(0 = disabled)", ref y);
        y -= 10;

        _chkEnableRfc2217 = AddCheckBox(tabAdvanced, "Enable RFC 2217 (Telnet COM Control)", config.EnableRfc2217, ref y);
        _chkEnableLogging = AddCheckBox(tabAdvanced, "Enable Data Logging", config.EnableLogging, ref y);

        tabs.TabPages.AddRange(new[] { tabGeneral, tabSerial, tabAdvanced });

        // Buttons panel
        var buttonPanel = new Panel { Dock = DockStyle.Bottom, Height = 50 };
        var btnOk = new Button { Text = "OK", DialogResult = DialogResult.OK, Width = 90, Height = 32, Left = 260, Top = 8 };
        var btnCancel = new Button { Text = "Cancel", DialogResult = DialogResult.Cancel, Width = 90, Height = 32, Left = 360, Top = 8 };
        btnOk.Click += BtnOk_Click;
        buttonPanel.Controls.AddRange(new Control[] { btnOk, btnCancel });

        Controls.Add(tabs);
        Controls.Add(buttonPanel);
        AcceptButton = btnOk;
        CancelButton = btnCancel;

        CboMode_Changed(this, EventArgs.Empty);
    }

    private void CboMode_Changed(object? sender, EventArgs e)
    {
        // IP label context changes based on mode
        bool isServer = _cboMode.SelectedIndex == 0;
        // For server: bind address; for client: remote address
    }

    private void BtnOk_Click(object? sender, EventArgs e)
    {
        if (string.IsNullOrWhiteSpace(_txtName.Text))
        {
            MessageBox.Show(this, "Name is required.", "Validation", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            DialogResult = DialogResult.None;
            return;
        }

        if (!int.TryParse(_cboBaudRate.Text, out int baudRate) || baudRate <= 0)
        {
            MessageBox.Show(this, "Invalid baud rate.", "Validation", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            DialogResult = DialogResult.None;
            return;
        }

        _config.Enabled = _chkEnabled.Checked;
        _config.Name = _txtName.Text.Trim();
        _config.ComPort = _cboComPort.Text;
        _config.Mode = (ConnectionMode)_cboMode.SelectedIndex;
        _config.RemoteIp = _txtIp.Text.Trim();
        _config.TcpPort = (int)_nudPort.Value;
        _config.BaudRate = baudRate;
        _config.DataBits = int.Parse(_cboDataBits.Text);
        _config.StopBits = float.Parse(_cboStopBits.Text);
        _config.Parity = _cboParity.Text;
        _config.FlowControl = (FlowControlType)_cboFlowControl.SelectedIndex;
        _config.AutoReconnect = _chkAutoReconnect.Checked;
        _config.ReconnectIntervalMs = (int)_nudReconnectInterval.Value;
        _config.ConnectOnData = _chkConnectOnData.Checked;
        _config.InactivityTimeoutMs = (int)_nudInactivityTimeout.Value;
        _config.EnableRfc2217 = _chkEnableRfc2217.Checked;
        _config.EnableLogging = _chkEnableLogging.Checked;
    }

    #region Layout Helpers

    private static void AddLabel(Control parent, string text, ref int y)
    {
        var lbl = new Label { Text = text, Left = 15, Top = y, Width = 120, AutoSize = true };
        parent.Controls.Add(lbl);
        y += 28;
    }

    private static TextBox AddTextBox(Control parent, string label, string value, ref int y)
    {
        AddLabel(parent, label, ref y);
        var txt = new TextBox { Left = 140, Top = y - 28, Width = 280, Text = value };
        parent.Controls.Add(txt);
        return txt;
    }

    private static CheckBox AddCheckBox(Control parent, string text, bool value, ref int y)
    {
        var chk = new CheckBox { Text = text, Left = 15, Top = y, Width = 400, Checked = value, AutoSize = true };
        parent.Controls.Add(chk);
        y += 28;
        return chk;
    }

    #endregion
}
