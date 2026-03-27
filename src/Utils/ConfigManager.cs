using Newtonsoft.Json;
using ComIpBridge.Models;

namespace ComIpBridge.Utils;

public static class ConfigManager
{
    private static readonly string ConfigDir = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
        "ComIpBridge");

    private static readonly string ConfigFile = Path.Combine(ConfigDir, "bridges.json");

    public static List<BridgeConfig> Load()
    {
        try
        {
            if (!File.Exists(ConfigFile))
                return new List<BridgeConfig>();

            var json = File.ReadAllText(ConfigFile);
            return JsonConvert.DeserializeObject<List<BridgeConfig>>(json) ?? new List<BridgeConfig>();
        }
        catch
        {
            return new List<BridgeConfig>();
        }
    }

    public static void Save(List<BridgeConfig> configs)
    {
        Directory.CreateDirectory(ConfigDir);
        var json = JsonConvert.SerializeObject(configs, Formatting.Indented);
        File.WriteAllText(ConfigFile, json);
    }

    public static void ExportToFile(List<BridgeConfig> configs, string filePath)
    {
        var json = JsonConvert.SerializeObject(configs, Formatting.Indented);
        File.WriteAllText(filePath, json);
    }

    public static List<BridgeConfig> ImportFromFile(string filePath)
    {
        var json = File.ReadAllText(filePath);
        return JsonConvert.DeserializeObject<List<BridgeConfig>>(json) ?? new List<BridgeConfig>();
    }
}
