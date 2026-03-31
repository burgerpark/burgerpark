using ComIpBridge.Core;
using ComIpBridge.Models;

namespace ComIpBridge.UI;

public class VirtualPortDialog : Form
{
    private readonly Com0ComManager _com0com;
    private readonly ListView _pairListView;
    private readonly Label _statusLabel;
    private readonly ComboBox _cboPortA;
    private readonly ComboBox _cboPortB;
    private readonly ComboBox _cboBridgeMode;
    private readonly TextBox _txtBridgeIp;
    private readonly NumericUpDown _nudBridgePort;
    private readonly CheckBox _chkAutoCreateBridge;

    public BridgeConfig? CreatedBridgeConfig { get; private set; }

    public VirtualPortDialog(Com0ComManager com0com)
    {
        _com0com = com0com;

        Text = "가상 COM 포트 관리";
        Size = new Size(600, 520);
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        StartPosition = FormStartPosition.CenterParent;
        Font = new Font("Segoe UI", 9F);

        // Status panel
        var statusPanel = new Panel { Dock = DockStyle.Top, Height = 50, Padding = new Padding(10) };
        _statusLabel = new Label
        {
            Dock = DockStyle.Fill,
            Font = new Font("Segoe UI", 9.5F),
            AutoSize = false,
            TextAlign = ContentAlignment.MiddleLeft
        };
        statusPanel.Controls.Add(_statusLabel);

        // Existing pairs list
        var listGroup = new GroupBox
        {
            Text = "현재 가상 포트 페어",
            Dock = DockStyle.Top,
            Height = 150,
            Padding = new Padding(10)
        };

        _pairListView = new ListView
        {
            Dock = DockStyle.Fill,
            View = View.Details,
            FullRowSelect = true,
            GridLines = true
        };
        _pairListView.Columns.AddRange(new[]
        {
            new ColumnHeader { Text = "번호", Width = 50 },
            new ColumnHeader { Text = "포트 A (앱용)", Width = 120 },
            new ColumnHeader { Text = "포트 B (브릿지용)", Width = 120 },
            new ColumnHeader { Text = "상태", Width = 200 }
        });
        listGroup.Controls.Add(_pairListView);

        // Create new pair section
        var createGroup = new GroupBox
        {
            Text = "새 가상 포트 생성",
            Dock = DockStyle.Top,
            Height = 200,
            Padding = new Padding(10, 5, 10, 5)
        };

        int y = 25;

        var lblPortA = new Label { Text = "앱 포트 (A):", Left = 15, Top = y, AutoSize = true };
        _cboPortA = new ComboBox { Left = 130, Top = y - 2, Width = 120, DropDownStyle = ComboBoxStyle.DropDown };
        var lblArrow = new Label { Text = "↔", Left = 260, Top = y, AutoSize = true, Font = new Font("Segoe UI", 11F, FontStyle.Bold) };
        var lblPortB = new Label { Text = "브릿지 포트 (B):", Left = 285, Top = y, AutoSize = true };
        _cboPortB = new ComboBox { Left = 410, Top = y - 2, Width = 120, DropDownStyle = ComboBoxStyle.DropDown };
        y += 35;

        _chkAutoCreateBridge = new CheckBox
        {
            Text = "생성 후 자동으로 브릿지 설정 추가",
            Left = 15, Top = y, AutoSize = true, Checked = true
        };
        _chkAutoCreateBridge.CheckedChanged += (_, _) => ToggleBridgeOptions();
        y += 30;

        var lblMode = new Label { Text = "브릿지 모드:", Left = 35, Top = y, AutoSize = true };
        _cboBridgeMode = new ComboBox { Left = 130, Top = y - 2, Width = 150, DropDownStyle = ComboBoxStyle.DropDownList };
        _cboBridgeMode.Items.AddRange(new object[] { "TCP 서버", "TCP 클라이언트", "UDP" });
        _cboBridgeMode.SelectedIndex = 0;
        y += 30;

        var lblIp = new Label { Text = "IP 주소:", Left = 35, Top = y, AutoSize = true };
        _txtBridgeIp = new TextBox { Left = 130, Top = y - 2, Width = 150, Text = "0.0.0.0" };

        var lblBridgePort = new Label { Text = "포트:", Left = 300, Top = y, AutoSize = true };
        _nudBridgePort = new NumericUpDown
        {
            Left = 340, Top = y - 2, Width = 100,
            Minimum = 1, Maximum = 65535, Value = 5000
        };
        y += 35;

        var btnCreate = new Button
        {
            Text = "가상 포트 생성",
            Left = 130, Top = y, Width = 150, Height = 32
        };
        btnCreate.Click += BtnCreate_Click;

        var btnDelete = new Button
        {
            Text = "선택한 페어 삭제",
            Left = 300, Top = y, Width = 150, Height = 32
        };
        btnDelete.Click += BtnDelete_Click;

        createGroup.Controls.AddRange(new Control[]
        {
            lblPortA, _cboPortA, lblArrow, lblPortB, _cboPortB,
            _chkAutoCreateBridge,
            lblMode, _cboBridgeMode,
            lblIp, _txtBridgeIp, lblBridgePort, _nudBridgePort,
            btnCreate, btnDelete
        });

        // Button panel
        var buttonPanel = new Panel { Dock = DockStyle.Bottom, Height = 50 };
        var btnClose = new Button
        {
            Text = "닫기", DialogResult = DialogResult.OK,
            Width = 90, Height = 32, Left = 490, Top = 8
        };

        var btnInstallHelp = new Button
        {
            Text = "com0com 설치 안내",
            Width = 140, Height = 32, Left = 15, Top = 8
        };
        btnInstallHelp.Click += (_, _) =>
        {
            MessageBox.Show(this, Com0ComManager.GetInstallInstructions(),
                "com0com 설치 안내", MessageBoxButtons.OK, MessageBoxIcon.Information);
        };

        buttonPanel.Controls.AddRange(new Control[] { btnClose, btnInstallHelp });

        Controls.Add(buttonPanel);
        Controls.Add(createGroup);
        Controls.Add(listGroup);
        Controls.Add(statusPanel);

        AcceptButton = btnClose;

        RefreshStatus();
        RefreshPairList();
        RefreshAvailablePorts();
    }

    private void RefreshStatus()
    {
        if (_com0com.IsInstalled)
        {
            _statusLabel.Text = "com0com 상태: 설치됨";
            _statusLabel.ForeColor = Color.DarkGreen;
        }
        else
        {
            _statusLabel.Text = "com0com 상태: 미설치 - 가상 포트 기능을 사용하려면 com0com을 먼저 설치하세요.";
            _statusLabel.ForeColor = Color.Red;
        }
    }

    private void RefreshPairList()
    {
        _pairListView.Items.Clear();
        if (!_com0com.IsInstalled) return;

        try
        {
            var pairs = _com0com.ListPairs();
            foreach (var pair in pairs)
            {
                var item = new ListViewItem(new[]
                {
                    pair.PairIndex.ToString(),
                    pair.PortA,
                    pair.PortB,
                    "활성"
                })
                {
                    Tag = pair,
                    ForeColor = Color.DarkGreen
                };
                _pairListView.Items.Add(item);
            }
        }
        catch (Exception ex)
        {
            _statusLabel.Text = $"포트 목록 조회 실패: {ex.Message}";
            _statusLabel.ForeColor = Color.Red;
        }
    }

    private void RefreshAvailablePorts()
    {
        _cboPortA.Items.Clear();
        _cboPortB.Items.Clear();

        if (!_com0com.IsInstalled)
        {
            for (int i = 10; i <= 30; i++)
            {
                _cboPortA.Items.Add($"COM{i}");
                _cboPortB.Items.Add($"COM{i}");
            }
        }
        else
        {
            var available = _com0com.GetAvailablePortNames(20, 10);
            foreach (var port in available)
            {
                _cboPortA.Items.Add(port);
                _cboPortB.Items.Add(port);
            }
        }

        if (_cboPortA.Items.Count >= 2)
        {
            _cboPortA.SelectedIndex = 0;
            _cboPortB.SelectedIndex = 1;
        }
    }

    private void ToggleBridgeOptions()
    {
        bool enabled = _chkAutoCreateBridge.Checked;
        _cboBridgeMode.Enabled = enabled;
        _txtBridgeIp.Enabled = enabled;
        _nudBridgePort.Enabled = enabled;
    }

    private void BtnCreate_Click(object? sender, EventArgs e)
    {
        if (!_com0com.IsInstalled)
        {
            MessageBox.Show(this, Com0ComManager.GetInstallInstructions(),
                "com0com 미설치", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }

        var portA = _cboPortA.Text.Trim().ToUpper();
        var portB = _cboPortB.Text.Trim().ToUpper();

        if (string.IsNullOrEmpty(portA) || string.IsNullOrEmpty(portB))
        {
            MessageBox.Show(this, "두 포트 이름을 모두 입력해주세요.", "입력 오류", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }

        if (portA == portB)
        {
            MessageBox.Show(this, "두 포트 이름이 같을 수 없습니다.", "입력 오류", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }

        try
        {
            Cursor = Cursors.WaitCursor;
            var pair = _com0com.CreatePair(portA, portB);

            if (pair != null)
            {
                MessageBox.Show(this,
                    $"가상 포트 페어가 생성되었습니다!\n\n" +
                    $"  앱용 포트:     {pair.PortA}\n" +
                    $"  브릿지용 포트: {pair.PortB}\n\n" +
                    $"앱에서는 {pair.PortA}을 사용하세요.",
                    "생성 완료", MessageBoxButtons.OK, MessageBoxIcon.Information);

                // Auto-create bridge config
                if (_chkAutoCreateBridge.Checked)
                {
                    CreatedBridgeConfig = new BridgeConfig
                    {
                        Name = $"가상포트 {pair.PortB}",
                        ComPort = pair.PortB,
                        Mode = (ConnectionMode)_cboBridgeMode.SelectedIndex,
                        RemoteIp = _txtBridgeIp.Text.Trim(),
                        TcpPort = (int)_nudBridgePort.Value,
                        Enabled = true,
                        AutoReconnect = true
                    };
                }

                RefreshPairList();
                RefreshAvailablePorts();
            }
            else
            {
                MessageBox.Show(this, "포트 생성에 실패했습니다. 관리자 권한으로 실행해보세요.",
                    "오류", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "오류", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        finally
        {
            Cursor = Cursors.Default;
        }
    }

    private void BtnDelete_Click(object? sender, EventArgs e)
    {
        if (_pairListView.SelectedItems.Count == 0)
        {
            MessageBox.Show(this, "삭제할 페어를 선택해주세요.", "알림", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }

        var pair = _pairListView.SelectedItems[0].Tag as VirtualPortPair;
        if (pair == null) return;

        var result = MessageBox.Show(this,
            $"가상 포트 페어를 삭제하시겠습니까?\n\n  {pair.PortA} ↔ {pair.PortB}",
            "삭제 확인", MessageBoxButtons.YesNo, MessageBoxIcon.Question);
        if (result != DialogResult.Yes) return;

        try
        {
            if (_com0com.RemovePair(pair.PairIndex))
            {
                MessageBox.Show(this, "삭제 완료!", "완료", MessageBoxButtons.OK, MessageBoxIcon.Information);
                RefreshPairList();
                RefreshAvailablePorts();
            }
            else
            {
                MessageBox.Show(this, "삭제에 실패했습니다.", "오류", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "오류", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
