using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: AssemblyTitle("S.PDF 제거")]
[assembly: AssemblyVersion("2.0.0.0")]

internal static class UninstallProgram
{
    private const string RegistryPath = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\S.PDF";
    [STAThread]
    private static int Main(string[] args)
    {
        Application.EnableVisualStyles();
        string installPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "S.PDF");
        try
        {
            if (args.Length == 2 && args[0] == "/remove")
            {
                int parentId;
                if (Int32.TryParse(args[1], out parentId))
                {
                    try { using (Process parent = Process.GetProcessById(parentId)) if (!parent.WaitForExit(15000)) throw new IOException("제거 프로그램을 다시 실행해주세요."); }
                    catch (ArgumentException) { }
                }
                Remove(installPath);
                MessageBox.Show("S.PDF를 제거했습니다.", "제거 완료", MessageBoxButtons.OK, MessageBoxIcon.Information); return 0;
            }
            if (!File.Exists(Path.Combine(installPath, ".spdf-install")))
                throw new IOException("현재 사용자 계정에 설치된 프로그램을 찾을 수 없습니다.");
            if (MessageBox.Show("S.PDF를 제거할까요?\n사용자의 PDF 파일은 그대로 보관됩니다.", "프로그램 제거", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return 0;
            string temp = Path.Combine(Path.GetTempPath(), "S.PDF-Uninstall-" + Guid.NewGuid().ToString("N") + ".exe");
            File.Copy(Application.ExecutablePath, temp);
            Process.Start(new ProcessStartInfo(temp, "/remove " + Process.GetCurrentProcess().Id) { UseShellExecute = false }); return 0;
        }
        catch (Exception error) { MessageBox.Show(error.Message, "프로그램 제거", MessageBoxButtons.OK, MessageBoxIcon.Information); return 1; }
    }

    private static void DeleteShortcut(string path, string expectedFolder)
    {
        if (!File.Exists(path)) return;
        Type shellType = Type.GetTypeFromProgID("WScript.Shell"); object shell = Activator.CreateInstance(shellType); object shortcut = null;
        try
        {
            shortcut = shellType.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { path });
            string target = (string)shortcut.GetType().InvokeMember("TargetPath", BindingFlags.GetProperty, null, shortcut, null);
            if (String.Equals(Path.GetDirectoryName(target), expectedFolder, StringComparison.OrdinalIgnoreCase)) File.Delete(path);
        }
        finally
        {
            if (shortcut != null) System.Runtime.InteropServices.Marshal.FinalReleaseComObject(shortcut);
            System.Runtime.InteropServices.Marshal.FinalReleaseComObject(shell);
        }
    }

    private static void Remove(string path)
    {
        if (!File.Exists(Path.Combine(path, ".spdf-install"))) throw new IOException("설치 폴더를 확인할 수 없습니다.");
        foreach (Process process in Process.GetProcessesByName("S.PDF"))
        {
            using (process)
            {
                try { if (String.Equals(process.MainModule.FileName, Path.Combine(path, "S.PDF.exe"), StringComparison.OrdinalIgnoreCase)) throw new IOException("S.PDF를 닫은 뒤 다시 제거해주세요."); }
                catch (System.ComponentModel.Win32Exception) { }
                catch (InvalidOperationException) { }
            }
        }
        InstallFiles.RemoveOwned(path);
        FileAssociations.Unregister(Path.Combine(path, "S.PDF.exe"));
        string menu = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "S.PDF");
        DeleteShortcut(Path.Combine(menu, "S.PDF.lnk"), path);
        DeleteShortcut(Path.Combine(menu, "프로그램 제거.lnk"), path);
        DeleteShortcut(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "S.PDF.lnk"), path);
        if (Directory.Exists(menu) && Directory.GetFileSystemEntries(menu).Length == 0) Directory.Delete(menu);
        using (RegistryKey key = Registry.CurrentUser.OpenSubKey(RegistryPath))
        {
            if (key != null && String.Equals(key.GetValue("InstallLocation") as string, path, StringComparison.OrdinalIgnoreCase))
                Registry.CurrentUser.DeleteSubKeyTree(RegistryPath, false);
        }
    }
}
