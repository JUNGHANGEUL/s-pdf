using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("S.PDF")]
[assembly: System.Reflection.AssemblyVersion(BuildInfo.AssemblyVersion)]

internal static class Launcher
{
    private static string Quote(string value)
    {
        StringBuilder result = new StringBuilder("\"");
        int slashes = 0;
        foreach (char character in value)
        {
            if (character == '\\') { slashes++; continue; }
            if (character == '"') { result.Append('\\', slashes * 2 + 1); result.Append('"'); slashes = 0; continue; }
            result.Append('\\', slashes); slashes = 0; result.Append(character);
        }
        result.Append('\\', slashes * 2); result.Append('"'); return result.ToString();
    }
    [STAThread]
    private static int Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        bool testing = Array.IndexOf(args, "--self-test") >= 0;
        try
        {
            string executable = Path.Combine(root, "runtime", "pythonw.exe");
            string script = Path.Combine(root, "_internal", "main.py");
            ProcessStartInfo info = new ProcessStartInfo(executable);
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            info.WorkingDirectory = root;
            info.RedirectStandardOutput = true;
            info.RedirectStandardError = true;
            info.Arguments = "-I -B " + Quote(script);
            foreach (string argument in args) info.Arguments += " " + Quote(argument);
            string windows = Environment.GetFolderPath(Environment.SpecialFolder.Windows);
            info.EnvironmentVariables["PATH"] = String.Join(";", new string[] {
                Path.Combine(root, "runtime"), Path.Combine(root, "_internal"),
                Path.Combine(root, "_internal", "PySide6"), Path.Combine(root, "_internal", "shiboken6"),
                Path.Combine(windows, "System32"), windows });
            Process child;
            using (InstallLock.Acquire()) { child = Process.Start(info); }
            using (Process process = child)
            {
                var output = process.StandardOutput.ReadToEndAsync();
                var errors = process.StandardError.ReadToEndAsync();
                process.WaitForExit();
                string stderr = errors.GetAwaiter().GetResult();
                string stdout = output.GetAwaiter().GetResult();
                if (process.ExitCode != 0)
                {
                    string logRoot = Environment.GetEnvironmentVariable("SPDF_DATA_DIR");
                    if (String.IsNullOrEmpty(logRoot)) logRoot = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "S.PDF");
                    Directory.CreateDirectory(logRoot);
                    File.WriteAllText(Path.Combine(logRoot, "launcher-error.txt"), stderr + "\r\n" + stdout, Encoding.UTF8);
                    if (!testing) MessageBox.Show("S.PDF를 시작하지 못했습니다.\n" + stderr, "S.PDF", MessageBoxButtons.OK, MessageBoxIcon.Information);
                }
                return process.ExitCode;
            }
        }
        catch (Exception error)
        {
            if (!testing) MessageBox.Show(error.Message, "S.PDF", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return 1;
        }
    }
}
