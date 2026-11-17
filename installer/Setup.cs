using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: AssemblyTitle("S.PDF 설치")]
[assembly: AssemblyVersion(BuildInfo.AssemblyVersion)]

internal static class SetupProgram
{
    internal const string RegistryPath = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\S.PDF";
    internal static readonly string InstallPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "S.PDF");
    internal const string Marker = ".spdf-install";
    internal static string Profile { get { return Environment.GetEnvironmentVariable("SPDF_DATA_DIR") ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "S.PDF"); } }

    [STAThread]
    private static int Main(string[] args)
    {
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        bool updating = args.Length > 0 && args[0] == "/update";
        try
        {
            if (args.Length == 2 && args[0] == "/extract") { Extract(Path.GetFullPath(args[1]), null, null); return 0; }
            if (updating)
            {
                if (!File.Exists(Path.Combine(InstallPath, Marker))) throw new IOException("설치된 S.PDF를 찾을 수 없습니다.");
                using (InstallLock.Acquire())
                {
                    int position = Array.IndexOf(args, "/wait"), processId;
                    if (position >= 0 && position + 1 < args.Length && Int32.TryParse(args[position + 1], out processId))
                    {
                        try { using (Process parent = Process.GetProcessById(processId)) if (!parent.WaitForExit(60000)) throw new IOException("작업 중인 S.PDF가 있어 업데이트를 미뤘습니다."); }
                        catch (ArgumentException) { }
                    }
                    DateTime deadline = DateTime.UtcNow.AddSeconds(60);
                    while (AppRunning(InstallPath)) { if (DateTime.UtcNow > deadline) throw new IOException("S.PDF를 닫은 뒤 다시 실행해주세요."); Thread.Sleep(200); }
                    bool desktop = true;
                    using (RegistryKey key = Registry.CurrentUser.OpenSubKey(RegistryPath)) if (key != null) desktop = Convert.ToInt32(key.GetValue("DesktopShortcut", 1)) != 0;
                    Install(desktop, null, null, null, InstallPath, true);
                    string pendingPath = Path.Combine(Profile, "updates", "pending.json");
                    object pendingVersion;
                    if (ReadSettings(pendingPath).TryGetValue("version", out pendingVersion) && Convert.ToString(pendingVersion) == BuildInfo.Version) File.Delete(pendingPath);
                }
                if (Array.IndexOf(args, "/restart") >= 0)
                {
                    List<string> files = new List<string>();
                    for (int index = 0; index + 1 < args.Length; index++) if (args[index] == "/open") files.Add(Quote(args[++index]));
                    Process.Start(new ProcessStartInfo(Path.Combine(InstallPath, "S.PDF.exe"), String.Join(" ", files.ToArray())) { UseShellExecute = false });
                }
                return 0;
            }
            Application.Run(new SetupForm()); return 0;
        }
        catch (Exception error)
        {
            if (updating) { Directory.CreateDirectory(Profile); File.WriteAllText(Path.Combine(Profile, "update-error.txt"), error.ToString(), Encoding.UTF8); }
            else MessageBox.Show(error.Message, "S.PDF 설치", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return 1;
        }
    }

    private static string Quote(string text)
    {
        StringBuilder result = new StringBuilder("\""); int slashes = 0;
        foreach (char c in text) { if (c == '\\') { slashes++; continue; } if (c == '"') { result.Append('\\', slashes * 2 + 1); result.Append(c); slashes = 0; continue; } result.Append('\\', slashes); slashes = 0; result.Append(c); }
        result.Append('\\', slashes * 2); return result.Append('"').ToString();
    }

    internal static bool AppRunning(string folder)
    {
        foreach (Process process in Process.GetProcessesByName("S.PDF")) using (process)
        {
            try { if (String.Equals(process.MainModule.FileName, Path.Combine(folder, "S.PDF.exe"), StringComparison.OrdinalIgnoreCase)) return true; }
            catch (System.ComponentModel.Win32Exception) { } catch (InvalidOperationException) { }
        }
        return false;
    }

    internal static void Extract(string destination, Action<int, string> progress, Func<bool> cancelled)
    {
        if (Directory.Exists(destination) && Directory.GetFileSystemEntries(destination).Length > 0) throw new IOException("압축을 풀 폴더가 비어 있지 않습니다.");
        Directory.CreateDirectory(destination);
        string prefix = Path.GetFullPath(destination).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        using (Stream stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip"))
        using (ZipArchive zip = new ZipArchive(stream, ZipArchiveMode.Read))
        {
            long total = Math.Max(1, zip.Entries.Sum(entry => entry.Length)), copied = 0;
            foreach (ZipArchiveEntry entry in zip.Entries)
            {
                if (cancelled != null && cancelled()) throw new OperationCanceledException();
                string target = Path.GetFullPath(Path.Combine(destination, entry.FullName.Replace('/', Path.DirectorySeparatorChar)));
                if (!target.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) throw new IOException("설치 파일 경로가 올바르지 않습니다.");
                if (String.IsNullOrEmpty(entry.Name)) { Directory.CreateDirectory(target); continue; }
                Directory.CreateDirectory(Path.GetDirectoryName(target));
                using (Stream source = entry.Open()) using (FileStream output = File.Create(target)) source.CopyTo(output);
                copied += entry.Length;
                if (progress != null) progress(3 + (int)(copied * 82 / total), "프로그램 파일 설치 중");
            }
        }
    }

    internal static Dictionary<string, object> ReadSettings(string path)
    {
        try { return new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(path, Encoding.UTF8)) ?? new Dictionary<string, object>(); }
        catch (IOException) { } catch (ArgumentException) { } catch (InvalidOperationException) { }
        return new Dictionary<string, object>();
    }
    internal static void SaveUpdatePreference(bool enabled)
    {
        Directory.CreateDirectory(Profile);
        string path = Path.Combine(Profile, "settings.json"), temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        var settings = ReadSettings(path); settings["automatic_updates"] = enabled;
        File.WriteAllText(temporary, new JavaScriptSerializer().Serialize(settings), new UTF8Encoding(false));
        if (File.Exists(path)) File.Replace(temporary, path, null); else File.Move(temporary, path);
    }
    internal static void Shortcut(string path, string target)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path));
        Type type = Type.GetTypeFromProgID("WScript.Shell"); object shell = Activator.CreateInstance(type), shortcut = null;
        try
        {
            shortcut = type.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { path });
            Type shortcutType = shortcut.GetType();
            shortcutType.InvokeMember("TargetPath", BindingFlags.SetProperty, null, shortcut, new object[] { target });
            shortcutType.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, shortcut, new object[] { Path.GetDirectoryName(target) });
            shortcutType.InvokeMember("IconLocation", BindingFlags.SetProperty, null, shortcut, new object[] { target + ",0" });
            shortcutType.InvokeMember("Save", BindingFlags.InvokeMethod, null, shortcut, null);
        }
        finally { if (shortcut != null) System.Runtime.InteropServices.Marshal.FinalReleaseComObject(shortcut); System.Runtime.InteropServices.Marshal.FinalReleaseComObject(shell); }
    }

    internal static void Install(bool desktop, bool? updates, Action<int, string> progress, Func<bool> cancelled, string targetFolder, bool register)
    {
        if (AppRunning(targetFolder)) throw new IOException("S.PDF를 닫은 뒤 다시 설치해주세요.");
        if (Directory.Exists(targetFolder) && !File.Exists(Path.Combine(targetFolder, Marker))) throw new IOException("설치 위치에 다른 폴더가 있습니다.\n" + targetFolder);
        string parent = Path.GetDirectoryName(Path.GetFullPath(targetFolder)); Directory.CreateDirectory(parent);
        string staging = Path.Combine(parent, "S.PDF-staging-" + Guid.NewGuid().ToString("N"));
        string backup = Path.Combine(parent, "S.PDF-backup-" + Guid.NewGuid().ToString("N"));
        bool backedUp = false, deployed = false;
        try
        {
            Extract(staging, progress, cancelled);
            File.WriteAllText(Path.Combine(staging, Marker), "S.PDF " + BuildInfo.Version);
            if (cancelled != null && cancelled()) throw new OperationCanceledException();
            if (Directory.Exists(targetFolder)) { Directory.Move(targetFolder, backup); backedUp = true; }
            Directory.Move(staging, targetFolder); deployed = true;
            if (progress != null) progress(90, "바로가기와 설정을 저장하는 중");
            if (register)
            {
                string exe = Path.Combine(targetFolder, "S.PDF.exe"); FileAssociations.Register(exe);
                string menu = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "S.PDF");
                Shortcut(Path.Combine(menu, "S.PDF.lnk"), exe); Shortcut(Path.Combine(menu, "프로그램 제거.lnk"), Path.Combine(targetFolder, "Uninstall.exe"));
                if (desktop) Shortcut(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "S.PDF.lnk"), exe);
                using (RegistryKey key = Registry.CurrentUser.CreateSubKey(RegistryPath))
                {
                    key.SetValue("DisplayName", "S.PDF"); key.SetValue("DisplayVersion", BuildInfo.Version); key.SetValue("Publisher", "S.PDF Contributors");
                    key.SetValue("InstallLocation", targetFolder); key.SetValue("DisplayIcon", exe); key.SetValue("UninstallString", "\"" + Path.Combine(targetFolder, "Uninstall.exe") + "\"");
                    key.SetValue("NoModify", 1, RegistryValueKind.DWord); key.SetValue("NoRepair", 1, RegistryValueKind.DWord); key.SetValue("DesktopShortcut", desktop ? 1 : 0, RegistryValueKind.DWord);
                    key.SetValue("EstimatedSize", 250000, RegistryValueKind.DWord);
                }
                if (updates.HasValue) SaveUpdatePreference(updates.Value);
            }
        }
        catch
        {
            if (deployed && File.Exists(Path.Combine(targetFolder, Marker))) InstallFiles.RemoveOwned(targetFolder);
            if (backedUp && Directory.Exists(backup) && !Directory.Exists(targetFolder)) Directory.Move(backup, targetFolder);
            throw;
        }
        finally
        {
            string resolved = Path.GetFullPath(staging);
            if (Directory.Exists(staging) && String.Equals(Path.GetDirectoryName(resolved), parent, StringComparison.OrdinalIgnoreCase) && Path.GetFileName(resolved).StartsWith("S.PDF-staging-", StringComparison.Ordinal)) Directory.Delete(staging, true);
        }
        if (backedUp && Directory.Exists(backup))
        {
            // Preserve files the user added inside the app folder, at the same paths.
            var owned = new HashSet<string>(File.ReadAllLines(Path.Combine(backup, "install-manifest.txt")), StringComparer.OrdinalIgnoreCase);
            owned.Add("install-manifest.txt"); owned.Add(Marker);
            foreach (string file in Directory.GetFiles(backup, "*", SearchOption.AllDirectories))
            {
                string relative = file.Substring(backup.Length + 1), destination = Path.Combine(targetFolder, relative);
                if (!owned.Contains(relative) && !File.Exists(destination)) { Directory.CreateDirectory(Path.GetDirectoryName(destination)); File.Copy(file, destination); }
            }
            try { InstallFiles.RemoveOwned(backup); } catch (IOException) { } catch (UnauthorizedAccessException) { }
        }
        if (progress != null) progress(100, "설치가 완료되었습니다.");
    }
}

internal sealed class BlueProgress : Control
{
    internal int Value;
    internal BlueProgress() { DoubleBuffered = true; Height = 7; }
    protected override void OnPaint(PaintEventArgs e) { e.Graphics.Clear(Color.FromArgb(239, 243, 250)); using (Brush brush = new SolidBrush(Color.FromArgb(53, 103, 237))) e.Graphics.FillRectangle(brush, 0, 0, Width * Value / 100, Height); }
}

internal sealed class SetupForm : Form
{
    private readonly Panel main = new Panel();
    private readonly CheckBox desktop = new CheckBox(), automatic = new CheckBox(), launch = new CheckBox();
    private readonly Button primary = new Button(), secondary = new Button();
    private readonly Label heading = new Label(), description = new Label(), steps = new Label(), note = new Label(), percent = new Label();
    private readonly BlueProgress progress = new BlueProgress();
    private bool busy, installed;
    private readonly bool preview;
    private volatile bool cancelled;
    private static readonly Color Ink = Color.FromArgb(32, 44, 66), Muted = Color.FromArgb(104, 117, 138), Blue = Color.FromArgb(53, 103, 237);

    protected override bool ShowWithoutActivation { get { return preview || base.ShowWithoutActivation; } }
    internal SetupForm(bool previewOnly = false)
    {
        preview = previewOnly;
        Text = "S.PDF 설치"; Font = new Font("맑은 고딕", 9); ClientSize = new Size(714, 495); BackColor = Color.White; ForeColor = Ink;
        FormBorderStyle = FormBorderStyle.FixedSingle; MaximizeBox = false; StartPosition = FormStartPosition.CenterScreen;
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        Panel brand = new Panel { Dock = DockStyle.Left, Width = 218, BackColor = Color.FromArgb(239, 243, 253) };
        brand.Controls.Add(new PictureBox { Left = 27, Top = 31, Width = 38, Height = 38, Image = Icon.ToBitmap(), SizeMode = PictureBoxSizeMode.Zoom });
        brand.Controls.Add(TextLabel("S.PDF", 76, 33, 120, 36, 20, Ink, true));
        brand.Controls.Add(TextLabel("문서 작업을\n한곳에서.", 27, 102, 175, 87, 19, Ink, true));
        brand.Controls.Add(TextLabel("보기부터 편집까지,\n매일 쓰는 PDF 도구.", 28, 201, 170, 50, 9, Muted, false));
        brand.Controls.Add(TextLabel("여러 문서, 하나의 공간\n\n선명한 고화질 캡처\n\n페이지와 글자 편집", 28, 283, 178, 110, 9, Muted, false));
        brand.Controls.Add(TextLabel("PDF는 내 컴퓨터에서\n처리합니다.", 28, 435, 178, 40, 8, Muted, false)); Controls.Add(brand);
        main.SetBounds(248, 29, 436, 453); Controls.Add(main);
        steps.SetBounds(0, 0, 435, 23); steps.ForeColor = Blue; steps.Font = new Font(Font.FontFamily, 8); main.Controls.Add(steps);
        heading.SetBounds(0, 48, 436, 43); heading.Font = new Font(Font.FontFamily, 19, FontStyle.Bold); main.Controls.Add(heading);
        description.SetBounds(0, 99, 436, 53); description.ForeColor = Muted; main.Controls.Add(description);
        desktop.SetBounds(0, 157, 430, 28); desktop.Text = "바탕화면에 바로가기 만들기"; desktop.Checked = true; main.Controls.Add(desktop);
        automatic.SetBounds(0, 218, 430, 28); automatic.Text = "자동 업데이트 사용"; automatic.Checked = true; main.Controls.Add(automatic);
        main.Controls.Add(TextLabel("바탕화면에서 S.PDF를 바로 실행합니다.", 23, 186, 405, 24, 8, Muted, false));
        main.Controls.Add(TextLabel("새 버전을 자동으로 내려받고, 작업을 마친 뒤 적용합니다.", 23, 247, 405, 45, 8, Muted, false));
        LinkLabel location = new LinkLabel { Text = "설치 위치와 추가 정보", Left = 0, Top = 321, AutoSize = true, LinkColor = Muted, Font = new Font(Font.FontFamily, 8) };
        location.LinkClicked += delegate { MessageBox.Show(this, SetupProgram.InstallPath + "\n\n현재 Windows 사용자에게 설치합니다.\n별도 Python 설치가 필요하지 않습니다.\n\n업데이트 배포처: github.com/JUNGHANGEUL/s-pdf", "S.PDF 설치 정보", MessageBoxButtons.OK, MessageBoxIcon.Information); }; main.Controls.Add(location);
        main.Controls.Add(new Panel { Left = 0, Top = 361, Width = 436, Height = 1, BackColor = Color.FromArgb(228, 232, 239) });
        primary.SetBounds(309, 379, 127, 40); primary.FlatStyle = FlatStyle.Flat; primary.FlatAppearance.BorderSize = 0; primary.BackColor = Blue; primary.ForeColor = Color.White; primary.Text = "설치 시작  →"; primary.Font = new Font(Font.FontFamily, 9, FontStyle.Bold); main.Controls.Add(primary);
        secondary.SetBounds(234, 379, 66, 40); secondary.Text = "취소"; secondary.FlatStyle = FlatStyle.Flat; secondary.FlatAppearance.BorderColor = Color.FromArgb(228, 232, 239); main.Controls.Add(secondary);
        note.SetBounds(0, 431, 436, 19); note.Text = "S.PDF " + BuildInfo.Version + " · 관리자 권한 없이 설치"; note.Font = new Font(Font.FontFamily, 8); note.ForeColor = Muted; main.Controls.Add(note);
        progress.SetBounds(0, 208, 436, 7); progress.Visible = false; main.Controls.Add(progress);
        percent.SetBounds(0, 173, 436, 29); percent.ForeColor = Blue; percent.Visible = false; main.Controls.Add(percent);
        launch.SetBounds(0, 293, 420, 28); launch.Text = "지금 S.PDF 실행"; launch.Checked = true; launch.Visible = false; main.Controls.Add(launch);
        primary.Click += InstallClicked; secondary.Click += delegate { if (busy) { cancelled = true; secondary.Enabled = false; secondary.Text = "취소 중"; } else Close(); };
        FormClosing += delegate(object sender, FormClosingEventArgs e) { if (busy) { cancelled = true; e.Cancel = true; } };
        AcceptButton = primary; CancelButton = secondary;
        heading.Text = "S.PDF를 설치합니다"; description.Text = "필요한 설정만 고르면 준비가 끝납니다."; steps.Text = "❶ 설치 준비     ─     ② 설치     ─     ③ 완료";
        object enabled; if (SetupProgram.ReadSettings(Path.Combine(SetupProgram.Profile, "settings.json")).TryGetValue("automatic_updates", out enabled)) automatic.Checked = !Object.Equals(enabled, false);
    }
    private static Label TextLabel(string text, int x, int y, int width, int height, float size, Color color, bool bold)
    { return new Label { Text = text, Left = x, Top = y, Width = width, Height = height, Font = new Font("맑은 고딕", size, bold ? FontStyle.Bold : FontStyle.Regular), ForeColor = color }; }
    private async void InstallClicked(object sender, EventArgs e)
    {
        if (installed) { if (launch.Checked) Process.Start(new ProcessStartInfo(Path.Combine(SetupProgram.InstallPath, "S.PDF.exe")) { UseShellExecute = false }); Close(); return; }
        bool desktopChoice = desktop.Checked, automaticChoice = automatic.Checked;
        busy = true; cancelled = false; primary.Enabled = false;
        foreach (Control control in main.Controls) if (control != heading && control != description && control != steps && control != primary && control != secondary && control != note) control.Visible = false;
        progress.Visible = true; percent.Visible = true; heading.Text = "곧 만날 수 있어요"; description.Text = "S.PDF를 사용할 준비를 하고 있습니다."; steps.Text = "① 설치 준비     ─     ❷ 설치     ─     ③ 완료";
        try
        {
            await Task.Run(() => { using (InstallLock.Acquire()) SetupProgram.Install(desktopChoice, automaticChoice, (value, text) => BeginInvoke((Action)(() => { progress.Value = value; progress.Invalidate(); percent.Text = text + "   " + value + "%"; if (value >= 90) secondary.Enabled = false; })), () => cancelled, SetupProgram.InstallPath, true); });
            installed = true; heading.Text = "준비가 끝났습니다"; description.Text = "이제 S.PDF에서 문서 작업을 시작하세요.\n\n설치가 완료되었습니다."; description.Height = 85;
            steps.Text = "① 설치 준비     ─     ② 설치     ─     ❸ 완료"; progress.Visible = false; percent.Visible = true; percent.Top = 224; percent.Height = 55; percent.Text = automaticChoice ? "자동 업데이트가 켜져 있습니다.\n새 버전은 문서를 닫고 종료할 때 적용합니다." : "자동 업데이트가 꺼져 있습니다."; percent.ForeColor = Muted;
            launch.Visible = true; secondary.Visible = false; primary.Text = "시작하기  →"; note.Text = "S.PDF " + BuildInfo.Version + " · 설치 완료";
        }
        catch (OperationCanceledException) { CloseAfterWork(); }
        catch (Exception error) { MessageBox.Show(this, error.Message, "S.PDF 설치", MessageBoxButtons.OK, MessageBoxIcon.Information); CloseAfterWork(); }
        finally { busy = false; if (!IsDisposed) primary.Enabled = true; }
    }
    private void CloseAfterWork() { busy = false; Close(); }
}
