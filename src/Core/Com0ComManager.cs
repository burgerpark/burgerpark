using System.Diagnostics;
using System.Text.RegularExpressions;
using Microsoft.Win32;

namespace ComIpBridge.Core;

public class VirtualPortPair
{
    public string PortA { get; set; } = "";
    public string PortB { get; set; } = "";
    public int PairIndex { get; set; }

    public override string ToString() => $"{PortA} ↔ {PortB}";
}

public class Com0ComManager
{
    private string? _setupcPath;

    public bool IsInstalled => FindSetupc() != null;

    /// <summary>
    /// Find com0com setupc.exe path
    /// </summary>
    public string? FindSetupc()
    {
        if (_setupcPath != null && File.Exists(_setupcPath))
            return _setupcPath;

        // Check common install paths
        string[] searchPaths = new[]
        {
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "com0com", "setupc.exe"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), "com0com", "setupc.exe"),
            @"C:\Program Files\com0com\setupc.exe",
            @"C:\Program Files (x86)\com0com\setupc.exe",
        };

        foreach (var path in searchPaths)
        {
            if (File.Exists(path))
            {
                _setupcPath = path;
                return path;
            }
        }

        // Check registry
        try
        {
            string[] regKeys = new[]
            {
                @"SOFTWARE\com0com",
                @"SOFTWARE\WOW6432Node\com0com"
            };

            foreach (var regKey in regKeys)
            {
                using var key = Registry.LocalMachine.OpenSubKey(regKey);
                var installDir = key?.GetValue("Install_Dir") as string;
                if (installDir != null)
                {
                    var path = Path.Combine(installDir, "setupc.exe");
                    if (File.Exists(path))
                    {
                        _setupcPath = path;
                        return path;
                    }
                }
            }
        }
        catch { }

        // Check PATH
        try
        {
            var result = RunCommand("where", "setupc.exe");
            if (result.ExitCode == 0 && !string.IsNullOrWhiteSpace(result.Output))
            {
                var path = result.Output.Trim().Split('\n')[0].Trim();
                if (File.Exists(path))
                {
                    _setupcPath = path;
                    return path;
                }
            }
        }
        catch { }

        return null;
    }

    /// <summary>
    /// List existing virtual port pairs
    /// </summary>
    public List<VirtualPortPair> ListPairs()
    {
        var pairs = new List<VirtualPortPair>();
        var setupc = FindSetupc();
        if (setupc == null) return pairs;

        var result = RunCommand(setupc, "list");
        if (result.ExitCode != 0) return pairs;

        // Parse output like:
        // CNCA0 PortName=COM5,RealPortName=COM5
        // CNCB0 PortName=COM6,RealPortName=COM6
        var lines = result.Output.Split('\n', StringSplitOptions.RemoveEmptyEntries);
        var portMap = new Dictionary<int, (string? a, string? b)>();

        foreach (var line in lines)
        {
            var match = Regex.Match(line.Trim(), @"CNC([AB])(\d+)\s+PortName=(\w+)");
            if (!match.Success) continue;

            var side = match.Groups[1].Value;
            var index = int.Parse(match.Groups[2].Value);
            var portName = match.Groups[3].Value;

            if (!portMap.ContainsKey(index))
                portMap[index] = (null, null);

            var current = portMap[index];
            if (side == "A")
                portMap[index] = (portName, current.b);
            else
                portMap[index] = (current.a, portName);
        }

        foreach (var (index, (a, b)) in portMap)
        {
            if (a != null && b != null)
            {
                pairs.Add(new VirtualPortPair
                {
                    PairIndex = index,
                    PortA = a,
                    PortB = b
                });
            }
        }

        return pairs;
    }

    /// <summary>
    /// Create a new virtual port pair (e.g., COM10 ↔ COM11)
    /// </summary>
    public VirtualPortPair? CreatePair(string portNameA, string portNameB)
    {
        var setupc = FindSetupc();
        if (setupc == null)
            throw new InvalidOperationException("com0com이 설치되어 있지 않습니다. 먼저 com0com을 설치해주세요.");

        // Install pair with specific port names
        var result = RunCommand(setupc, $"install PortName={portNameA} PortName={portNameB}");
        if (result.ExitCode != 0)
            throw new Exception($"가상 포트 생성 실패: {result.Output} {result.Error}");

        // Verify creation
        var pairs = ListPairs();
        return pairs.FirstOrDefault(p =>
            (p.PortA == portNameA && p.PortB == portNameB) ||
            (p.PortA == portNameB && p.PortB == portNameA));
    }

    /// <summary>
    /// Remove a virtual port pair by index
    /// </summary>
    public bool RemovePair(int pairIndex)
    {
        var setupc = FindSetupc();
        if (setupc == null) return false;

        var result = RunCommand(setupc, $"remove {pairIndex}");
        return result.ExitCode == 0;
    }

    /// <summary>
    /// Remove all virtual port pairs
    /// </summary>
    public void RemoveAll()
    {
        var setupc = FindSetupc();
        if (setupc == null) return;

        RunCommand(setupc, "uninstall --all");
    }

    /// <summary>
    /// Get list of available (unused) COM port numbers
    /// </summary>
    public List<string> GetAvailablePortNames(int count = 2, int startFrom = 10)
    {
        var usedPorts = new HashSet<string>(
            System.IO.Ports.SerialPort.GetPortNames(),
            StringComparer.OrdinalIgnoreCase);

        // Also check virtual pairs
        foreach (var pair in ListPairs())
        {
            usedPorts.Add(pair.PortA);
            usedPorts.Add(pair.PortB);
        }

        var available = new List<string>();
        for (int i = startFrom; available.Count < count && i <= 255; i++)
        {
            var name = $"COM{i}";
            if (!usedPorts.Contains(name))
                available.Add(name);
        }

        return available;
    }

    /// <summary>
    /// Get com0com download URL
    /// </summary>
    public static string GetDownloadUrl()
    {
        return "https://sourceforge.net/projects/com0com/files/latest/download";
    }

    /// <summary>
    /// Get installation instructions
    /// </summary>
    public static string GetInstallInstructions()
    {
        return "com0com 설치 방법:\n\n" +
               "1. 아래 링크에서 com0com을 다운로드하세요:\n" +
               "   https://sourceforge.net/projects/com0com/\n\n" +
               "2. 다운로드한 설치 파일을 실행하세요.\n" +
               "   (Windows 보안 경고가 뜨면 '추가 정보' → '실행')\n\n" +
               "3. 설치 완료 후 이 프로그램을 재시작하세요.\n\n" +
               "참고: Windows 10/11에서는 '테스트 모드' 또는\n" +
               "'드라이버 서명 강제 사용 안 함' 설정이 필요할 수 있습니다.";
    }

    private static (int ExitCode, string Output, string Error) RunCommand(string fileName, string arguments)
    {
        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = fileName,
                Arguments = arguments,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true,
                Verb = "runas"
            };

            using var process = Process.Start(psi);
            if (process == null)
                return (-1, "", "프로세스를 시작할 수 없습니다.");

            var output = process.StandardOutput.ReadToEnd();
            var error = process.StandardError.ReadToEnd();
            process.WaitForExit(10000);

            return (process.ExitCode, output, error);
        }
        catch (Exception ex)
        {
            return (-1, "", ex.Message);
        }
    }
}
