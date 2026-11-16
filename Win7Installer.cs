using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using System.Xml;

internal sealed class OriginalFile
{
    public string name { get; set; }
    public bool existed { get; set; }
}

internal sealed class ModState
{
    public string gameDirectory { get; set; }
    public string variant { get; set; }
    public bool active { get; set; }
    public string backupDirectory { get; set; }
    public List<OriginalFile> originals { get; set; }
    public string time { get; set; }
}

internal sealed class Installer
{
    private readonly string package = AppDomain.CurrentDomain.BaseDirectory;
    private readonly XmlElement patch;
    private readonly string variant, gameTitle, engine, suffix;
    private readonly string[] dataFiles, processNames;
    private readonly JavaScriptSerializer json = new JavaScriptSerializer();

    private Installer()
    {
        XmlDocument manifest = new XmlDocument();
        manifest.XmlResolver = null;
        manifest.Load(Path.Combine(package, "EnginePatch.xml"));
        patch = manifest.DocumentElement;
        variant = patch.GetAttribute("variant");
        if (variant != "YR" && variant != "RA2") throw new InvalidDataException("无法识别离线包对应的游戏版本。");
        bool yr = variant == "YR";
        suffix = yr ? "md" : "";
        engine = yr ? "gamemd.exe" : "game.exe";
        gameTitle = yr ? "尤里的复仇" : "原版红警2";
        processNames = yr ? new[] { "gamemd", "ra2md", "yuri" } : new[] { "game", "ra2" };
        dataFiles = new[] { "rules" + suffix + ".ini", "ai" + suffix + ".ini", "art" + suffix + ".ini",
            "ra2" + suffix + ".csf", "sgsticon.shp", "gastrt.shp", "ggstrt.shp" };
    }

    [STAThread]
    private static int Main(string[] args)
    {
        bool interactive = args.Length == 0;
        try
        {
            Installer setup = new Installer();
            string game;
            bool enable;
            if (interactive)
            {
                Application.EnableVisualStyles();
                using (FolderBrowserDialog picker = new FolderBrowserDialog())
                {
                    picker.Description = "选择" + setup.gameTitle + "的游戏目录（包含 " + setup.engine + "）";
                    picker.ShowNewFolderButton = false;
                    if (picker.ShowDialog() != DialogResult.OK) return 0;
                    game = picker.SelectedPath;
                }
                DialogResult action = MessageBox.Show("是：安装或更新 MOD\n否：停用并还原原文件\n取消：退出",
                    "开始进攻 MOD", MessageBoxButtons.YesNoCancel, MessageBoxIcon.Question);
                if (action == DialogResult.Cancel) return 0;
                enable = action == DialogResult.Yes;
            }
            else
            {
                if (args.Length != 2 || (args[0] != "--install" && args[0] != "--restore"))
                    throw new ArgumentException("StartAttack-Win7.exe --install|--restore <游戏目录>");
                enable = args[0] == "--install";
                game = args[1];
            }
            string result = setup.Apply(game, enable);
            if (interactive) MessageBox.Show(result, "开始进攻 MOD");
            return 0;
        }
        catch (Exception error)
        {
            if (interactive) MessageBox.Show(error.Message, "开始进攻 MOD", MessageBoxButtons.OK, MessageBoxIcon.Error);
            else Console.Error.WriteLine(error.Message);
            return 1;
        }
    }

    private string Apply(string directory, bool enable)
    {
        string game = Path.GetFullPath(directory).TrimEnd(Path.DirectorySeparatorChar);
        string gameEngine = Path.Combine(game, engine);
        if (!File.Exists(gameEngine)) throw new FileNotFoundException("所选目录缺少 " + engine + "。");
        foreach (string name in processNames)
        {
            Process[] running = Process.GetProcessesByName(name);
            foreach (Process process in running) process.Dispose();
            if (running.Length > 0) throw new InvalidOperationException("游戏正在运行，未改动游戏文件。");
        }
        string managed = Path.Combine(game, "StartAttackMOD");
        string statePath = Path.Combine(managed, "state-" + variant + ".json");
        ModState state = File.Exists(statePath) ? json.Deserialize<ModState>(File.ReadAllText(statePath)) : null;
        if (state != null && !String.Equals(state.gameDirectory, game, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("旧 MOD 备份关联了其他目录。");

        if (!enable)
        {
            if (state == null || !state.active) return "MOD 当前已停用。";
            Restore(game, managed, statePath, state);
            return "MOD 已停用，原文件已还原。";
        }

        string original = gameEngine;
        if (state != null && state.active)
            foreach (OriginalFile entry in state.originals)
                if (String.Equals(entry.name, engine, StringComparison.OrdinalIgnoreCase))
                    original = Path.Combine(state.backupDirectory, engine);
        byte[] modified = PatchEngine(File.ReadAllBytes(original));
        Dictionary<string, byte[]> payload = LoadPayload(game, state);

        if (state != null && state.active) Restore(game, managed, statePath, state);
        string staged = Path.Combine(Path.Combine(managed, "安装文件"), gameTitle);
        Directory.CreateDirectory(staged);
        foreach (string name in dataFiles)
            File.WriteAllBytes(Path.Combine(staged, name), payload[name]);
        File.WriteAllBytes(Path.Combine(staged, engine), modified);
        string manager = Path.Combine(managed, "管理MOD.ps1");
        if (!File.Exists(manager))
            using (Stream resource = Assembly.GetExecutingAssembly().GetManifestResourceStream("ManageMod"))
            using (FileStream file = File.Create(manager))
            {
                byte[] buffer = new byte[8192];
                int count;
                while ((count = resource.Read(buffer, 0, buffer.Length)) > 0) file.Write(buffer, 0, count);
            }

        ModState next = new ModState { gameDirectory = game, variant = variant,
            time = Stamp(), originals = new List<OriginalFile>() };
        next.backupDirectory = Archive(managed, "原文件备份", next.time);
        List<string> files = new List<string>(dataFiles);
        files.Add(engine);
        foreach (string name in files)
        {
            string path = Path.Combine(game, name);
            bool exists = File.Exists(path);
            if (exists) File.Copy(path, Path.Combine(next.backupDirectory, name));
            next.originals.Add(new OriginalFile { name = name, existed = exists });
        }
        SaveState(statePath, next);
        List<OriginalFile> written = new List<OriginalFile>();
        try
        {
            foreach (OriginalFile entry in next.originals)
            {
                written.Add(entry);
                File.Copy(Path.Combine(staged, entry.name), Path.Combine(game, entry.name), true);
            }
            next.active = true;
            SaveState(statePath, next);
        }
        catch
        {
            string failed = Archive(managed, "安装失败保存", Stamp());
            foreach (OriginalFile entry in written)
            {
                string path = Path.Combine(game, entry.name);
                if (File.Exists(path)) File.Move(path, Path.Combine(failed, entry.name));
                if (entry.existed) File.Copy(Path.Combine(next.backupDirectory, entry.name), path);
            }
            throw;
        }
        try { RepairCredits(game, managed); }
        catch (IOException) { return "MOD 已启用。上次的遭遇战资金未能重置，可在大厅手动调整。"; }
        catch (UnauthorizedAccessException) { return "MOD 已启用。上次的遭遇战资金未能重置，可在大厅手动调整。"; }
        return gameTitle + " MOD 已启用，原文件已备份。";
    }

    private byte[] PatchEngine(byte[] data)
    {
        XmlNodeList changes = patch.SelectNodes("Change");
        if (data.Length != Int32.Parse(patch.GetAttribute("length"), CultureInfo.InvariantCulture) || changes.Count == 0)
            throw new InvalidDataException("本机游戏程序与离线包不匹配，或离线包不完整。");
        CheckBytes(data, 0, Convert.FromBase64String(patch["Header"].InnerText));
        foreach (XmlElement change in changes)
        {
            int offset = Int32.Parse(change.GetAttribute("offset"), CultureInfo.InvariantCulture);
            byte[] before = Convert.FromBase64String(change.GetAttribute("before"));
            byte[] after = Convert.FromBase64String(change.GetAttribute("after"));
            if (before.Length != after.Length) throw new InvalidDataException("程序补丁长度无效。");
            CheckBytes(data, offset, before);
            Buffer.BlockCopy(after, 0, data, offset, after.Length);
        }
        return data;
    }

    private Dictionary<string, byte[]> LoadPayload(string game, ModState state)
    {
        string folder = Path.Combine(package, "Payload");
        string recipe = Path.Combine(package, "Resources.xml");
        Dictionary<string, byte[]> result = new Dictionary<string, byte[]>();
        if (File.Exists(recipe))
        {
            XmlDocument document = new XmlDocument();
            document.XmlResolver = null;
            document.Load(recipe);
            result.Add("sgsticon.shp", File.ReadAllBytes(Path.Combine(folder, "sgsticon.shp")));
            foreach (XmlElement entry in document.DocumentElement.SelectNodes("Resource"))
            {
                string name = entry.GetAttribute("name");
                try { result.Add(name, ReadResource(game, state, entry)); }
                catch (IOException error)
                {
                    throw new IOException("无法应用 " + name + "：请使用发布说明指定的原版游戏资源。", error);
                }
                catch (InvalidDataException error)
                {
                    throw new InvalidDataException("游戏资源与发布包不匹配：" + name + "。", error);
                }
            }
        }
        else
            foreach (string name in dataFiles)
                result.Add(name, File.ReadAllBytes(Path.Combine(folder, name)));
        foreach (string name in dataFiles)
            if (!result.ContainsKey(name)) throw new InvalidDataException("补丁包缺少 " + name + "。");
        return result;
    }

    private static int Number(XmlElement entry, string key)
    {
        return Int32.Parse(entry.GetAttribute(key), CultureInfo.InvariantCulture);
    }

    private static byte[] ReadResource(string game, ModState state, XmlElement entry)
    {
        string label = entry.GetAttribute("appendLabel");
        if (label.Length != 0)
        {
            string name = entry.GetAttribute("name");
            string loose = Path.Combine(game, name);
            if (state != null && state.active)
                foreach (OriginalFile item in state.originals)
                    if (String.Equals(item.name, name, StringComparison.OrdinalIgnoreCase))
                        loose = Path.Combine(state.backupDirectory, name);
            if (File.Exists(loose)) return AppendLabel(File.ReadAllBytes(loose), label, entry.GetAttribute("labelText"));
        }
        string archive = entry.GetAttribute("archive");
        byte[] original = new byte[Number(entry, "length")];
        using (FileStream file = File.OpenRead(Path.Combine(game, archive)))
        using (BinaryReader reader = new BinaryReader(file))
        {
            int offset = Number(entry, "offset");
            if (file.Length != Number(entry, "archiveLength") || offset < 0 || offset > file.Length - original.Length)
                throw new InvalidDataException("MIX 文件布局不匹配。");
            file.Position = offset;
            original = reader.ReadBytes(original.Length);
        }
        foreach (XmlElement guard in entry.SelectNodes("Guard"))
            CheckBytes(original, Number(guard, "offset"), Convert.FromBase64String(guard.InnerText));
        if (label.Length != 0) return AppendLabel(original, label, entry.GetAttribute("labelText"));
        if (!entry.HasChildNodes || entry.SelectNodes("Copy|Add").Count == 0) return original;
        using (MemoryStream output = new MemoryStream())
        {
            foreach (XmlElement part in entry.ChildNodes)
            {
                if (part.Name == "Copy") output.Write(original, Number(part, "offset"), Number(part, "length"));
                else if (part.Name == "Add")
                {
                    byte[] added = Convert.FromBase64String(part.InnerText);
                    output.Write(added, 0, added.Length);
                }
            }
            return output.ToArray();
        }
    }

    private static byte[] AppendLabel(byte[] data, string label, string text)
    {
        if (data.Length < 24 || BitConverter.ToInt32(data, 0) != 0x43534620 ||
            Encoding.ASCII.GetString(data).IndexOf(label, StringComparison.OrdinalIgnoreCase) >= 0)
            throw new InvalidDataException("语言文件无效或已包含 MOD 标签。");
        using (MemoryStream stream = new MemoryStream())
        using (BinaryWriter writer = new BinaryWriter(stream))
        {
            writer.Write(data, 0, 8);
            writer.Write(checked(BitConverter.ToInt32(data, 8) + 1));
            writer.Write(checked(BitConverter.ToInt32(data, 12) + 1));
            writer.Write(data, 16, data.Length - 16);
            writer.Write(Encoding.ASCII.GetBytes(" LBL"));
            writer.Write(1);
            byte[] name = Encoding.ASCII.GetBytes(label);
            writer.Write(name.Length);
            writer.Write(name);
            writer.Write(Encoding.ASCII.GetBytes(" RTS"));
            writer.Write(text.Length);
            foreach (byte value in Encoding.Unicode.GetBytes(text)) writer.Write((byte)~value);
            return stream.ToArray();
        }
    }

    private static void CheckBytes(byte[] data, int offset, byte[] expected)
    {
        if (offset < 0 || offset > data.Length - expected.Length)
            throw new InvalidDataException("程序补丁位置无效。");
        for (int i = 0; i < expected.Length; ++i)
            if (data[offset + i] != expected[i])
                throw new InvalidDataException("本机游戏程序与离线包不匹配。请用对应的原版游戏文件重新生成离线包。");
    }

    private void Restore(string game, string managed, string statePath, ModState state)
    {
        List<string> allowed = new List<string>(dataFiles);
        allowed.Add(engine);
        foreach (OriginalFile entry in state.originals)
        {
            if (!allowed.Contains(entry.name)) throw new InvalidDataException("状态文件中的文件名异常。");
            if (entry.existed && !File.Exists(Path.Combine(state.backupDirectory, entry.name)))
                throw new FileNotFoundException("原文件备份缺失：" + entry.name + "，未执行还原。");
        }
        string archive = Archive(managed, "停用时保存", Stamp());
        List<string> moved = new List<string>();
        List<string> restored = new List<string>();
        try
        {
            foreach (OriginalFile entry in state.originals)
            {
                string path = Path.Combine(game, entry.name);
                if (File.Exists(path))
                {
                    File.Move(path, Path.Combine(archive, entry.name));
                    moved.Add(entry.name);
                }
                if (entry.existed)
                {
                    restored.Add(entry.name);
                    File.Copy(Path.Combine(state.backupDirectory, entry.name), path);
                }
            }
            state.active = false;
            SaveState(statePath, state);
        }
        catch
        {
            string interrupted = Archive(managed, "还原失败保存", Stamp());
            foreach (string name in restored)
                if (File.Exists(Path.Combine(game, name)))
                    File.Move(Path.Combine(game, name), Path.Combine(interrupted, name));
            foreach (string name in moved)
                File.Move(Path.Combine(archive, name), Path.Combine(game, name));
            throw;
        }
    }

    private void SaveState(string path, ModState state)
    {
        File.WriteAllText(path, json.Serialize(state), new UTF8Encoding(false));
    }

    private static string Stamp()
    {
        return DateTime.UtcNow.AddHours(8).ToString("yyyyMMdd-HHmmss-fff", CultureInfo.InvariantCulture);
    }

    private string Archive(string managed, string kind, string stamp)
    {
        string folder = Path.Combine(Path.Combine(managed, kind), variant + "-" + stamp);
        Directory.CreateDirectory(folder);
        return folder;
    }

    private void RepairCredits(string game, string managed)
    {
        string ini = Path.Combine(game, "RA2" + suffix + ".INI");
        if (!File.Exists(ini)) return;
        Encoding encoding = Encoding.GetEncoding(28591);
        string text = File.ReadAllText(ini, encoding);
        Match section = Regex.Match(text, @"(?im)^\[Skirmish\][^\r\n]*\r?\n(?:(?!^\[)[\s\S])*");
        Match credits = Regex.Match(section.Value, @"(?im)^Credits=([+-]?\d+)[ \t]*(?=\r?$)");
        decimal amount;
        if (!credits.Success || !Decimal.TryParse(credits.Groups[1].Value, out amount) ||
            (amount >= 5000 && amount <= 500000)) return;
        string backup = Archive(managed, "更新时保存", Stamp());
        File.Copy(ini, Path.Combine(backup, Path.GetFileName(ini)));
        int start = section.Index + credits.Index;
        File.WriteAllText(ini, text.Remove(start, credits.Length).Insert(start, "Credits=10000"), encoding);
    }
}
